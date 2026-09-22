"""Wire-shaped payloads Grid produces and consumes.

Grid never imports producer's or distributor's own event classes -- ``ProducerOutputEvent``
and ``ZoneBalanceEvent`` below are Grid's own copies of the shape those signals are
documented to carry (a subset of the real, owning definitions in
``producer.events``/``distributor.events``), built once at the point each listener in
``grid.kafka`` receives an event. That is the same "structural, not compiled, contract"
every ``kafka.py`` in this project already documents -- see ``grid.kafka`` for where
these are actually constructed and used.

Grid does not publish an event of its own over a signal: the tick heartbeat is
``simulation.signals.tick_advanced``, whose payload (``tick_number``,
``frequency_deviation``) is sent as plain signal keywords rather than wrapped in a
class. ``GridTickEvent`` is Grid's own typed record of that same shape, assembled from
``SimulationState``/the shared clock rather than received over a signal, and used by
``grid.status.snapshot`` so that assembly is written once, not repeated inline.
"""
import dataclasses

from simulation.clock import day_number, time_of_day
from simulation.models import SimulationState


@dataclasses.dataclass(frozen=True)
class GridTickEvent:
    """The tick heartbeat: what tick just happened, and the frequency deviation it
    carries."""

    tick_number: int
    frequency_deviation_hz: float
    simulated_time: str
    simulated_day: int

    @classmethod
    def from_state(cls, state: SimulationState) -> 'GridTickEvent':
        return cls(
            tick_number=state.current_tick,
            frequency_deviation_hz=state.frequency_deviation_hz,
            simulated_time=time_of_day(state.current_tick),
            simulated_day=day_number(state.current_tick),
        )


@dataclasses.dataclass(frozen=True)
class ProducerOutputEvent:
    """One plant's contribution for one tick -- only the fields
    ``grid.state.GridStateTracker.record_supply`` needs. See
    ``producer.events.ProducerOutputEvent`` for the real, owning definition."""

    producer_id: int
    output_mw: float

    @classmethod
    def from_signal(cls, event) -> 'ProducerOutputEvent':
        return cls(producer_id=event.producer_id, output_mw=event.output_mw)


@dataclasses.dataclass(frozen=True)
class ZoneBalanceEvent:
    """One zone's merged balance for one tick -- only the fields
    ``grid.state.GridStateTracker.record_demand`` needs. ``demand_kw`` only: Grid's
    status is downstream of the merge, not a second copy of it. See
    ``distributor.events.ZoneBalanceEvent`` for the real, owning definition."""

    zone_id: str
    demand_kw: float

    @classmethod
    def from_signal(cls, event) -> 'ZoneBalanceEvent':
        return cls(zone_id=event.zone_id, demand_kw=event.demand_kw)
