"""Wire-shaped payloads distributor publishes.

Distributor *consumes* producer output and zone demand as plain, duck-typed signal
payloads -- it never imports producer's or customer's own event classes, reading only
the attribute names their signals are documented to carry (``producer_id``/
``output_mw``; ``zone_id``/``zone_name``/``tick``/``demand_kw``/``timestamp``). That is
what a structural, rather than a shared, contract means in a single process: no shared
class between apps, just an agreed shape -- see ``kafka.py``.

What distributor itself *produces*, it owns outright, the same way ``producer.events``
and ``customer.infrastructure.kafka`` own theirs.
"""
import dataclasses
import datetime

from .domain import ZoneDistribution


@dataclasses.dataclass(frozen=True)
class ZoneBalanceEvent:
    """One zone's merged supply-and-demand picture, published for anything downstream.

    The wire counterpart of ``distribution.ZoneDistribution``. Kept as its own type on
    purpose, the same way ``customer``'s wire event is kept apart from its domain
    ``ZoneDemand``: this is a contract other apps compile against, so it can evolve for
    them without dragging the merge logic's own domain type along.
    """

    zone_id: str
    zone_name: str
    tick: int
    demand_kw: float
    supplied_kw: float
    balance_kw: float
    timestamp: datetime.datetime

    @classmethod
    def of(cls, distribution: ZoneDistribution) -> 'ZoneBalanceEvent':
        return cls(
            zone_id=distribution.zone_id,
            zone_name=distribution.zone_name,
            tick=distribution.tick,
            demand_kw=distribution.demand_kw,
            supplied_kw=distribution.supplied_kw,
            balance_kw=distribution.balance_kw,
            timestamp=distribution.at,
        )


@dataclasses.dataclass(frozen=True)
class ZoneCapacityEvent:
    """A zone's capacity configuration, broadcast for anything downstream (Billing,
    eventually) that needs it, without duplicating the capacity data entry itself.

    ``capacity_kw`` of ``None`` means "removed": the zone reverts to uncapped, billed
    at the normal rate only.
    """

    zone_id: str
    zone_name: str
    capacity_kw: float | None
    timestamp: datetime.datetime
