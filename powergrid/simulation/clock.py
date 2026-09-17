"""The tick/time relationship for the whole simulation -- the one canonical copy.

Ported from Power-Grid's ``Grid.simulation.SimulationClock`` (Java). In the Java
system every service keeps its own numerically-identical copy of this file, because
each is an independently deployed process with no shared library between them. This
Django project is one process, so there is exactly one copy, here, and every app
(``producer``, ``customer``, ``distributor``, ``billing``, ...) imports it rather than
re-deriving it.

The contract:

    1 simulated day  = 288 ticks
    24h / 288         = 5 simulated minutes per tick
    1 real second     = 1 simulated minute
    => a tick every 5 real seconds, and a simulated day every 24 real minutes

TICKS_PER_DAY is not an arbitrary pace setting: the solar strategy divides the tick
number by it to get a position in the day, so it is what makes sunrise fall on tick 72
and sunset on tick 216.
"""

TICKS_PER_DAY = 288

SIMULATED_MINUTES_PER_TICK = (24 * 60) // TICKS_PER_DAY

REAL_TIME_PER_TICK_SECONDS = SIMULATED_MINUTES_PER_TICK


def time_of_day(tick: int) -> str:
    """Time of day the given tick represents, wrapping at midnight, as "HH:MM"."""
    minutes = (tick % TICKS_PER_DAY) * SIMULATED_MINUTES_PER_TICK
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def day_number(tick: int) -> int:
    """Simulated days elapsed; tick 0 through 287 are day 0."""
    return tick // TICKS_PER_DAY


def energy_mwh(output_mw: float) -> float:
    """Energy something produces/consumes in one tick: power held for one tick's
    simulated duration."""
    return output_mw * SIMULATED_MINUTES_PER_TICK / 60.0
