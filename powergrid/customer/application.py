"""The use case: given a tick, aggregate every zone's units into that zone's demand and
hand the result to the output ports.

.

It knows nothing about Kafka, Redis or Grid -- only that the tick number comes from
somewhere outside it, zones and units come from repositories read fresh every time, and
demand goes somewhere to be published and somewhere to be recorded. The one thing it
does lean on is ``simulation.clock``, the project's single canonical tick-to-time
conversion (pure functions, no framework), where the Java service kept its own copy.
"""
import abc
import dataclasses
import datetime
import logging

from simulation.clock import day_number, is_weekend, minute_of_day, time_of_day

from .domain import ConsumerUnit, Season, Zone, ZoneDemand, demand_kw

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class DemandSnapshot:
    """One tick's worth of demand: every zone, plus the context they share.

    Tick number, simulated time and wall-clock instant are identical across a tick's
    zones, so they live here rather than being repeated on each ``ZoneDemand``. Giving
    the whole tick a name is also what lets both output ports take a single argument,
    which enforces batching by the type rather than leaving it to an adapter's
    discretion.

    ``at`` is when the tick ran, shared by every record it produces so they can be
    correlated across stores. ``total_kw`` is derived in ``of`` and nowhere else, so it
    cannot drift out of step with the list it describes.
    """

    tick: int
    simulated_time: str
    at: datetime.datetime
    zones: tuple[ZoneDemand, ...]
    total_kw: float

    @classmethod
    def of(cls, tick: int, simulated_time: str, at: datetime.datetime,
           zones: list[ZoneDemand]) -> 'DemandSnapshot':
        zones = tuple(zones)
        return cls(tick, simulated_time, at, zones, sum(zone.demand_kw for zone in zones))


@dataclasses.dataclass(frozen=True)
class CurrentDemand:
    """The latest demand, as recovered from ``DemandStateStore.current()``.

    Deliberately thinner than ``DemandSnapshot``: a zone's name and unit count are not
    expected to reach the store, so this carries only what a read can recover -- zone id
    and demand. A caller wanting the full picture joins ``demand_by_zone_id`` against
    the zone configuration itself.
    """

    tick: int
    updated_at: datetime.datetime | None
    total_kw: float
    demand_by_zone_id: dict[str, float]

    @classmethod
    def none(cls) -> 'CurrentDemand':
        """Before the first tick, or on a fresh install with nothing stored yet."""
        return cls(tick=0, updated_at=None, total_kw=0.0, demand_by_zone_id={})


class ZoneRepository(abc.ABC):
    """Outbound port: the zones a tick should simulate.

    ``find_all`` is the only method ``DemandSimulator`` calls, and it calls it fresh on
    every tick rather than once at construction -- that is what lets a zone added or
    removed at runtime take effect on the very next tick instead of needing a restart.
    It stays the only abstract method so a test fake can be tiny. ``save`` and
    ``delete`` are for the zone-management API, which is a different caller.
    """

    @abc.abstractmethod
    def find_all(self) -> list[Zone]:
        ...

    def save(self, zone: Zone) -> None:
        """Adds a zone, or replaces one with the same id."""
        raise NotImplementedError

    def delete(self, zone_id: str) -> None:
        """Removes a zone by id. A no-op if no such zone existed."""


class ConsumerUnitRepository(abc.ABC):
    """Outbound port: the units a tick should simulate -- the ``ZoneRepository`` of the
    unit world. ``find_all`` is read fresh every tick, exactly like the zones', so a
    unit added, edited or removed at runtime takes effect on the very next tick.
    """

    @abc.abstractmethod
    def find_all(self) -> list[ConsumerUnit]:
        ...

    def find_by_zone_id(self, zone_id: str) -> list[ConsumerUnit]:
        return [unit for unit in self.find_all() if unit.zone_id == zone_id]

    def save(self, unit: ConsumerUnit) -> None:
        """Adds a unit, or replaces one with the same id."""
        raise NotImplementedError

    def delete(self, unit_id: str) -> None:
        """Removes a unit by id. A no-op if no such unit existed."""

    def delete_by_zone_id(self, zone_id: str) -> None:
        """Removes every unit belonging to a zone -- the cascade a zone deletion needs."""


