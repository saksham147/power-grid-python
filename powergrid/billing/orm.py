"""Django ORM adapters for the billing use cases' ports.

Backs ``billing.WalletRepository``/``billing.WalletTransactionRepository`` with the
``Wallet``/``WalletTransaction`` tables, ``billing.BillingHistoryReader`` with a sum
over both the raw and rolled-up billing history, and ``billing.BillingLedger`` with
one atomic write spanning both wallets and both history tables -- the concrete
Postgres side of the abstractions ``billing.py`` defines, the same relationship
``distributor.orm`` has to ``distributor.distribution``.
"""
import datetime

from django.db import transaction
from django.utils import timezone

from . import models as orm
from .billing import BillingHistoryReader, BillingLedger, WalletRepository, WalletTransactionRepository
from .domain import GRID_WALLET_ID, GRID_WALLET_NAME, BillingResult, TransactionType, Wallet, WalletTransaction


def _to_domain_wallet(row: orm.Wallet) -> Wallet:
    return Wallet(zone_id=row.zone_id, zone_name=row.zone_name, balance_rupees=row.balance_rupees,
                  updated_at=row.updated_at)


class DjangoWalletRepository(WalletRepository):
    """Reads and writes a wallet -- a zone's, or the shared Grid wallet.

    ``get_for_update`` must be called inside a transaction the caller controls -- the
    lock it takes is released when that transaction ends, not when this method
    returns, exactly as ``billing.WalletRepository`` documents.
    """

    def get_for_update(self, wallet_id: str) -> Wallet | None:
        try:
            row = orm.Wallet.objects.select_for_update().get(pk=wallet_id)
        except orm.Wallet.DoesNotExist:
            return None
        return _to_domain_wallet(row)

    def save(self, wallet: Wallet) -> None:
        orm.Wallet.objects.update_or_create(
            zone_id=wallet.zone_id,
            defaults={
                'zone_name': wallet.zone_name,
                'balance_rupees': wallet.balance_rupees,
                'updated_at': wallet.updated_at or timezone.now(),
            },
        )


class DjangoWalletTransactionRepository(WalletTransactionRepository):
    """Records one wallet ledger movement. Insert-only."""

    def save(self, transaction: WalletTransaction) -> None:
        orm.WalletTransaction.objects.create(
            zone_id=transaction.zone_id,
            type=transaction.type.value,
            amount_rupees=transaction.amount_rupees,
            balance_after_rupees=transaction.balance_after_rupees,
            occurred_at=transaction.occurred_at,
        )


class DjangoBillingHistoryReader(BillingHistoryReader):
    """Cumulative energy billed so far, across both raw and rolled-up history -- a
    rollup replaces the raw rows it summarises rather than sit alongside them, so
    summing both never double-counts either side.
    """

    def cumulative_kwh_sold(self) -> float:
        return orm.BillingRecord.objects.sum_kwh() + orm.BillingDailyRollup.objects.sum_total_kwh()


class DjangoBillingLedger(BillingLedger):
    """Checks the idempotency guard, debits the zone's wallet (creating it at the
    starting balance on its first-ever charge), credits the Grid wallet by the same
    amount (creating it the same way), and writes both the billing record and both
    wallet transactions -- all inside one transaction, so a crash midway can never
    leave a debit with no record of why, or a record with no matching debit.

    Opens its own transaction rather than relying on a caller to -- unlike
    ``WalletRepository.get_for_update``, this is one port method that must be atomic
    by itself, which is exactly why ``billing.BillingLedger`` is shaped as a single
    method instead of separate "record" and "debit" ports.
    """

    def __init__(self, starting_balance: float):
        self._starting_balance = starting_balance

    @transaction.atomic
    def apply(self, zone_id: str, zone_name: str, tick: int, kwh: float, overage_kwh: float,
              rate_per_kwh: float, cost_rupees: float, overage_cost_rupees: float,
              at: datetime.datetime) -> BillingResult | None:
        if orm.BillingRecord.objects.filter(zone_id=zone_id, tick_number=tick).exists():
            return None

        wallet_row = self._debit(zone_id, zone_name, cost_rupees, at, TransactionType.BILL_DEBIT)

        orm.BillingRecord.objects.create(
            zone_id=zone_id, zone_name=zone_name, tick_number=tick, kwh=kwh, overage_kwh=overage_kwh,
            rate_per_kwh=rate_per_kwh, cost_rupees=cost_rupees, overage_cost_rupees=overage_cost_rupees,
            recorded_at=at,
        )

        # What the zone paid is what the grid earned: without this credit, revenue
        # would leave the zone's wallet and arrive nowhere.
        self._debit(GRID_WALLET_ID, GRID_WALLET_NAME, -cost_rupees, at, TransactionType.BILL_REVENUE)

        return BillingResult(
            zone_id=zone_id, zone_name=zone_name, tick=tick, kwh=kwh, overage_kwh=overage_kwh,
            rate_per_kwh=rate_per_kwh, cost_rupees=cost_rupees, overage_cost_rupees=overage_cost_rupees,
            balance_after_rupees=wallet_row.balance_rupees, timestamp=at,
        )

    def _debit(self, wallet_id: str, wallet_name: str, amount_rupees: float, at: datetime.datetime,
               transaction_type: TransactionType) -> orm.Wallet:
        """Lowers ``wallet_id``'s balance by ``amount_rupees`` (a negative amount
        raises it -- the Grid wallet's side of a zone's charge), lazily creating the
        wallet at the starting balance first if needed, and logs the movement."""
        row, _ = orm.Wallet.objects.select_for_update().get_or_create(
            zone_id=wallet_id,
            defaults={'zone_name': wallet_name, 'balance_rupees': self._starting_balance, 'updated_at': at},
        )
        row.zone_name = wallet_name
        row.balance_rupees -= amount_rupees
        row.updated_at = at
        row.save()

        orm.WalletTransaction.objects.create(
            zone_id=wallet_id, type=transaction_type.value, amount_rupees=abs(amount_rupees),
            balance_after_rupees=row.balance_rupees, occurred_at=at,
        )
        return row
