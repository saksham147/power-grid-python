from django.core.exceptions import ValidationError
from django.db import connections, models
from django.db.models import Max


class PlantType(models.TextChoices):
    """Dispatchable vs. non-dispatchable: THERMAL is governor-controlled; SOLAR/WIND take
    whatever the weather gives them."""

    THERMAL = 'THERMAL', 'Thermal'
    SOLAR = 'SOLAR', 'Solar'
    WIND = 'WIND', 'Wind'


class PowerPlantQuerySet(models.QuerySet):
    """Ported from ``Producer.model.PowerPlantRepository``."""

    def active(self):
        """Plants that take part in a tick."""
        return self.filter(active=True)


class GenerationRecordQuerySet(models.QuerySet):
    """Ported from ``Producer.model.GenerationRecordRepository``."""

    def history(self, plant_id, start, end, limit):
        """Newest first, half-open ``[start, end)`` so adjacent ranges never share a row."""
        return self.filter(
            plant_id=plant_id, recorded_at__gte=start, recorded_at__lt=end,
        ).order_by('-recorded_at')[:limit]

    def delete_recorded_before(self, cutoff):
        """Bulk delete of everything recorded before the cutoff. One DELETE statement --
        the model has no relations or signals, so no instance is loaded, which matters
        because a rollup run may cover thousands of rows.

        :return: number of rows deleted
        """
        deleted, _ = self.filter(recorded_at__lt=cutoff).delete()
        return deleted

    def max_tick_number(self):
        """Highest tick number among raw rows, across every plant, or None if empty."""
        return self.aggregate(highest=Max('tick_number'))['highest']


class GenerationRollupQuerySet(models.QuerySet):
    """Ported from ``Producer.model.GenerationRollupRepository``."""

    def roll_up_recorded_before(self, cutoff, minutes_per_tick):
        """Compresses every raw ``GenerationRecord`` recorded before the cutoff into one
        row per plant per real minute.

        Native SQL because the aggregation runs entirely inside Postgres: no raw row is
        ever loaded into this process, however large the backlog. Energy is summed per
        tick -- output held for the tick's simulated minutes -- so a bucket's
        ``energy_mwh`` is exactly the total of the raw rows it replaces.

        Must run in the same transaction as ``GenerationRecord.objects
        .delete_recorded_before`` with the same cutoff, or rows could be summarised and
        then kept, or deleted without being summarised. The unique key on
        ``(plant_id, bucket_start)`` turns a bucket rolled twice into a failed run
        rather than silently doubled energy.

        :return: number of rollup rows inserted
        """
        connection = connections[self.db]
        record_table = connection.ops.quote_name(GenerationRecord._meta.db_table)
        rollup_table = connection.ops.quote_name(self.model._meta.db_table)

        with connection.cursor() as cursor:
            cursor.execute(f"""
                insert into {rollup_table}
                    (plant_id, plant_type, bucket_start,
                     avg_output_mw, min_output_mw, max_output_mw,
                     energy_mwh, sample_count, first_tick, last_tick)
                select plant_id,
                       plant_type,
                       date_trunc('minute', recorded_at),
                       avg(output_mw),
                       min(output_mw),
                       max(output_mw),
                       (sum(output_mw) * %s) / 60,
                       count(*),
                       min(tick_number),
                       max(tick_number)
                from {record_table}
                where recorded_at < %s
                group by plant_id, plant_type, date_trunc('minute', recorded_at)
            """, [minutes_per_tick, cutoff])
            return cursor.rowcount

    def history(self, plant_id, start, end, limit):
        """Newest first, half-open ``[start, end)``."""
        return self.filter(
            plant_id=plant_id, bucket_start__gte=start, bucket_start__lt=end,
        ).order_by('-bucket_start')[:limit]

    def max_last_tick(self):
        """Highest ``last_tick`` among rollup rows, across every plant, or None if empty."""
        return self.aggregate(highest=Max('last_tick'))['highest']


