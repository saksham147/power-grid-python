from django.core.exceptions import ValidationError
from django.db import models


class PlantType(models.TextChoices):
    """Dispatchable vs. non-dispatchable: THERMAL is governor-controlled; SOLAR/WIND take
    whatever the weather gives them."""

    THERMAL = 'THERMAL', 'Thermal'
    SOLAR = 'SOLAR', 'Solar'
    WIND = 'WIND', 'Wind'


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

    class Meta:
        db_table = 'producer_generation_record'
        indexes = [
            models.Index(fields=['plant_id', 'recorded_at'], name='ix_gen_record_plant_time'),
            models.Index(fields=['recorded_at'], name='ix_gen_record_time'),
        ]
        ordering = ['-tick_number']

    def __str__(self):
        return f'plant {self.plant_id} @ tick {self.tick_number}: {self.output_mw:.2f} MW'
