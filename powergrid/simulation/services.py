"""The tick-advance use case -- the one place that mutates SimulationState."""
from .models import SimulationState


def advance_tick() -> SimulationState:
    """Moves the shared clock forward by one tick and persists it.

    Frequency deviation is left untouched here: with auto_control on, it is expected
    to be recomputed by whichever app aggregates fleet supply/demand (see
    ``simulation.frequency.compute_deviation``) and written back through
    SimulationState; with auto_control off, it stays at whatever a manual override
    last set it to.
    """
    state = SimulationState.load()
    state.current_tick += 1
    state.save()
    return state