class PowerPlant(models.Model):
    """A single generating unit. Ported from Power-Grid's ``Producer.model.PowerPlant``."""

    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=PlantType.choices)

    # Nameplate rating. Also the base that droop response is scaled against.
    capacity_mw = models.FloatField()

    # Technical minimum. A thermal unit cannot be turned down below roughly 40% of rating
    # without tripping offline; renewables carry 0 here.
    min_output_mw = models.FloatField()

    # The scheduled dispatch setpoint the thermal droop response adjusts around.
    base_output_mw = models.FloatField()

    # Result of the most recent tick. Written back once per tick; set to base_output_mw
    # at creation (there is no separate "starting output" input, mirroring the Java
    # constructor, which does not take this as a parameter either).
    current_output_mw = models.FloatField(default=0.0)

    # Cumulative energy this unit has generated, MWh. Persisted (not summed in memory)
    # so it survives a restart.
    energy_mwh = models.FloatField(default=0)

    active = models.BooleanField(default=True)

    objects = PowerPlantQuerySet.as_manager()

    class Meta:
        db_table = 'producer_power_plant'

    def __str__(self):
        return self.name

    @staticmethod
    def _check_ratings(capacity_mw, min_output_mw, base_output_mw):
        if min_output_mw > capacity_mw:
            raise ValidationError(
                f'minOutputMw ({min_output_mw}) cannot exceed capacityMw ({capacity_mw})')
        if base_output_mw > capacity_mw:
            raise ValidationError(
                f'baseOutputMw ({base_output_mw}) cannot exceed capacityMw ({capacity_mw})')
        if base_output_mw < min_output_mw:
            raise ValidationError(
                f'baseOutputMw ({base_output_mw}) cannot be below minOutputMw ({min_output_mw})')

    def clean(self):
        self._check_ratings(self.capacity_mw, self.min_output_mw, self.base_output_mw)

    def upgrade(self, name, capacity_mw, min_output_mw, base_output_mw):
        """Re-rates this unit: new name and new ratings, applied together so it can
        never be halfway through a re-rating."""
        self._check_ratings(capacity_mw, min_output_mw, base_output_mw)
        self.name = name
        self.capacity_mw = capacity_mw
        self.min_output_mw = min_output_mw
        self.base_output_mw = base_output_mw
        # Only the upper bound is clamped: an idle unit below the new minimum is a real
        # state, forcing it up would invent output the plant isn't producing.
        self.current_output_mw = min(self.current_output_mw, capacity_mw)

    def add_energy(self, mwh):
        """Adds one tick's worth of generation. Accumulate-only."""
        self.energy_mwh += mwh

    def save(self, *args, **kwargs):
        self._check_ratings(self.capacity_mw, self.min_output_mw, self.base_output_mw)
        if self._state.adding:
            self.current_output_mw = self.base_output_mw
        super().save(*args, **kwargs)


class GenerationRecord(models.Model):
    """One plant's output on one tick. Insert-only history, ported from
    ``Producer.model.GenerationRecord``.

    No foreign key to PowerPlant: plants can be deleted, and history is an audit log
    that outlives the plant, so it carries the type it needs to stay meaningful on its
    own rather than cascading or blocking deletes.
    """

    plant_id = models.BigIntegerField()
    plant_type = models.CharField(max_length=20, choices=PlantType.choices)
    tick_number = models.BigIntegerField()
    output_mw = models.FloatField()
    frequency_deviation = models.FloatField()
    recorded_at = models.DateTimeField()

    objects = GenerationRecordQuerySet.as_manager()

    class Meta:
        db_table = 'producer_generation_record'
        indexes = [
            models.Index(fields=['plant_id', 'recorded_at'], name='ix_gen_record_plant_time'),
            models.Index(fields=['recorded_at'], name='ix_gen_record_time'),
        ]
        ordering = ['-tick_number']

    def __str__(self):
        return f'plant {self.plant_id} @ tick {self.tick_number}: {self.output_mw:.2f} MW'


class GenerationRollup(models.Model):
    """One plant's generation over one real minute -- exactly one simulated hour at
    this simulation's pace (5 simulated minutes/tick x 12 ticks/minute). Ported from
    ``Producer.model.GenerationRollup``.

    A real minute rather than a real hour because the simulation runs 60x faster than
    real time: an hourly bucket would span 2.5 simulated days and average every
    day/night cycle into an identical row, whereas a minute keeps 24 points per
    simulated day and so the solar curve survives.

    Never written through the ORM's per-instance ``save``: rows arrive only via
    ``GenerationRollup.objects.roll_up_recorded_before``, one set-based INSERT...SELECT.
    """

    plant_id = models.BigIntegerField()
    plant_type = models.CharField(max_length=20, choices=PlantType.choices)

    # Start of the real minute this row summarises, truncated to the minute.
    bucket_start = models.DateTimeField()

    avg_output_mw = models.FloatField()
    min_output_mw = models.FloatField()
    max_output_mw = models.FloatField()

    # Exact: energy is additive, so the bucket total equals the raw rows it replaced.
    # Only the shape *within* the simulated hour is given up.
    energy_mwh = models.FloatField()

    # Normally 12; fewer means a restart or an outage left a gap in that minute.
    sample_count = models.IntegerField()

    # Lowest/highest tick number in the bucket. Only meaningful as a range when no
    # restart fell inside the minute, since the tick counter resets.
    first_tick = models.BigIntegerField()
    last_tick = models.BigIntegerField()

    objects = GenerationRollupQuerySet.as_manager()

    class Meta:
        db_table = 'producer_generation_rollup'
        constraints = [
            models.UniqueConstraint(
                fields=['plant_id', 'bucket_start'], name='uq_generation_rollup_plant_bucket'),
        ]
        indexes = [
            models.Index(fields=['bucket_start'], name='ix_generation_rollup_bucket'),
        ]
        ordering = ['-bucket_start']

    def __str__(self):
        return f'plant {self.plant_id} @ {self.bucket_start}: avg {self.avg_output_mw:.2f} MW'
