"""Messaging adapters for the distributor app: react to producer output and zone
demand as they arrive, and publish merged balances and capacity changes.

Both directions are in-process Django signals, since the project has no message
broker -- the same shape ``producer.kafka`` and ``customer.infrastructure.kafka``
already use. ``distribution.py`` knows none of this: it depends only on the
``BalancePublisher``/``ZoneCapacityPublisher`` ports, which is what keeps the merge and
capacity-admin logic testable with fakes and no signal machinery in the picture.

Consuming producer output and zone demand is duck-typed on purpose: the listeners
below read only the attributes their upstream signals are documented to carry (see
``events.py``), never importing producer's or customer's own event classes. That is
the in-process equivalent of two independently deployed services agreeing on a JSON
shape without sharing a class file.

Nothing here connects itself; a future composition root wires the listeners once this
app has concrete adapters to hand them (mirroring how ``customer.infrastructure.kafka.
connect_grid_tick_listener`` is also left for its own composition root), and importing
this module has no side effects.
"""
import datetime
import logging

import django.dispatch

from customer.infrastructure.kafka import demand_published
from producer.kafka import output_published

from .distribution import BalancePublisher, DistributionService, ZoneCapacityPublisher
from .domain import ZoneDistribution
from .events import ZoneBalanceEvent, ZoneCapacityEvent

logger = logging.getLogger(__name__)

ZONE_BALANCE_TOPIC = 'distributor.zone-balance'
ZONE_CAPACITY_TOPIC = 'distributor.zone-capacity'

balance_published = django.dispatch.Signal()
capacity_published = django.dispatch.Signal()

_PRODUCER_OUTPUT_UID = 'distributor.on_producer_output'
_ZONE_DEMAND_UID = 'distributor.on_zone_demand'


class SignalBalancePublisher(BalancePublisher):
    """Publishes one ``ZoneBalanceEvent`` per merged balance.

    One publish per incoming demand reading, not a per-tick fan-out over every zone the
    way Customer's publisher is, so there is no publish budget needed here: a single
    failing subscriber costs one event, not a whole tick's worth. ``send_robust``
    isolates subscribers from each other the same way ``producer.kafka.publish`` does.
    """

    def publish(self, distribution: ZoneDistribution) -> None:
        event = ZoneBalanceEvent.of(distribution)
        for subscriber, response in balance_published.send_robust(sender=None, event=event):
            if isinstance(response, Exception):
                logger.error('%s failed for zone %s (tick %s): %r',
                             ZONE_BALANCE_TOPIC, event.zone_id, event.tick, response)


class SignalZoneCapacityPublisher(ZoneCapacityPublisher):
    """Publishes a zone's capacity configuration.

    Capacities change rarely -- an admin edit, not a per-tick event -- so unlike the
    balance publisher there is no publish-volume concern here either.
    """

    def publish(self, zone_id: str, zone_name: str, capacity_kw: float | None,
                at: datetime.datetime) -> None:
        event = ZoneCapacityEvent(zone_id, zone_name, capacity_kw, at)
        for subscriber, response in capacity_published.send_robust(sender=None, event=event):
            if isinstance(response, Exception):
                logger.error('%s failed for zone %s: %r', ZONE_CAPACITY_TOPIC, event.zone_id, response)


class ProducerOutputListener:
    """Tracks Producer's fleet output as it streams in.

    A failure is logged and swallowed rather than raised: letting an exception escape a
    signal receiver stops every receiver after it for that dispatch, silently freezing
    this plant's contribution to every future balance.
    """

    def __init__(self, service: DistributionService):
        self._service = service

    def on_output_published(self, sender, event, **kwargs):
        try:
            self._service.on_producer_output(event.producer_id, event.output_mw)
        except Exception:
            logger.exception('Failed to record output for plant %s (tick %s)',
                             getattr(event, 'producer_id', '?'), getattr(event, 'tick_number', '?'))


class ZoneDemandListener:
    """Reacts to each zone's demand by merging it against the tracked fleet supply --
    see ``DistributionService`` for why demand, not the shared clock's tick, is what
    drives the merge.

    A failure is logged and swallowed for the same reason as ``ProducerOutputListener``:
    an escaping exception would stop every receiver after it, including any other app
    reacting to the same demand reading.
    """

    def __init__(self, service: DistributionService):
        self._service = service

    def on_demand_published(self, sender, event, **kwargs):
        try:
            self._service.on_zone_demand(event.zone_id, event.zone_name, event.tick, event.demand_kw, event.timestamp)
        except Exception:
            logger.exception('Failed to balance zone %s (tick %s)',
                             getattr(event, 'zone_id', '?'), getattr(event, 'tick', '?'))


def connect_listeners(service: DistributionService) -> tuple[ProducerOutputListener, ZoneDemandListener]:
    """Starts driving ``service`` from producer output and zone demand.

    Replaces any listeners connected earlier rather than stacking a second pair, which
    would run every reading twice (and a same-id reconnect would otherwise be silently
    ignored, keeping the old service).
    """
    producer_listener = ProducerOutputListener(service)
    demand_listener = ZoneDemandListener(service)

    output_published.disconnect(dispatch_uid=_PRODUCER_OUTPUT_UID)
    output_published.connect(producer_listener.on_output_published, weak=False, dispatch_uid=_PRODUCER_OUTPUT_UID)

    demand_published.disconnect(dispatch_uid=_ZONE_DEMAND_UID)
    demand_published.connect(demand_listener.on_demand_published, weak=False, dispatch_uid=_ZONE_DEMAND_UID)

    return producer_listener, demand_listener


def disconnect_listeners() -> tuple[bool, bool]:
    """Stops reacting to producer output and zone demand. Each element is False if
    that listener was not connected."""
    return (
        output_published.disconnect(dispatch_uid=_PRODUCER_OUTPUT_UID),
        demand_published.disconnect(dispatch_uid=_ZONE_DEMAND_UID),
    )
