"""Messaging adapters for the grid app: react to Producer's output and Distributor's
zone balance as they arrive, feeding ``GridStateTracker``.

The tick heartbeat itself is already published: ``simulation.signals.tick_advanced``,
fired every ``simulation.clock.REAL_TIME_PER_TICK_SECONDS`` (5) real seconds by the
``runsimulation`` command, is this project's in-process stand-in for that broadcast,
and Producer and Customer already react to it directly. There is nothing left for
this module to publish -- it only consumes.

Both reactions are in-process Django signals, since the project has no message
broker -- the same shape ``distributor.kafka`` already uses. Consuming producer
output and zone balance is duck-typed on purpose: the listeners below read the
incoming signal only through ``events.ProducerOutputEvent.from_signal``/
``events.ZoneBalanceEvent.from_signal``, which pick out just the documented attribute
names their upstream signals are known to carry, never importing producer's or
distributor's own event classes -- see ``distributor.kafka`` for the same reasoning.

Nothing here connects itself; a future composition root wires the listeners once this
app has somewhere to hand its tracker, and importing this module has no side effects.
"""
import logging

from distributor.kafka import balance_published
from producer.kafka import output_published

from .events import ProducerOutputEvent, ZoneBalanceEvent
from .state import GridStateTracker

logger = logging.getLogger(__name__)

_PRODUCER_OUTPUT_UID = 'grid.on_producer_output'
_ZONE_BALANCE_UID = 'grid.on_zone_balance'


class ProducerOutputListener:
    """Tracks Producer's fleet output as it streams in.

    A failure is logged and swallowed rather than raised: letting an exception escape
    a signal receiver stops every receiver after it for that dispatch, silently
    freezing this plant's contribution to every future status read.
    """

    def __init__(self, tracker: GridStateTracker):
        self._tracker = tracker

    def on_output_published(self, sender, event, **kwargs):
        try:
            output = ProducerOutputEvent.from_signal(event)
            self._tracker.record_supply(output.producer_id, output.output_mw)
        except Exception:
            logger.exception('Failed to record output for plant %s', getattr(event, 'producer_id', '?'))


class ZoneBalanceListener:
    """Tracks each zone's latest demand off Distributor's merged balance -- Grid reads
    ``demand_kw`` off this event rather than Customer's raw demand directly, since
    Grid's status is a view downstream of the merge, not a second copy of it.

    A failure is logged and swallowed for the same reason ``ProducerOutputListener``
    documents.
    """

    def __init__(self, tracker: GridStateTracker):
        self._tracker = tracker

    def on_balance_published(self, sender, event, **kwargs):
        try:
            balance = ZoneBalanceEvent.from_signal(event)
            self._tracker.record_demand(balance.zone_id, balance.demand_kw)
        except Exception:
            logger.exception('Failed to record demand for zone %s', getattr(event, 'zone_id', '?'))


def connect_listeners(tracker: GridStateTracker) -> tuple[ProducerOutputListener, ZoneBalanceListener]:
    """Starts driving ``tracker`` from producer output and distributor zone balance.

    Replaces any listeners connected earlier rather than stacking a second pair, which
    would run every reading twice (and a same-id reconnect would otherwise be silently
    ignored, keeping the old tracker).
    """
    producer_listener = ProducerOutputListener(tracker)
    balance_listener = ZoneBalanceListener(tracker)

    output_published.disconnect(dispatch_uid=_PRODUCER_OUTPUT_UID)
    output_published.connect(producer_listener.on_output_published, weak=False, dispatch_uid=_PRODUCER_OUTPUT_UID)

    balance_published.disconnect(dispatch_uid=_ZONE_BALANCE_UID)
    balance_published.connect(balance_listener.on_balance_published, weak=False, dispatch_uid=_ZONE_BALANCE_UID)

    return producer_listener, balance_listener


def disconnect_listeners() -> tuple[bool, bool]:
    """Stops reacting to producer output and zone balance. Each element is False if
    that listener was not connected."""
    return (
        output_published.disconnect(dispatch_uid=_PRODUCER_OUTPUT_UID),
        balance_published.disconnect(dispatch_uid=_ZONE_BALANCE_UID),
    )
