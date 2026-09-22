from django.db import models
from django.db.models import Max


class DistributionRecordQuerySet(models.QuerySet):
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


class DistributionRecord(models.Model):
    """One zone's merged supply-and-demand balance for one tick. Insert-only: a record
    of what happened is never edited.

    One row per zone per demand reading, not a tick-wide batch of many plants the way
    Producer's generation history is -- so a plain insert per reading is already a
    single round trip, with no identity-batching concern to work around.
    """

    zone_id = models.CharField(max_length=64)
    zone_name = models.CharField(max_length=200)
    tick_number = models.BigIntegerField()
    demand_kw = models.FloatField()
    supplied_kw = models.FloatField()
    balance_kw = models.FloatField()
    recorded_at = models.DateTimeField()

    objects = DistributionRecordQuerySet.as_manager()

    class Meta:
        db_table = 'distributor_distribution_record'
        indexes = [
            models.Index(fields=['zone_id', 'recorded_at'], name='ix_dist_record_zone_time'),
            models.Index(fields=['recorded_at'], name='ix_dist_record_time'),
        ]
        ordering = ['-tick_number']

    def __str__(self):
        return f'zone {self.zone_id} @ tick {self.tick_number}: balance {self.balance_kw:.2f} kW'


class ZoneCapacity(models.Model):
    """The power capacity assigned to a zone -- a billing-relevant ceiling, not a hard
    limit on delivery: the merge still allocates supply purely by demand share,
    unchanged by this. A zone with no row here is uncapped, billed at the normal rate
    regardless of how much it draws.
    """

    zone_id = models.CharField(max_length=64, primary_key=True)
    zone_name = models.CharField(max_length=200)
    capacity_kw = models.FloatField()
    # Set on every save, both create and update, so it always reflects the last change.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'distributor_zone_capacity'

    def __str__(self):
        return f'{self.zone_id}: {self.capacity_kw:.2f} kW'


class DistributionDailyRollup(models.Model):
    """One zone's balance history over one simulated day -- the compressed form a
    ``DistributionRecord`` ages into once it falls outside the raw retention window.

    Why a simulated day, not a real-time bucket: the retention window this replaces is
    itself defined in simulated days, so a paused or restarted simulation must not
    silently shrink or stretch how much history survives. A simulated day is exactly
    288 ticks, so the bucket key is ``tick_number // 288``.

    Nothing here is summed the way a plant's energy is: demand/supplied/balance are
    instantaneous kW readings, not power held over an interval, so there is no additive
    total to preserve -- avg/min/max keep the shape a day's raw rows had, and only the
    tick-by-tick detail within the day is given up.

    Rows are meant to be written by one set-based INSERT...SELECT executed inside
    Postgres, never built up in Python from raw rows.
    """

    zone_id = models.CharField(max_length=64)
    zone_name = models.CharField(max_length=200)

    # tick_number // 288 -- simulated day 0 is ticks 0-287, day 1 is 288-575, and so on.
    simulated_day = models.BigIntegerField()

    avg_demand_kw = models.FloatField()
    min_demand_kw = models.FloatField()
    max_demand_kw = models.FloatField()

    avg_supplied_kw = models.FloatField()
    min_supplied_kw = models.FloatField()
    max_supplied_kw = models.FloatField()

    avg_balance_kw = models.FloatField()
    min_balance_kw = models.FloatField()
    max_balance_kw = models.FloatField()

    sample_count = models.IntegerField()

    # Lowest/highest tick number rolled into this day. Only a true range when no
    # restart reset the tick counter mid-day.
    first_tick = models.BigIntegerField()
    last_tick = models.BigIntegerField()

    class Meta:
        db_table = 'distributor_distribution_daily_rollup'
        constraints = [
            models.UniqueConstraint(
                fields=['zone_id', 'simulated_day'], name='uq_dist_daily_rollup_zone_day'),
        ]
        indexes = [
            models.Index(fields=['simulated_day'], name='ix_dist_daily_rollup_day'),
        ]
        ordering = ['-simulated_day']

    def __str__(self):
        return f'zone {self.zone_id} @ day {self.simulated_day}: avg balance {self.avg_balance_kw:.2f} kW'
