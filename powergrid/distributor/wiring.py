"""Composition root for the distributor app: the concrete adapters behind
``distribution.py``'s ports.

``GridStateTracker`` is genuinely process-wide in-memory state -- there is exactly one,
built lazily on first use, so the messaging listeners (once connected, see ``connect``
below) and every HTTP view read and write the very same tracked totals rather than each
starting from an empty tracker of its own.
"""
import functools

from .distribution import DistributionService, GridStateTracker, ZoneCapacityService
from .kafka import SignalBalancePublisher, SignalZoneCapacityPublisher
from .kafka import connect_listeners as _connect_listeners
from .orm import DjangoDistributionLogger, DjangoZoneCapacityRepository


@functools.cache
def state_tracker() -> GridStateTracker:
    return GridStateTracker()


@functools.cache
def distribution_service() -> DistributionService:
    return DistributionService(state_tracker(), DjangoDistributionLogger(), SignalBalancePublisher())


@functools.cache
def zone_capacity_service() -> ZoneCapacityService:
    return ZoneCapacityService(DjangoZoneCapacityRepository(), SignalZoneCapacityPublisher())


def connect() -> None:
    """Starts driving ``distribution_service()`` from producer output and zone demand.

    Not called automatically anywhere in this project yet -- see
    ``distributor.kafka.connect_listeners`` for why every app here leaves that to an
    explicit call rather than a side effect of import.
    """
    _connect_listeners(distribution_service())
