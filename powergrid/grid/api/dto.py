"""Request and response bodies for the grid HTTP API.

Plain functions rather than a serializer framework: there is no DRF here and each
shape is a handful of fields.
"""
import math
from http import HTTPStatus

from django.utils import timezone

from ..status import GridStatus
from .exceptions import RequestValidationError

# Bounded at a quarter of a hertz either way. Real interconnects trip protection long
# before that, and at 4% droop a 0.25 Hz dip already asks a thermal unit for 12.5% of
# its rating -- past this the clamp to capacity would be doing all the work and the
# number would stop meaning anything.
MAX_FREQUENCY_DEVIATION_HZ = 0.25


def parse_frequency_deviation_request(body: dict) -> float:
    """A new grid frequency deviation, in Hz. Required and bounded, so a body
    omitting the field -- or asking for more than the grid can plausibly carry -- is
    rejected rather than silently returning the grid to nominal or accepted as-is.
    """
    value = body.get('frequencyDeviation')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RequestValidationError(['frequencyDeviation: must be a number'])
    if abs(value) > MAX_FREQUENCY_DEVIATION_HZ:
        raise RequestValidationError(
            [f'frequencyDeviation: must be between -{MAX_FREQUENCY_DEVIATION_HZ} and '
             f'{MAX_FREQUENCY_DEVIATION_HZ}'])
    return float(value)


def status_response(status: GridStatus) -> dict:
    return {
        'tickNumber': status.tick_number,
        'simulatedTime': status.simulated_time,
        'simulatedDay': status.simulated_day,
        'tickIntervalSeconds': status.tick_interval_seconds,
        'frequencyDeviationHz': status.frequency_deviation_hz,
        'autoControlEnabled': status.auto_control_enabled,
        'totalSupplyKw': status.total_supply_kw,
        'totalDemandKw': status.total_demand_kw,
        'loadExceeded': status.load_exceeded,
    }


def api_error(status: HTTPStatus, message: str, details: list[str] | None = None) -> dict:
    """The single error shape for this API."""
    return {
        'timestamp': timezone.now().isoformat(),
        'status': status.value,
        'error': status.phrase,
        'message': message,
        'details': details or [],
    }
