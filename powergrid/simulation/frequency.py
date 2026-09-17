"""Automatic frequency control (AGC) -- ported from Grid's ``FrequencyController``.

Real-AGC-inspired: deviation moves with the fleet's supply/demand imbalance, scaled
by a gain and clamped to a maximum swing.

This is a pure function, not wired into the tick loop yet -- it needs a fleet-wide
supply and demand figure, which nothing in this project reports yet (that arrives once
``producer``/``distributor`` exist and can call this after summing their own state).
Until then, :class:`~simulation.models.SimulationState`'s ``frequency_deviation_hz``
is only ever moved by a manual override.
"""

GAIN_HZ = 2.0
MAX_DEVIATION_HZ = 0.25


def compute_deviation(supply_kw: float, demand_kw: float) -> float:
    """deviation = clamp((supply - demand) / demand * gain, +/- max_deviation)."""
    if demand_kw == 0:
        return 0.0
    deviation = (supply_kw - demand_kw) / demand_kw * GAIN_HZ
    return min(max(deviation, -MAX_DEVIATION_HZ), MAX_DEVIATION_HZ)