class DemandPublisher(abc.ABC):
    """Outbound port: publishes a tick's zone demand to whatever is downstream.

    Takes the whole snapshot rather than one zone, so a chatty implementation is not
    expressible against this interface. Implementations must not raise and must not
    block: an outage downstream is expected to cost the events, never the simulation.
    """

    @abc.abstractmethod
    def publish(self, snapshot: DemandSnapshot) -> None:
        ...


class DemandStateStore(abc.ABC):
    """Outbound port: records the latest demand state for anything that wants to read it.

    Latest state only -- history belongs to the event stream, not to a cache. ``save``
    shares ``DemandPublisher``'s contract: one call per tick, never raising, never
    blocking. ``current`` is a separate concern -- reading back what a tick already
    saved, for a caller that can afford to wait (a request, not the tick loop) -- so it
    has a default instead of being a second thing every implementation must provide.
    """

    @abc.abstractmethod
    def save(self, snapshot: DemandSnapshot) -> None:
        ...

    def current(self) -> CurrentDemand:
        """The latest saved snapshot, or ``CurrentDemand.none()`` if nothing has been
        saved yet."""
        return CurrentDemand.none()


class DemandSimulator:
    """Runs one tick: aggregate every zone's units into that zone's demand, then hand the
    result to the output ports.

    Cost is proportional to the number of *units*, not to any population they
    represent: each unit is one closed-form evaluation, summed per zone. A unit whose
    zone does not exist contributes to nothing, and a zone with no units reports zero.
    """

    def __init__(self, zones: ZoneRepository, units: ConsumerUnitRepository,
                 publisher: DemandPublisher, state_store: DemandStateStore):
        self._zones = zones
        self._units = units
        self._publisher = publisher
        self._state_store = state_store
        self._last_tick = 0

    def tick(self, tick_number: int) -> DemandSnapshot:
        """Runs one tick, for the tick number the shared clock issued, and returns what it
        produced. A tick over no zones still produces (and publishes) an empty snapshot."""
        current_zones = self._zones.find_all()
        if not current_zones:
            logger.warning('No zones configured; tick %s reports zero demand', tick_number)

        minute = minute_of_day(tick_number)
        weekend = is_weekend(tick_number)
        season = Season.of(day_number(tick_number))

        units_by_zone: dict[str, list[ConsumerUnit]] = {}
        for unit in self._units.find_all():
            units_by_zone.setdefault(unit.zone_id, []).append(unit)

        demands = []
        for zone in current_zones:
            zone_units = units_by_zone.get(zone.zone_id, [])
            kw = sum(demand_kw(unit, minute, weekend, season) for unit in zone_units)
            demands.append(ZoneDemand(zone.zone_id, zone.name, len(zone_units), kw))

        snapshot = DemandSnapshot.of(
            tick_number, time_of_day(tick_number), datetime.datetime.now(datetime.timezone.utc), demands)
        self._last_tick = tick_number

        # Publish before recording state. Both ports are guarded independently, so this
        # does not order their completion -- but if the process dies between the two, a
        # missed event is a permanent gap in the stream, whereas a stale state store is
        # simply overwritten by the next tick.
        self._guard('publish', lambda: self._publisher.publish(snapshot))
        self._guard('state save', lambda: self._state_store.save(snapshot))

        logger.debug('Tick %s (%s): %.0f kW across %d zones',
                     tick_number, snapshot.simulated_time, snapshot.total_kw, len(demands))
        return snapshot

    def current_tick(self) -> int:
        """The tick most recently run; 0 before the first."""
        return self._last_tick

    @staticmethod
    def _guard(what: str, action) -> None:
        """Runs one output port, absorbing anything it raises.

        Both ports are specified never to raise. This is defence against one of them
        breaking that contract anyway -- a serialisation fault, an unexpected None --
        which must not cost the tick or stop the other port receiving the same snapshot.
        """
        try:
            action()
        except Exception:
            logger.exception('Demand %s failed; the simulation continues', what)
