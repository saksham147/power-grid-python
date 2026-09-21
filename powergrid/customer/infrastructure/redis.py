"""Redis adapters for the customer app: zones and consumer units as key-value entries,
and the latest demand as one cached snapshot.

Layout, one hash per concern:

* ``customer:zones``  -- one field per zone, keyed by zone id, the zone as JSON.
* ``customer:units``  -- one field per consumer unit, keyed by unit id, the unit as JSON.
* ``customer:demand:latest`` -- the latest tick's demand: a ``zone:<id>`` field per zone
  plus ``tick``, ``total_kw`` and ``updated_at``.

Zones and units are configuration that must change at runtime and survive a restart. They
are only ever read by id or "all of them", so a finer-grained layout would buy nothing.

Reads that cannot reach Redis raise. They deliberately do not degrade to an empty fleet:
a tick that could not see its configuration must not publish, or store, a made-up
zero-demand snapshot over the last good one. The tick listener logs the failed tick and
the next tick simply tries again. The exception is ``DemandStateStore.save``, which by
its port's contract never raises: losing one snapshot costs a sample of a continuous
signal, never the tick.
"""
import datetime
import json
import logging

import redis
from django.conf import settings

from ..application import (
    ConsumerUnitRepository, CurrentDemand, DemandSnapshot, DemandStateStore, ZoneRepository,
)
from ..domain import ConsumerUnit, DemandProfile, Zone

logger = logging.getLogger(__name__)

ZONES_KEY = 'customer:zones'
UNITS_KEY = 'customer:units'
DEMAND_KEY = 'customer:demand:latest'

# Zone fields are prefixed so a zone id can never collide with a metadata field
# (a zone may legitimately be called "tick").
_ZONE_FIELD_PREFIX = 'zone:'

# A slow or dead Redis must not hold up the tick loop. Every call is bounded by these, so
# the most a tick can lose to an unreachable Redis is about this long.
CONNECT_TIMEOUT_SECONDS = 1.0
SOCKET_TIMEOUT_SECONDS = 1.0

# A failing state write is logged the first time and then once per this many, so an
# outage of hours cannot flood the log at one line per tick.
_LOG_EVERY = 100


def connect(url: str | None = None) -> redis.Redis:
    """A Redis client for ``url`` (default ``settings.REDIS_URL``), with bounded timeouts.

    Connects lazily, on first use. Responses are decoded to ``str``, which is what every
    adapter here expects.
    """
    return redis.Redis.from_url(
        url or settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
    )


def _zone_to_json(zone: Zone) -> str:
    return json.dumps({'zone_id': zone.zone_id, 'name': zone.name})


def _zone_from_json(text: str) -> Zone:
    data = json.loads(text)
    return Zone(zone_id=data['zone_id'], name=data['name'])


def _unit_to_json(unit: ConsumerUnit) -> str:
    return json.dumps({
        'unit_id': unit.unit_id,
        'zone_id': unit.zone_id,
        'name': unit.name,
        'type': unit.type.name,
        'capacity_kw': unit.capacity_kw,
    })


def _unit_from_json(text: str) -> ConsumerUnit:
    data = json.loads(text)
    return ConsumerUnit(
        unit_id=data['unit_id'],
        zone_id=data['zone_id'],
        name=data['name'],
        type=DemandProfile[data['type']],
        capacity_kw=data['capacity_kw'],
    )


def _decode_all(entries: dict[str, str], decode, key: str) -> list:
    """Decodes every entry of a hash, in id order.

    An entry that no longer decodes (edited by hand, say) is logged by its field and
    skipped, so one bad record cannot take the rest of the fleet down with it. Records
    written by these adapters always decode: they only ever store validated objects.
    """
    decoded = []
    for field in sorted(entries):
        try:
            decoded.append(decode(entries[field]))
        except (ValueError, KeyError, TypeError):
            logger.error('Skipping unreadable entry %r in %s', field, key, exc_info=True)
    return decoded


class RedisZoneRepository(ZoneRepository):
    """Zones in the ``customer:zones`` hash."""

    def __init__(self, client: redis.Redis):
        self._client = client

    def find_all(self) -> list[Zone]:
        return _decode_all(self._client.hgetall(ZONES_KEY), _zone_from_json, ZONES_KEY)

    def save(self, zone: Zone) -> None:
        self._client.hset(ZONES_KEY, zone.zone_id, _zone_to_json(zone))

    def delete(self, zone_id: str) -> None:
        self._client.hdel(ZONES_KEY, zone_id)


