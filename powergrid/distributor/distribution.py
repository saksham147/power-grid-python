"""The merge use case: fold incoming supply into ``GridStateTracker``, and on every
incoming demand reading, merge it against the tracker's current state into one zone's
balance -- log it, then publish it. Alongside it, the zone-capacity admin use case:
create, update and delete a zone's assigned capacity ceiling.

Deliberately free of Django, the same way ``customer.application`` is: both use cases
depend only on the ports below, which is what keeps the allocation math and the capacity
admin logic testable with fakes and no database or messaging in the picture.

Callers pass plain values (a plant id and its output, a zone id and its demand), not a
wire-shaped event -- the same shape ``customer.application.DemandSimulator.tick`` takes
a bare tick number. Unpacking an incoming message into these values, and shaping what
gets published on the way out, belongs to a future messaging adapter, not here.

Why demand, not a tick, drives the merge: producer output and zone demand each arrive on
their own independent schedule, with no ordering guarantee against each other, so a merge
tied to the shared clock's tick would just as often run before this tick's own figures
had arrived as after. Reacting directly to each demand reading instead means the demand
side of every balance is exactly current; only the supply side can lag, which
``GridStateTracker`` documents below.
"""
import abc
import datetime
import logging
import threading

from .domain import ZoneCapacity, ZoneDistribution

logger = logging.getLogger(__name__)

_KW_PER_MW = 1000.0


class GridStateTracker:
    """The current view of the grid: the latest known output of every plant, and the
    latest known demand of every zone, kept in memory rather than queried back from
    either upstream.

    Recording *replaces* what was known about a plant or zone rather than adding to it:
    each reading already carries that plant's or zone's total figure, not a delta.

    A known limitation: neither side ever reports "this plant/zone is gone" -- a
    deactivated plant or a deleted zone simply stops sending readings -- so a plant or
    zone that stops reporting leaves its last known figure here forever, gently
    overstating whichever total it belonged to. Acceptable while fleet and zone
    membership rarely change mid-run; real eviction would need a signal neither side
    currently sends.

    Guarded by a lock rather than left to the GIL: two different callers (a producer
    reading, a zone reading) can arrive concurrently, and a torn read of "total" while
    a write is in progress must not be possible.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._output_mw_by_plant: dict[int, float] = {}
        self._demand_kw_by_zone: dict[str, float] = {}

    def record_supply(self, plant_id: int, output_mw: float) -> None:
        with self._lock:
            self._output_mw_by_plant[plant_id] = output_mw

    def record_demand(self, zone_id: str, demand_kw: float) -> None:
        with self._lock:
            self._demand_kw_by_zone[zone_id] = demand_kw

    def total_supply_kw(self) -> float:
        """Sum of every plant's latest known output, converted from MW to kW."""
        with self._lock:
            return sum(self._output_mw_by_plant.values()) * _KW_PER_MW

    def total_demand_kw(self) -> float:
        """Sum of every zone's latest known demand, already in kW."""
        with self._lock:
            return sum(self._demand_kw_by_zone.values())

    def demand_kw_for(self, zone_id: str) -> float:
        """One zone's latest known demand, in kW -- 0 if it has never reported. For a
        zone-capacity view, to show current draw against an assigned capacity."""
        with self._lock:
            return self._demand_kw_by_zone.get(zone_id, 0.0)

    def tracked_plant_count(self) -> int:
        """How many distinct plants have reported at least once. Status only."""
        with self._lock:
            return len(self._output_mw_by_plant)

    def tracked_zone_count(self) -> int:
        """How many distinct zones have reported at least once. Status only."""
        with self._lock:
            return len(self._demand_kw_by_zone)


class DistributionLogger(abc.ABC):
    """Outbound port: records a merged balance as a permanent log entry.

    Implementations must not raise: ``DistributionService`` treats a failure here as
    independent of ``BalancePublisher``'s own outcome, not a reason to skip it.
    """

    @abc.abstractmethod
    def log(self, distribution: ZoneDistribution) -> None:
        ...


class BalancePublisher(abc.ABC):
    """Outbound port: publishes a merged balance to whatever is downstream.

    Implementations must not raise: ``DistributionService`` treats a failure here as
    independent of ``DistributionLogger``'s own outcome, not a reason to skip it.
    """

    @abc.abstractmethod
    def publish(self, distribution: ZoneDistribution) -> None:
        ...


