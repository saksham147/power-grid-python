"""Framework-free demand domain: zones, consumer units, and how their demand varies
over the day, the week and the year.


"""
import dataclasses
import enum
import math

_HOURS = 24

# Simulated days in one season; 4 seasons make an 88-day simulated year. Matches
# producer.generation's own season length so both sides of the grid change season
# together.
_DAYS_PER_SEASON = 22


def _require_text(value, message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)


@dataclasses.dataclass(frozen=True)
class Zone:
    """A named grouping of ConsumerUnits -- a neighbourhood, a district, whatever the
    installation wants to call a cluster of houses, factories and commercial buildings
    that share a distribution point.

    A zone carries no demand of its own: it is a pure container. Its demand is the sum
    of its units' (see ``demand_kw``), so a zone with no units yet reports zero, not an
    error.
    """

    zone_id: str
    name: str

    def __post_init__(self):
        _require_text(self.zone_id, 'zone_id must not be blank')
        _require_text(self.name, f'zone {self.zone_id} must have a name')


class DemandProfile(enum.Enum):
    """How one customer's demand varies over the day and the week.

    Each profile is a 24-point hourly shape, interpolated between hours so demand moves
    smoothly rather than stepping on the hour. A published load profile is exactly this
    shape of data, so the numbers stay readable and adjustable instead of being buried
    in fitted sinusoids. The values are ``(hourly, weekend_factor)``.
    """

    # Medium through the working day, high at night. Appliances -- laundry, dishwashers,
    # EV charging, AC and heating held on a thermostat rather than a schedule -- keep
    # the evening and night hours the highest part of the curve, not just a peak that
    # immediately falls away.
    RESIDENTIAL = (
        (0.70, 0.62, 0.55, 0.52, 0.55, 0.65, 0.85, 1.00,
         0.95, 0.85, 0.80, 0.80, 0.82, 0.80, 0.78, 0.80,
         0.90, 1.15, 1.50, 1.65, 1.60, 1.40, 1.10, 0.85),
        # People are home all day at weekends, so the whole curve lifts substantially
        # rather than just the evening peak: weekends read "high", not "weekday plus a bit".
        1.30,
    )

    # Near-nothing overnight, ramps at opening, plateaus through business hours.
    COMMERCIAL = (
        (0.25, 0.22, 0.20, 0.20, 0.22, 0.30, 0.50, 0.85,
         1.25, 1.45, 1.50, 1.50, 1.45, 1.50, 1.50, 1.45,
         1.35, 1.10, 0.80, 0.60, 0.45, 0.35, 0.30, 0.27),
        # Mostly closed.
        0.35,
    )

    # Continuous process load: nearly flat, with a mild day-shift lift.
    INDUSTRIAL = (
        (0.92, 0.90, 0.90, 0.90, 0.92, 0.95, 1.00, 1.05,
         1.08, 1.10, 1.10, 1.08, 1.05, 1.08, 1.10, 1.10,
         1.08, 1.05, 1.00, 0.98, 0.96, 0.95, 0.94, 0.93),
        # Reduced shifts, not a shutdown.
        0.80,
    )

    # Government and public-sector buildings: near-nothing overnight bar security and
    # emergency lighting, a sharp ramp at opening, a flat office-hours plateau, then a
    # sharp drop -- closer to COMMERCIAL's shape than RESIDENTIAL's, but steadier through
    # the day and with almost no weekend activity, since a government office is not a shop.
    GOV = (
        (0.18, 0.16, 0.15, 0.15, 0.16, 0.20, 0.30, 0.55,
         0.85, 1.05, 1.10, 1.10, 1.05, 1.10, 1.10, 1.08,
         1.00, 0.70, 0.40, 0.30, 0.25, 0.22, 0.20, 0.19),
        # Essential services only; almost fully closed.
        0.20,
    )

    def __init__(self, hourly, weekend_factor):
        if len(hourly) != _HOURS:
            raise ValueError(f'{self.name}: expected {_HOURS} hourly points, got {len(hourly)}')
        self.hourly = hourly
        self.weekend_factor = weekend_factor

    def factor_at(self, minute_of_day: int, is_weekend: bool) -> float:
        """Multiplier on a unit's rated demand at this moment -- a positive factor,
        typically between 0.1 and 1.7.

        Interpolates from this hour's point into the next, wrapping 23 -> 0 so midnight
        is continuous.
        """
        hour = (minute_of_day // 60) % _HOURS
        within_hour = (minute_of_day % 60) / 60.0

        from_value = self.hourly[hour]
        to_value = self.hourly[(hour + 1) % _HOURS]
        shape = from_value + (to_value - from_value) * within_hour

        return shape * (self.weekend_factor if is_weekend else 1.0)


@dataclasses.dataclass(frozen=True)
class ConsumerUnit:
    """A single house, factory or commercial building -- the atomic demand-generating
    entity in this service, and the child of exactly one Zone.

    Each unit is significant on its own, the way a ``producer.PowerPlant`` is: a rated
    capacity, a type that selects how that capacity behaves, and a closed-form formula
    (``demand_kw``) instead of population statistics.

    ``capacity_kw`` is the unit's rated demand, in kW, at a profile factor of 1.0.
    """

    unit_id: str
    zone_id: str
    name: str
    type: DemandProfile
    capacity_kw: float

    def __post_init__(self):
        _require_text(self.unit_id, 'unit_id must not be blank')
        _require_text(self.zone_id, f'unit {self.unit_id} must belong to a zone')
        _require_text(self.name, f'unit {self.unit_id} must have a name')
        if not isinstance(self.type, DemandProfile):
            raise ValueError(f'unit {self.unit_id} must have a type')
        # Finite as well as positive: NaN compares false against everything, so it would
        # sail through a bare "<= 0" check and poison every sum it joined.
        if (isinstance(self.capacity_kw, bool) or not isinstance(self.capacity_kw, (int, float))
                or not math.isfinite(self.capacity_kw) or self.capacity_kw <= 0):
            raise ValueError(f'unit {self.unit_id} must have a positive, finite capacity_kw')


class Season(enum.Enum):
    """The simulated year's season, on the demand side -- a structural sibling to
    ``producer.generation.Season``, not a shared class: the two are deliberately
    independent, each owning its own multipliers.

    Demand rises in both summer (cooling load) and winter (heating load) relative to
    spring and autumn -- the same real-world "shoulder season" shape utilities actually
    see, complementary to (not copied from) the renewable-output curve's own seasonal
    swing. Keyed on a day number rather than a tick, so it stays independent of the
    clock: the clock already turns a tick into a day.
    """

    SPRING = 1.00
    SUMMER = 1.20
    AUTUMN = 0.95
    WINTER = 1.15

    def __init__(self, demand_factor):
        self.demand_factor = demand_factor

    @classmethod
    def of(cls, day_number: int) -> 'Season':
        members = list(cls)
        return members[(day_number // _DAYS_PER_SEASON) % len(members)]


def demand_kw(unit: ConsumerUnit, minute_of_day: int, is_weekend: bool,
              season: Season = Season.SPRING) -> float:
    """One unit's demand for one tick, in kW, never negative.

    ``capacity x type x season``: the unit's rated capacity scaled by its type's demand
    shape at this time of day and week, then by the season's demand factor. Season is
    its own multiplicative term rather than folded into ``DemandProfile``'s hourly
    shape -- "what kind of building this is" and "what time of year it is" are
    orthogonal, and merging them would give every profile a second, unrelated axis of
    variation.

    Deterministic on purpose: the same unit and the same moment always give the same
    figure, matching every other simulated quantity in this project. (Ported from
    ``DemandModel.demandKw``; with no anonymous population to collapse into a single
    statistical draw, there is nothing left for randomness to earn its place.)
    """
    return max(0.0, unit.capacity_kw * unit.type.factor_at(minute_of_day, is_weekend) * season.demand_factor)


@dataclasses.dataclass(frozen=True)
class ZoneDemand:
    """One zone's aggregated demand for one tick -- the sum of its units' own demand.

    Tick and simulated time are deliberately absent: they are the same for every zone in
    a tick, so they belong to the tick (``DemandSnapshot``), not repeated on each zone.
    """

    zone_id: str
    name: str
    unit_count: int
    demand_kw: float
