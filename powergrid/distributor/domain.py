"""Framework-free values for the distributor app: one zone's merged supply-and-demand
picture, and a zone's assigned capacity ceiling.

No Django import anywhere in this file, the same discipline ``customer.domain`` follows,
so these can be reasoned about and tested with no database, cache or web framework in
the picture.
"""
import dataclasses
import datetime
import math


def _require_text(value, message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)


def _require_positive_finite(value, message: str) -> None:
    # Booleans are rejected (bool is a subclass of int), and so are NaN and Infinity,
    # which would otherwise slip past a bare "> 0" comparison and corrupt every total
    # they joined.
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(message)


@dataclasses.dataclass(frozen=True)
class ZoneDistribution:
    """One zone's merged supply-and-demand picture for a tick: what it asked for,
    what share of the fleet's supply it was allocated, and the balance between them.

    ``balance_kw`` is ``supplied_kw - demand_kw``: positive means the zone was
    allocated more than it asked for (a fleet-wide surplus, shared out by zone size),
    negative means less (a shortfall). It says nothing about a hard delivery cap --
    that is what ``ZoneCapacity`` is for, and the two are independent.
    """

    zone_id: str
    zone_name: str
    tick: int
    demand_kw: float
    supplied_kw: float
    balance_kw: float
    at: datetime.datetime

    def __post_init__(self):
        _require_text(self.zone_id, 'zone_id must not be blank')
        _require_text(self.zone_name, f'zone {self.zone_id} must have a name')


@dataclasses.dataclass(frozen=True)
class ZoneCapacity:
    """A zone's assigned power-capacity ceiling.

    A billing input -- what overage is priced against -- not a hard delivery cap that
    the merge itself enforces; ``DistributionService`` allocates supply by demand share
    regardless of any capacity assigned here.
    """

    zone_id: str
    zone_name: str
    capacity_kw: float

    def __post_init__(self):
        _require_text(self.zone_id, 'zone_id must not be blank')
        _require_text(self.zone_name, f'zone {self.zone_id} must have a name')
        _require_positive_finite(self.capacity_kw, f'zone {self.zone_id} must have a positive, finite capacity_kw')
