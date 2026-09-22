"""Messaging adapters for the billing app: react to zone demand and to Distributor's
zone-capacity broadcasts as they arrive.

Both are in-process Django signals, since the project has no message broker -- the
same shape ``distributor.kafka`` already uses. ``billing.py`` knows none of this: the
demand listener depends only on ``BillingCycleService``, and the capacity listener
only on ``ZoneCapacityCache``, which is what keeps billing and pricing logic testable
with fakes and no signal machinery in the picture. Billing has nothing of its own to
publish here: it only consumes.

Consuming zone demand and zone-capacity changes is duck-typed on purpose: the
listeners below read only the attribute names their upstream signals are documented
to carry (``zone_id``/``zone_name``/``tick``/``demand_kw``/``timestamp``;
``zone_id``/``capacity_kw``), never importing customer's or distributor's own event
classes. That is the in-process equivalent of two independently deployed services
agreeing on a JSON shape without sharing a class file -- see ``distributor.kafka`` for
the same reasoning.

Nothing here connects itself; a future composition root wires the listeners once this
app has concrete adapters to hand them (mirroring how ``distributor.kafka.
connect_listeners`` is also left for its own composition root), and importing this
module has no side effects.
"""
import logging

from customer.infrastructure.kafka import demand_published
from distributor.kafka import capacity_published

from .billing import BillingCycleService, ZoneCapacityCache

logger = logging.getLogger(__name__)

_ZONE_DEMAND_UID = 'billing.on_zone_demand'
_ZONE_CAPACITY_UID = 'billing.on_zone_capacity_changed'


class ZoneDemandBillingListener:
    """Reacts to each zone's tick-end demand by billing it -- see
    ``billing.BillingCycleService`` for why this, not a separate clock, drives billing
    cycles.

    A failure is logged and swallowed rather than raised: letting an exception escape
    a signal receiver stops every receiver after it for that dispatch, silently
    freezing every zone after this one from ever being billed again.
    """

    def __init__(self, cycle_service: BillingCycleService):
        self._cycle_service = cycle_service

    def on_demand_published(self, sender, event, **kwargs):
        try:
            self._cycle_service.on_zone_demand(
                event.zone_id, event.zone_name, event.tick, event.demand_kw, event.timestamp)
        except Exception:
            logger.exception('Failed to bill zone %s (tick %s)',
                             getattr(event, 'zone_id', '?'), getattr(event, 'tick', '?'))


class ZoneCapacityMirrorListener:
    """Keeps ``ZoneCapacityCache`` in step with Distributor's zone-capacity
    configuration -- a config mirror, not a billing action, so unlike
    ``ZoneDemandBillingListener`` there is nothing here that needs idempotency:
    replaying the same capacity change twice just overwrites the cache with the same
    value.

    A failure is logged and swallowed for the same reason
    ``ZoneDemandBillingListener`` documents.
    """

    def __init__(self, capacities: ZoneCapacityCache):
        self._capacities = capacities

    def on_capacity_published(self, sender, event, **kwargs):
        try:
            self._capacities.set(event.zone_id, event.capacity_kw)
        except Exception:
            logger.exception('Failed to apply capacity change for zone %s', getattr(event, 'zone_id', '?'))


def connect_listeners(
    cycle_service: BillingCycleService, capacities: ZoneCapacityCache,
) -> tuple[ZoneDemandBillingListener, ZoneCapacityMirrorListener]:
    """Starts driving ``cycle_service`` from zone demand and ``capacities`` from
    Distributor's zone-capacity broadcasts.

    Replaces any listeners connected earlier rather than stacking a second pair, which
    would run every reading twice (and a same-id reconnect would otherwise be silently
    ignored, keeping the old listener).
    """
    demand_listener = ZoneDemandBillingListener(cycle_service)
    capacity_listener = ZoneCapacityMirrorListener(capacities)

    demand_published.disconnect(dispatch_uid=_ZONE_DEMAND_UID)
    demand_published.connect(demand_listener.on_demand_published, weak=False, dispatch_uid=_ZONE_DEMAND_UID)

    capacity_published.disconnect(dispatch_uid=_ZONE_CAPACITY_UID)
    capacity_published.connect(capacity_listener.on_capacity_published, weak=False, dispatch_uid=_ZONE_CAPACITY_UID)

    return demand_listener, capacity_listener


def disconnect_listeners() -> tuple[bool, bool]:
    """Stops reacting to zone demand and zone-capacity changes. Each element is False
    if that listener was not connected."""
    return (
        demand_published.disconnect(dispatch_uid=_ZONE_DEMAND_UID),
        capacity_published.disconnect(dispatch_uid=_ZONE_CAPACITY_UID),
    )
