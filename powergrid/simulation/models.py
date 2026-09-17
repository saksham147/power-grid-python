from django.db import models


class SimulationState(models.Model):
    """Singleton row: the shared clock's current tick and frequency deviation.

    Ported from Grid's role in Power-Grid as "the single owner of simulation time".
    Every app reads this (via ``SimulationState.load()``) instead of keeping its own
    counter, and the ``simulation`` app's ``runsimulation`` command is the only thing
    that advances it.
    """

    current_tick = models.BigIntegerField(default=0)
    frequency_deviation_hz = models.FloatField(default=0.0)

    # Whether frequency_deviation_hz is recomputed automatically each tick from
    # reported fleet supply/demand (see simulation.frequency), or held at whatever a
    # manual override last set it to.
    auto_control = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Simulation state'
        verbose_name_plural = 'Simulation state'

    def __str__(self):
        return f'tick {self.current_tick}, deviation {self.frequency_deviation_hz:+.3f} Hz'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'SimulationState':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
