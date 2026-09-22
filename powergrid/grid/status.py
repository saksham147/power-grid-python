"""Reads and steers the shared clock.

Deliberately not framework-free the way ``billing.py``/``distribution.py`` are:
there is only one concrete source for the clock --
``simulation.models.SimulationState``, the project's single canonical clock owner
(see its own docstring: every app reads it instead of keeping its own counter) --
and only one concrete ``GridStateTracker``, so a port abstraction here would have
nothing else to ever stand behind it.

There is no start or stop here, and no tick-advance either: the loop that owns both
already lives in ``simulation`` (``runsimulation`` / ``services.advance_tick``). What
this module adds is Grid's own view combining that clock with ``GridStateTracker``,
and the one thing Grid alone is allowed to change about it -- frequency deviation.
"""
import dataclasses

from simulation.clock import REAL_TIME_PER_TICK_SECONDS
from simulation.models import SimulationState

from .events import GridTickEvent
from .state import GridStateTracker


@dataclasses.dataclass(frozen=True)
class GridStatus:
    """Point-in-time view of the clock, joined against Grid's own tracked totals."""

    tick_number: int
    simulated_time: str
    simulated_day: int
    tick_interval_seconds: int
    frequency_deviation_hz: float
    auto_control_enabled: bool
    total_supply_kw: float
    total_demand_kw: float
    load_exceeded: bool


def snapshot(tracker: GridStateTracker) -> GridStatus:
    state = SimulationState.load()
    tick = GridTickEvent.from_state(state)
    supply_kw = tracker.total_supply_kw()
    demand_kw = tracker.total_demand_kw()
    return GridStatus(
        tick_number=tick.tick_number,
        simulated_time=tick.simulated_time,
        simulated_day=tick.simulated_day,
        tick_interval_seconds=REAL_TIME_PER_TICK_SECONDS,
        frequency_deviation_hz=tick.frequency_deviation_hz,
        auto_control_enabled=state.auto_control,
        total_supply_kw=supply_kw,
        total_demand_kw=demand_kw,
        load_exceeded=demand_kw > supply_kw,
    )


def set_frequency_deviation(tracker: GridStateTracker, deviation_hz: float) -> GridStatus:
    """Manually sets the deviation every subsequent tick carries, and switches
    automatic control off so this value sticks rather than being silently overwritten
    -- the bound (a quarter of a hertz either way) is already enforced by the caller's
    request parsing, not re-checked here, the same division of labour
    ``distributor.distribution.ZoneCapacityService.upsert`` has with its own dto.
    """
    state = SimulationState.load()
    state.frequency_deviation_hz = deviation_hz
    state.auto_control = False
    state.save()

    return snapshot(tracker)
