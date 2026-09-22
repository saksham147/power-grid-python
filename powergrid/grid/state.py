"""Grid's own view of the system it regulates: the latest known output of every plant
(from Producer) and the latest known demand of every zone (from Distributor's merged
zone balance), kept in memory rather than queried back from either service.

This is ``distributor.distribution.GridStateTracker`` again, field-for-field: same
reasoning about a recording *replacing* what was known rather than accumulating it
(each reading already carries that plant's or zone's total figure, not a delta), the
same MW-to-kW conversion for ``total_supply_kw``, and the same known limitation that a
deactivated plant or a deleted zone leaves its last known figure here forever, since
neither upstream event announces its own absence. Kept as Grid's own copy rather than
shared, the same way every cross-service concept in this project is duplicated per
app rather than imported.

Demand is read from Distributor's zone-balance broadcast, not from Customer's raw
demand directly: Grid's status is a view downstream of the merge, not a second copy
of it.
"""
import threading

_KW_PER_MW = 1000.0


class GridStateTracker:
    """Guarded by a lock rather than left to the GIL: two different callers (a
    producer reading, a zone-balance reading) can arrive concurrently, and a torn
    read of a total while a write is in progress must not be possible.
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
