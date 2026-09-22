"""Composition root for the billing app: the concrete adapters behind ``billing.py``'s
ports, and the numbers every deployment agrees on until this project grows real
per-environment configuration.

``ZoneCapacityCache`` is genuinely process-wide in-memory state -- there is exactly
one, built lazily on first use, so the messaging listener (once connected, see
``connect`` below) and every HTTP view read the very same mirrored capacities rather
than each starting from an empty cache of its own.
"""
import functools

from .billing import BillingCycleService, UnlockService, WalletSpendingService, ZoneCapacityCache
from .kafka import connect_listeners as _connect_listeners
from .orm import (
    DjangoBillingHistoryReader, DjangoBillingLedger, DjangoWalletRepository, DjangoWalletTransactionRepository,
)

# Flat rate for every zone, in rupees per kWh.
RATE_PER_KWH = 1.0

# Demand above a zone's Distributor-assigned capacity is still billed, never refused,
# but at this multiple of RATE_PER_KWH. A zone with no capacity assigned is unaffected.
OVERAGE_RATE_MULTIPLIER = 1.5

# Applied once, the first time a wallet -- a zone's, or the shared Grid wallet -- is
# lazily created.
STARTING_BALANCE = 10_000.0

# Fraction of a fresh-build price refunded when a plant is decommissioned.
DECOMMISSION_REFUND_RATIO = 0.5


@functools.cache
def zone_capacity_cache() -> ZoneCapacityCache:
    return ZoneCapacityCache()


@functools.cache
def wallet_repository() -> DjangoWalletRepository:
    return DjangoWalletRepository()


@functools.cache
def wallet_transaction_repository() -> DjangoWalletTransactionRepository:
    return DjangoWalletTransactionRepository()


@functools.cache
def billing_ledger() -> DjangoBillingLedger:
    return DjangoBillingLedger(STARTING_BALANCE)


@functools.cache
def billing_history_reader() -> DjangoBillingHistoryReader:
    return DjangoBillingHistoryReader()


@functools.cache
def billing_cycle_service() -> BillingCycleService:
    return BillingCycleService(RATE_PER_KWH, OVERAGE_RATE_MULTIPLIER, zone_capacity_cache(), billing_ledger())


@functools.cache
def wallet_spending_service() -> WalletSpendingService:
    return WalletSpendingService(wallet_repository(), wallet_transaction_repository(), STARTING_BALANCE)


@functools.cache
def unlock_service() -> UnlockService:
    return UnlockService(billing_history_reader())


def connect() -> None:
    """Starts driving ``billing_cycle_service()`` from zone demand and
    ``zone_capacity_cache()`` from Distributor's zone-capacity broadcasts.

    Not called automatically anywhere in this project yet -- see
    ``billing.kafka.connect_listeners`` for why every app here leaves that to an
    explicit call rather than a side effect of import.
    """
    _connect_listeners(billing_cycle_service(), zone_capacity_cache())