class RedisConsumerUnitRepository(ConsumerUnitRepository):
    """Consumer units in the ``customer:units`` hash -- the same shape as the zones,
    one level down."""

    def __init__(self, client: redis.Redis):
        self._client = client

    def find_all(self) -> list[ConsumerUnit]:
        return _decode_all(self._client.hgetall(UNITS_KEY), _unit_from_json, UNITS_KEY)

    def save(self, unit: ConsumerUnit) -> None:
        self._client.hset(UNITS_KEY, unit.unit_id, _unit_to_json(unit))

    def delete(self, unit_id: str) -> None:
        self._client.hdel(UNITS_KEY, unit_id)

    def delete_by_zone_id(self, zone_id: str) -> None:
        # Entries that no longer decode are left alone: their zone cannot be known.
        doomed = []
        for field, text in self._client.hgetall(UNITS_KEY).items():
            try:
                if _unit_from_json(text).zone_id == zone_id:
                    doomed.append(field)
            except (ValueError, KeyError, TypeError):
                continue
        if doomed:
            self._client.hdel(UNITS_KEY, *doomed)


class RedisDemandStateStore(DemandStateStore):
    """The latest demand, in the ``customer:demand:latest`` hash.

    Every zone plus the tick metadata is written in one round trip, however many zones
    there are; nothing reads a zone in isolation. The hash is *replaced*, not merged, in
    one transaction, so it is always exactly the latest snapshot: a zone deleted since
    the last tick does not linger with a stale figure, and a reader never sees a
    half-written one.

    Only demand figures are stored. A zone's name and unit count are configuration, and
    history belongs to the published events; a cache that tried to be either would be a
    worse copy of something that already exists. Whoever needs both joins ``current()``
    against the zone repository.

    Floats are stored at full precision, so ``current()`` returns exactly what ``save``
    was given.
    """

    def __init__(self, client: redis.Redis):
        self._client = client
        self._failures = 0

    @property
    def failure_count(self) -> int:
        """Failed state writes since this store was created."""
        return self._failures

    def save(self, snapshot: DemandSnapshot) -> None:
        try:
            fields = {f'{_ZONE_FIELD_PREFIX}{zone.zone_id}': repr(zone.demand_kw) for zone in snapshot.zones}
            fields['tick'] = str(snapshot.tick)
            fields['total_kw'] = repr(snapshot.total_kw)
            fields['updated_at'] = snapshot.at.isoformat()

            with self._client.pipeline(transaction=True) as pipe:
                pipe.delete(DEMAND_KEY)
                pipe.hset(DEMAND_KEY, mapping=fields)
                pipe.execute()
        except Exception:
            self._failures += 1
            if self._failures == 1 or self._failures % _LOG_EVERY == 0:
                logger.error('Failed to write demand state to Redis (%d failures so far); the simulation continues',
                             self._failures, exc_info=True)

    def current(self) -> CurrentDemand:
        """The latest saved snapshot, or ``CurrentDemand.none()`` before the first tick.

        Raises if Redis cannot be reached: the caller is a request that is waiting on the
        answer and should be told. A hash that does not parse is logged and treated as
        empty; the next tick rewrites it.
        """
        fields = self._client.hgetall(DEMAND_KEY)
        if not fields:
            return CurrentDemand.none()

        try:
            return _current_demand_from(fields)
        except (ValueError, KeyError, TypeError):
            logger.error('Unreadable demand state in %s; treating it as empty until the next tick',
                         DEMAND_KEY, exc_info=True)
            return CurrentDemand.none()


def _current_demand_from(fields: dict[str, str]) -> CurrentDemand:
    by_zone: dict[str, float] = {}
    tick = 0
    total_kw = 0.0
    updated_at = None

    for name in sorted(fields):
        value = fields[name]
        if name.startswith(_ZONE_FIELD_PREFIX):
            by_zone[name[len(_ZONE_FIELD_PREFIX):]] = float(value)
        elif name == 'tick':
            tick = int(value)
        elif name == 'total_kw':
            total_kw = float(value)
        elif name == 'updated_at':
            updated_at = datetime.datetime.fromisoformat(value)

    return CurrentDemand(tick=tick, updated_at=updated_at, total_kw=total_kw, demand_by_zone_id=by_zone)
