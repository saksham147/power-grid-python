"""Messaging adapters for the customer app: react to the shared clock's tick, and
publish each zone's demand.

Both directions are in-process signals, since the project has no message broker, so a
broker-backed adapter can replace this module later without touching the use case
(``customer.application`` only knows the ``DemandPublisher`` port and
``DemandSimulator.tick``).

Nothing here connects itself and importing it has no side effects. Building a
``DemandSimulator`` needs the zone and unit repositories and a state store, so whichever
composition root supplies those calls ``connect_grid_tick_listener(simulator)``.

Signal receivers run synchronously on the clock's thread, one after another, so a
subscriber to ``demand_published`` should be quick; ``SignalDemandPublisher`` bounds what
a slow one can cost.
"""
import dataclasses
import datetime
import logging
import time
from typing import Callable

import django.dispatch

from simulation.signals import tick_advanced

from ..application import DemandPublisher, DemandSimulator, DemandSnapshot
from ..domain import ZoneDemand

logger = logging.getLogger(__name__)

TOPIC = 'customer.demand'

demand_published = django.dispatch.Signal()

# How long one tick may spend publishing before it gives up on the remaining zones.
# Comfortably inside a tick, and never reached while subscribers are quick.
PUBLISH_BUDGET_SECONDS = 1.0

_LISTENER_UID = 'customer.grid_tick_listener'


@dataclasses.dataclass(frozen=True)
class ZoneDemandEvent:
    """A zone's aggregated demand for one tick, as published to ``customer.demand``.

    Only zone-level aggregates leave the customer app; no individual consumer unit is
    ever represented. Separate from the domain's ``ZoneDemand`` on purpose: this is the
    contract subscribers depend on, so it carries the tick context each record needs to
    stand alone, and it can evolve for them without dragging the domain along.

    ``zone_id`` is the key: one zone's events are published in tick order. ``timestamp``
    is the wall-clock instant of the tick, shared by all of its events.
    """

    zone_id: str
    zone_name: str
    tick: int
    simulated_time: str
    unit_count: int
    demand_kw: float
    timestamp: datetime.datetime

    @classmethod
    def of(cls, snapshot: DemandSnapshot, zone: ZoneDemand) -> 'ZoneDemandEvent':
        return cls(
            zone_id=zone.zone_id,
            zone_name=zone.name,
            tick=snapshot.tick,
            simulated_time=snapshot.simulated_time,
            unit_count=zone.unit_count,
            demand_kw=zone.demand_kw,
            timestamp=snapshot.at,
        )


class SignalDemandPublisher(DemandPublisher):
    """Publishes one ``ZoneDemandEvent`` per zone, per tick, on ``demand_published``.

    Honours the ``DemandPublisher`` contract -- never raises, never blocks -- in two ways:

    * ``send_robust`` isolates subscribers: one that raises is logged and skipped, and
      neither the other subscribers nor the tick's remaining zones are affected.
    * The tick works to a publish budget. A subscriber that is slow (rather than broken)
      would otherwise stall the whole simulation, and the budget is per tick, not per
      event: a slow subscriber times N zones would overrun the tick itself. Once it is
      spent the rest of the tick's zones are abandoned. Old demand is not worth
      delivering late -- by then a fresher figure has replaced it.

    Failures are counted (``failure_count``) and logged, never raised.
    """

    def __init__(self, budget_seconds: float = PUBLISH_BUDGET_SECONDS,
                 monotonic: Callable[[], float] = time.monotonic):
        if budget_seconds <= 0:
            raise ValueError('budget_seconds must be positive')
        self._budget_seconds = budget_seconds
        self._monotonic = monotonic
        self._failures = 0

    @property
    def failure_count(self) -> int:
        """Failed deliveries since this publisher was created."""
        return self._failures

    def publish(self, snapshot: DemandSnapshot) -> None:
        deadline = self._monotonic() + self._budget_seconds

        for index, zone in enumerate(snapshot.zones):
            if self._monotonic() > deadline:
                abandoned = len(snapshot.zones) - index
                self._record_failure(
                    zone.zone_id, snapshot.tick,
                    RuntimeError(f'publish budget spent; {abandoned} of {len(snapshot.zones)} '
                                 f'zones abandoned on tick {snapshot.tick}'))
                return

            event = ZoneDemandEvent.of(snapshot, zone)
            for subscriber, response in demand_published.send_robust(sender=None, event=event):
                if isinstance(response, Exception):
                    self._record_failure(event.zone_id, event.tick, response, subscriber)

    def _record_failure(self, zone_id: str, tick: int, error: Exception, subscriber=None) -> None:
        self._failures += 1
        # For a failing subscriber Django logs the traceback itself; this line adds
        # which zone and tick it was.
        logger.error('%s failed for zone %s on tick %s (%d failures so far); the simulation continues: %r',
                     TOPIC, zone_id, tick, self._failures, error)


class GridTickListener:
    """Reacts to the shared clock's tick by running one demand tick.

    This app runs no scheduler of its own: the clock owns simulated time and every app
    reacts to it. The tick's frequency deviation arrives on the same signal but is unused
    here; only thermal generation responds to it.

    A failure is logged and swallowed rather than raised. The clock fires
    ``tick_advanced`` with a plain ``send``, so an exception escaping a receiver would
    stop the clock loop and skip every receiver after this one; a dropped tick is
    recovered on the next one.
    """

    def __init__(self, simulator: DemandSimulator):
        self._simulator = simulator

    def on_tick_advanced(self, sender, tick_number, frequency_deviation, **kwargs):
        try:
            self._simulator.tick(tick_number)
        except Exception:
            logger.exception('Tick %s failed; the simulation continues', tick_number)


def connect_grid_tick_listener(simulator: DemandSimulator) -> GridTickListener:
    """Starts driving ``simulator`` from the shared clock.

    Replaces any listener connected earlier rather than stacking a second one, which
    would run every tick twice (and Django would ignore a same-id reconnect, silently
    keeping the old simulator).
    """
    listener = GridTickListener(simulator)
    tick_advanced.disconnect(dispatch_uid=_LISTENER_UID)
    tick_advanced.connect(listener.on_tick_advanced, weak=False, dispatch_uid=_LISTENER_UID)
    return listener


def disconnect_grid_tick_listener() -> bool:
    """Stops reacting to the clock. False if nothing was connected."""
    return tick_advanced.disconnect(dispatch_uid=_LISTENER_UID)