class DistributionService:
    """Merges one zone's demand against the fleet's current total supply.

    Plants carry no zone of their own, so fleet-wide supply is split across zones in
    proportion to each zone's share of total demand: a zone asking for twice as much is
    allocated twice as much of whatever the fleet is producing. That makes
    ``balance_kw`` track the grid's overall surplus or shortfall, scaled by zone size,
    rather than a per-zone transmission model there is no data to support.

    That share is computed against ``GridStateTracker.total_demand_kw()`` as it stands
    the instant a reading arrives, not a settled round's worth: the first zone to report
    is momentarily allocated the whole of whatever total is known so far, and the split
    only reaches the true ratio once every zone has reported at least once. With
    readings arriving every few seconds this converges immediately and is not visible in
    practice.
    """

    def __init__(self, state: GridStateTracker, logger_port: DistributionLogger, publisher: BalancePublisher):
        self._state = state
        self._logger = logger_port
        self._publisher = publisher

    def on_producer_output(self, plant_id: int, output_mw: float) -> None:
        """Folds one plant's latest output into the tracked state. Nothing to merge or
        publish yet -- that happens the next time some zone reports its demand."""
        self._state.record_supply(plant_id, output_mw)

    def on_zone_demand(self, zone_id: str, zone_name: str, tick: int, demand_kw: float,
                        at: datetime.datetime) -> ZoneDistribution:
        """Merges one zone's demand against the fleet's current total supply, logs the
        result, and publishes it.

        The log write and the publish are independent output ports, exactly like
        ``customer.application.DemandSimulator.tick``: one failing must not cost the
        other, since each already happened as far as its own downstream is concerned.

        Returns the merged balance, for callers that want it (mainly tests).
        """
        self._state.record_demand(zone_id, demand_kw)

        total_demand_kw = self._state.total_demand_kw()
        total_supply_kw = self._state.total_supply_kw()
        share = demand_kw / total_demand_kw if total_demand_kw > 0 else 0.0
        supplied_kw = share * total_supply_kw
        balance_kw = supplied_kw - demand_kw

        distribution = ZoneDistribution(zone_id, zone_name, tick, demand_kw, supplied_kw, balance_kw, at)

        self._guard('record log', lambda: self._logger.log(distribution))
        self._guard('publish', lambda: self._publisher.publish(distribution))

        return distribution

    @staticmethod
    def _guard(what: str, action) -> None:
        """Runs one output port, absorbing anything it raises -- see
        ``customer.application.DemandSimulator._guard`` for why: neither port is
        allowed to cost the other, or the reading, its own outcome."""
        try:
            action()
        except Exception:
            logger.exception('Distribution %s failed; the pipeline continues', what)


class ZoneCapacityRepository(abc.ABC):
    """Outbound port: persists zone-capacity configuration."""

    @abc.abstractmethod
    def find_by_id(self, zone_id: str) -> ZoneCapacity | None:
        ...

    @abc.abstractmethod
    def find_all(self) -> list[ZoneCapacity]:
        ...

    def save(self, capacity: ZoneCapacity) -> None:
        """Adds a zone's capacity, or replaces one with the same id."""
        raise NotImplementedError

    def delete(self, zone_id: str) -> None:
        """Removes a zone's capacity by id. A no-op if none was assigned."""


class ZoneCapacityPublisher(abc.ABC):
    """Outbound port: broadcasts a zone's capacity configuration to whatever is
    downstream.

    Implementations must not raise: ``ZoneCapacityService`` treats a publish failure as
    independent of the repository write's own outcome, the same shape
    ``BalancePublisher`` already documents for ``DistributionService``.

    ``capacity_kw`` of ``None`` means "removed": the zone reverts to uncapped.
    """

    @abc.abstractmethod
    def publish(self, zone_id: str, zone_name: str, capacity_kw: float | None,
                at: datetime.datetime) -> None:
        ...


class ZoneCapacityNotFoundException(Exception):
    """No capacity is assigned to this zone -- there is nothing to update or delete."""

    def __init__(self, zone_id: str):
        super().__init__(f'No capacity assigned to zone {zone_id}')


class ZoneCapacityService:
    """Create, update and delete a zone's assigned power capacity: persist it, then
    broadcast the change -- the same "write, then independently publish" shape
    ``DistributionService`` already uses, so a publish failure never costs the write its
    own outcome.
    """

    def __init__(self, repository: ZoneCapacityRepository, publisher: ZoneCapacityPublisher):
        self._repository = repository
        self._publisher = publisher

    def list(self) -> list[ZoneCapacity]:
        return self._repository.find_all()

    def upsert(self, zone_id: str, zone_name: str, capacity_kw: float) -> ZoneCapacity:
        """Adds a zone's capacity, or replaces it if one is already assigned -- an
        upsert, not an update-or-404, so a repeated call is always safe."""
        capacity = ZoneCapacity(zone_id, zone_name, capacity_kw)
        self._repository.save(capacity)
        self._publisher.publish(zone_id, zone_name, capacity_kw, _now())
        return capacity

    def delete(self, zone_id: str) -> None:
        """Removes a zone's assigned capacity.

        Raises ``ZoneCapacityNotFoundException`` if none is assigned -- there being
        nothing to delete is the caller's mistake, unlike ``upsert``'s idempotent
        create-or-replace.
        """
        existing = self._repository.find_by_id(zone_id)
        if existing is None:
            raise ZoneCapacityNotFoundException(zone_id)

        self._repository.delete(zone_id)
        self._publisher.publish(zone_id, existing.zone_name, None, _now())


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)
