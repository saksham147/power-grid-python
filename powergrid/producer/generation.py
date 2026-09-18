"""Per-tick output for each plant type.

Ported from Power-Grid's ``Producer.generation`` package (Java): one deterministic
strategy per :class:`~producer.models.PlantType`, plus the service that runs all
active plants through their strategy for one tick. Tick/time math comes from the
project-level ``simulation`` app rather than a local copy, since Django is one
process and every app can share the one canonical clock.
"""
import enum
import logging
import math

from django.db import transaction
from django.utils import timezone

from simulation.clock import TICKS_PER_DAY, day_number, energy_mwh

from .models import GenerationRecord, PlantType, PowerPlant

logger = logging.getLogger(__name__)

_MASK64 = (1 << 64) - 1


def noise(stream: int, step: int) -> float:
    """Deterministic pseudo-random value in [0, 1), derived from a stream and a step.

    This is what keeps the simulation replayable: the same (stream, step) always
    produces the same value. A SplitMix64 finalizer -- allocation-free and
    well-distributed for adjacent seeds/steps, which a naive seeded PRNG is not.
    """
    h = (stream * 0xD1B54A32D192ED03 + step * 0x9E3779B97F4A7C15) & _MASK64
    h = ((h ^ (h >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    h = ((h ^ (h >> 27)) * 0x94D049BB133111EB) & _MASK64
    h ^= h >> 31
    return (h >> 11) * (2.0 ** -53)


# Simulated days in one season; 4 seasons x 22 simulated days = an 88-day simulated year.
_DAYS_PER_SEASON = 22


class Season(enum.Enum):
    """The simulated year's season, purely a function of the tick number. Multiplies
    on top of the daily/weather capacity factor in the solar/wind strategies -- it
    scales the curve, it does not replace it.

    Multipliers are deliberately asymmetric between solar and wind: winter has weak
    sun but often stronger, more consistent wind, and summer the reverse.
    """

    SPRING = (1.00, 1.05)
    SUMMER = (1.15, 0.85)
    AUTUMN = (0.90, 1.10)
    WINTER = (0.70, 1.20)

    def __init__(self, solar_factor, wind_factor):
        self.solar_factor = solar_factor
        self.wind_factor = wind_factor

    @classmethod
    def of(cls, tick_number: int) -> 'Season':
        day = day_number(tick_number)
        members = list(cls)
        index = (day // _DAYS_PER_SEASON) % len(members)
        return members[index]


class GenerationStrategy:
    """Computes a plant's output for one tick. Stateless; one instance per plant type."""

    supported_type: str

    def calculate_output(self, plant: PowerPlant, tick_number: int, frequency_deviation: float) -> float:
        raise NotImplementedError


class ThermalGenerationStrategy(GenerationStrategy):
    """Governor speed-droop control for a synchronous thermal unit.

    R = (delta-f / f0) / (delta-P / P_rated), rearranged for the power response:
    deltaP = -(delta-f / f0) x P_rated / R. Frequency below nominal means a deficit,
    so the governor opens up -- output moves opposite to the deviation.
    """

    supported_type = PlantType.THERMAL

    NOMINAL_FREQUENCY_HZ = 50.0
    DROOP = 0.04  # 4% droop -- typical utility turbine governor setting.

    def calculate_output(self, plant, tick_number, frequency_deviation):
        per_unit_frequency_error = frequency_deviation / self.NOMINAL_FREQUENCY_HZ
        response_mw = -(per_unit_frequency_error / self.DROOP) * plant.capacity_mw
        requested = plant.base_output_mw + response_mw

        # Physical headroom: cannot exceed rating, cannot go below technical minimum.
        return min(max(requested, plant.min_output_mw), plant.capacity_mw)


class SolarGenerationStrategy(GenerationStrategy):
    """Simulated capacity factor for a PV farm: a diurnal curve with cloud cover on top.

    frequency_deviation is ignored -- PV is inverter-coupled and non-dispatchable, it
    has no governor and contributes nothing to primary frequency response.
    """

    supported_type = PlantType.SOLAR

    SUNRISE = 0.25  # 06:00 as a fraction of the day
    SUNSET = 0.75  # 18:00
    MIN_CLOUD_FACTOR = 0.70

    def calculate_output(self, plant, tick_number, frequency_deviation):
        day_fraction = (tick_number % TICKS_PER_DAY) / TICKS_PER_DAY

        # Half-sine standing in for solar elevation: zero at sunrise, peak at solar
        # noon, zero at sunset; negative outside the window, floored to night-time zero.
        elevation = math.sin(math.pi * (day_fraction - self.SUNRISE) / (self.SUNSET - self.SUNRISE))
        clear_sky = max(0.0, elevation)

        cloud_factor = self.MIN_CLOUD_FACTOR + (1.0 - self.MIN_CLOUD_FACTOR) * noise(plant.id, tick_number)
        season_factor = Season.of(tick_number).solar_factor

        # Capped at 1.0: a summer boost narrows the gap to nameplate, it doesn't let
        # the panel exceed its own rated capacity.
        capacity_factor = min(1.0, clear_sky * cloud_factor * season_factor)

        return plant.capacity_mw * capacity_factor


class WindGenerationStrategy(GenerationStrategy):
    """Simulated capacity factor for a wind farm: a slow weather front modulated by
    fast gusts. Like solar, ignores frequency_deviation.

    The two periods are deliberately incommensurate so the sum never repeats on a
    short cycle, and each farm gets its own phase offset via noise(plant.id, 0).
    """

    supported_type = PlantType.WIND

    WEATHER_FRONT_PERIOD = 2003  # slow synoptic variation
    GUST_PERIOD = 37  # fast turbulence riding on top

    FRONT_WEIGHT = 0.70
    GUST_WEIGHT = 0.20
    NOISE_WEIGHT = 0.10

    MIN_CAPACITY_FACTOR = 0.05  # idle below cut-in wind speed
    MAX_CAPACITY_FACTOR = 0.95

    def calculate_output(self, plant, tick_number, frequency_deviation):
        phase = noise(plant.id, 0) * 2 * math.pi

        front = 0.5 + 0.5 * math.sin(2 * math.pi * tick_number / self.WEATHER_FRONT_PERIOD + phase)
        gust = 0.5 + 0.5 * math.sin(2 * math.pi * tick_number / self.GUST_PERIOD + phase)

        capacity_factor = (
            self.FRONT_WEIGHT * front
            + self.GUST_WEIGHT * gust
            + self.NOISE_WEIGHT * noise(plant.id, tick_number)
        )
        season_factor = Season.of(tick_number).wind_factor

        # Re-clamped after the season scaling: a winter boost can push the raw weighted
        # sum past MAX_CAPACITY_FACTOR, and turbines still cap out the same in winter.
        clamped = min(max(capacity_factor * season_factor, self.MIN_CAPACITY_FACTOR), self.MAX_CAPACITY_FACTOR)

        return plant.capacity_mw * clamped


STRATEGIES_BY_TYPE = {
    strategy.supported_type: strategy
    for strategy in (ThermalGenerationStrategy(), SolarGenerationStrategy(), WindGenerationStrategy())
}


@transaction.atomic
def handle_tick(tick_number: int, frequency_deviation: float) -> list[dict]:
    """Turns one tick into one output reading per active plant.

    One DB read, in-memory strategy dispatch, one batched write-back of current
    state, one batched insert of history -- ported from
    ``Producer.generation.GenerationService.handleTick``.
    """
    plants = list(PowerPlant.objects.filter(active=True))
    events = []
    history_rows = []
    timestamp = timezone.now()

    for plant in plants:
        strategy = STRATEGIES_BY_TYPE.get(plant.type)
        if strategy is None:
            logger.warning('No strategy for plant type %s (plant %s), skipping', plant.type, plant.id)
            continue

        output_mw = strategy.calculate_output(plant, tick_number, frequency_deviation)

        plant.current_output_mw = output_mw
        plant.add_energy(energy_mwh(output_mw))

        events.append({
            'plant_id': plant.id,
            'tick_number': tick_number,
            'output_mw': output_mw,
            'timestamp': timestamp,
        })
        history_rows.append(GenerationRecord(
            plant_id=plant.id,
            plant_type=plant.type,
            tick_number=tick_number,
            output_mw=output_mw,
            frequency_deviation=frequency_deviation,
            recorded_at=timestamp,
        ))

    if plants:
        PowerPlant.objects.bulk_update(plants, ['current_output_mw', 'energy_mwh'])
    if history_rows:
        GenerationRecord.objects.bulk_create(history_rows)

    logger.debug('Tick %s (deviation %s Hz): %d output events', tick_number, frequency_deviation, len(events))
    return events
