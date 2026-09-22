"""Django ORM models for the billing app: the Postgres tables backing the ports
``billing.py`` defines -- wallets, the wallet ledger, the raw per-tick billing
history, and its compressed daily form. The same relationship ``distributor.models``
has to ``distributor.distribution``.
"""
from django.db import models
from django.db.models import Max, Sum

from .domain import TransactionType

_TRANSACTION_TYPE_CHOICES = [(t.value, t.value) for t in TransactionType]


class Wallet(models.Model):
    """A running balance -- a zone's, or the shared Grid wallet (see
    ``billing.domain.GRID_WALLET_ID``). One row per wallet, created lazily the first
    time it is billed or spends.
    """

    zone_id = models.CharField(max_length=64, primary_key=True)
    zone_name = models.CharField(max_length=200)
    balance_rupees = models.FloatField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = 'billing_wallet'

    def __str__(self):
        return f'{self.zone_id}: ₹{self.balance_rupees:.2f}'


class WalletTransaction(models.Model):
    """One wallet ledger movement. Insert-only, and deliberately separate from
    ``BillingRecord`` -- see ``billing.domain.WalletTransaction`` for why."""

    zone_id = models.CharField(max_length=64)
    type = models.CharField(max_length=32, choices=_TRANSACTION_TYPE_CHOICES)
    amount_rupees = models.FloatField()
    balance_after_rupees = models.FloatField()
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = 'billing_wallet_transaction'
        indexes = [
            models.Index(fields=['zone_id', 'occurred_at'], name='ix_wallet_txn_zone_time'),
        ]
        ordering = ['-occurred_at']

    def __str__(self):
        return f'{self.zone_id} {self.type} ₹{self.amount_rupees:.2f}'


class BillingRecordQuerySet(models.QuerySet):
    """The queries the raw-history table needs beyond plain create/read."""

    def delete_before(self, cutoff_tick: int) -> int:
        """Bulk delete of every row strictly before ``cutoff_tick``. A single
        statement: no row is loaded, which matters when a rollup run covers
        thousands of them."""
        deleted, _ = self.filter(tick_number__lt=cutoff_tick).delete()
        return deleted

    def max_tick_number(self):
        """Highest tick number among raw rows, across every zone, or None if empty."""
        return self.aggregate(m=Max('tick_number'))['m']

    def sum_kwh(self) -> float:
        """Every kWh billed across these rows -- half of cumulative energy sold, all
        time; the other half is ``BillingDailyRollup.objects.sum_total_kwh()``."""
        return self.aggregate(s=Sum('kwh'))['s'] or 0.0


class BillingRecord(models.Model):
    """One zone's billing charge for one tick. Insert-only: a record of what was
    billed is never edited.

    The unique ``(zone_id, tick_number)`` constraint is the idempotency guard against
    redelivery of the same demand reading -- see ``billing.BillingLedger``.
    """

    zone_id = models.CharField(max_length=64)
    zone_name = models.CharField(max_length=200)
    tick_number = models.BigIntegerField()
    kwh = models.FloatField()
    overage_kwh = models.FloatField()
    rate_per_kwh = models.FloatField()
    cost_rupees = models.FloatField()
    overage_cost_rupees = models.FloatField()
    recorded_at = models.DateTimeField()

    objects = BillingRecordQuerySet.as_manager()

    class Meta:
        db_table = 'billing_billing_record'
        constraints = [
            models.UniqueConstraint(fields=['zone_id', 'tick_number'], name='uq_billing_record_zone_tick'),
        ]
        indexes = [
            models.Index(fields=['zone_id', 'recorded_at'], name='ix_billing_record_zone_time'),
        ]
        ordering = ['-tick_number']

    def __str__(self):
        return f'zone {self.zone_id} @ tick {self.tick_number}: ₹{self.cost_rupees:.2f}'


class BillingDailyRollupQuerySet(models.QuerySet):
    """The one query the compressed table needs beyond plain create/read."""

    def sum_total_kwh(self) -> float:
        """The rolled-up half of cumulative energy sold, all time -- see
        ``BillingRecordQuerySet.sum_kwh`` for the raw half."""
        return self.aggregate(s=Sum('total_kwh'))['s'] or 0.0


class BillingDailyRollup(models.Model):
    """One zone's billing history over one simulated day -- the compressed form
    ``BillingRecord`` ages into once it falls outside the raw retention window. See
    ``distributor.models.DistributionDailyRollup`` for the sibling table this mirrors,
    down to the simulated-day-not-wall-clock-time reasoning.

    kWh and rupees are additive -- energy and money held over a tick, not an
    instantaneous reading -- so ``total_kwh``/``total_cost_rupees`` are exact sums of
    the raw rows they replace, unlike distributor's avg/min/max. ``avg_rate_per_kwh``
    is kept for reference only; it is not itself used to reconstruct cost.

    Rows are meant to be written by one set-based INSERT...SELECT executed inside
    Postgres, never built up in Python from raw rows.
    """

    zone_id = models.CharField(max_length=64)
    zone_name = models.CharField(max_length=200)

    # tick_number // 288 -- simulated day 0 is ticks 0-287, day 1 is 288-575, and so on.
    simulated_day = models.BigIntegerField()

    total_kwh = models.FloatField()
    total_overage_kwh = models.FloatField()
    avg_rate_per_kwh = models.FloatField()
    total_cost_rupees = models.FloatField()
    total_overage_cost_rupees = models.FloatField()

    sample_count = models.IntegerField()

    # Lowest/highest tick number rolled into this day. Only a true range when no
    # restart reset the tick counter mid-day.
    first_tick = models.BigIntegerField()
    last_tick = models.BigIntegerField()

    objects = BillingDailyRollupQuerySet.as_manager()

    class Meta:
        db_table = 'billing_billing_daily_rollup'
        constraints = [
            models.UniqueConstraint(fields=['zone_id', 'simulated_day'], name='uq_billing_daily_rollup_zone_day'),
        ]
        indexes = [
            models.Index(fields=['simulated_day'], name='ix_billing_daily_rollup_day'),
        ]
        ordering = ['-simulated_day']

    def __str__(self):
        return f'zone {self.zone_id} @ day {self.simulated_day}: ₹{self.total_cost_rupees:.2f}'
