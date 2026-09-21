"""Composition root for the customer app: the concrete adapters behind its ports.

The use case and the HTTP API are written against the ports in ``customer.application``.
This is the one place that knows which adapters implement them, so changing where zones,
units and demand are stored means changing this file and nothing else.

The Redis client is built lazily, on first use, so importing the app (management commands,
migrations, tests) never requires Redis to be reachable. Connecting the clock listener
that drives demand ticks is a separate step and is not done here.
"""
import functools

from .application import ConsumerUnitRepository, DemandStateStore, ZoneRepository
from .infrastructure.redis import (
    RedisConsumerUnitRepository, RedisDemandStateStore, RedisZoneRepository, connect,
)


@functools.cache
def _client():
    return connect()


def zones() -> ZoneRepository:
    return RedisZoneRepository(_client())


def units() -> ConsumerUnitRepository:
    return RedisConsumerUnitRepository(_client())


def demand_state() -> DemandStateStore:
    return RedisDemandStateStore(_client())
