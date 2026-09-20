"""Wire-shaped request/response bodies for Producer's HTTP API.

Ported from Power-Grid's ``Producer.api.dto`` (Java records). Plain functions rather
than a serializer framework: there is no DRF here, and each shape is a handful of
fields. Only single-field rules live in this file; the cross-field rules (minimum
and setpoint within capacity, setpoint not below the minimum) belong to
``PowerPlant`` itself, so create and upgrade reject exactly the same combinations.
"""
import math
from http import HTTPStatus

from django.utils import timezone

from producer.history import HistoryPoint
from producer.models import PlantType, PowerPlant

from .exceptions import RequestValidationError

_NAME_MAX_LENGTH = PowerPlant._meta.get_field('name').max_length


def _number(body: dict, key: str, errors: list[str], *, positive: bool):
    """The value as a float, or None after recording why it is not acceptable.

    Booleans are rejected (``True`` is an ``int`` in Python) and so are NaN and
    Infinity, which Python's JSON parser accepts but which would slip past every
    ``> 0`` / ``< 0`` comparison and be stored as a rating.
    """
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f'{key}: must be a number')
    elif positive and value <= 0:
        errors.append(f'{key}: must be positive')
    elif not positive and value < 0:
        errors.append(f'{key}: must be positive or zero')
    else:
        return float(value)
    return None


def _plant_fields(body: dict, errors: list[str]) -> dict:
    name = body.get('name')
    if not isinstance(name, str) or not name.strip():
        errors.append('name: must not be blank')
    elif len(name) > _NAME_MAX_LENGTH:
        errors.append(f'name: must be at most {_NAME_MAX_LENGTH} characters')

    return {
        'name': name,
        'capacity_mw': _number(body, 'capacityMw', errors, positive=True),
        'min_output_mw': _number(body, 'minOutputMw', errors, positive=False),
        'base_output_mw': _number(body, 'baseOutputMw', errors, positive=False),
    }


def parse_create_plant_request(body: dict) -> dict:
    """A new generating unit. Ported from ``CreatePlantRequest``."""
    errors: list[str] = []
    fields = _plant_fields(body, errors)

    plant_type = body.get('type')
    if plant_type not in PlantType.values:
        errors.append(f'type: must be one of {PlantType.values}')

    if errors:
        raise RequestValidationError(errors)
    return {**fields, 'type': plant_type}


def parse_upgrade_plant_request(body: dict) -> dict:
    """New name and ratings for an existing unit. Ported from ``UpgradePlantRequest``.

    There is no ``type`` on purpose: a plant's type selects the generation strategy
    that computes its output, so changing it would replace the machine rather than
    re-rate it. All four fields are required, which is why the endpoint is a PUT.
    """
    errors: list[str] = []
    fields = _plant_fields(body, errors)

    if errors:
        raise RequestValidationError(errors)
    return fields


def parse_update_active_request(body: dict) -> bool:
    """Takes a plant in or out of service. Ported from ``UpdatePlantActiveRequest``.

    The field must be present and a real boolean, rather than a missing one
    defaulting to false, so an incomplete body is rejected instead of silently
    deactivating the plant.
    """
    if body.get('active') is None:
        raise RequestValidationError(['active: must not be null'])
    if not isinstance(body['active'], bool):
        raise RequestValidationError(['active: must be a boolean'])
    return body['active']


def plant_response(plant: PowerPlant) -> dict:
    """A plant as reported over HTTP. Ported from ``PowerPlantResponse``.

    Mapped rather than serialising the model, so the wire format is not tied to the
    persistence model. Comparing ``currentOutputMw`` with ``baseOutputMw`` is how
    droop response is observed. The ``float()`` calls keep a freshly built instance
    (whose field defaults are still ints, e.g. ``energy_mwh = 0``) serialising the same
    as one read back from the database.
    """
    return {
        'id': plant.id,
        'name': plant.name,
        'type': plant.type,
        'capacityMw': float(plant.capacity_mw),
        'minOutputMw': float(plant.min_output_mw),
        'baseOutputMw': float(plant.base_output_mw),
        'currentOutputMw': float(plant.current_output_mw),
        'energyMwh': float(plant.energy_mwh),
        'active': plant.active,
    }


def history_point_response(point: HistoryPoint) -> dict:
    """One point of a plant's output-over-time series. Ported from ``HistoryPoint``."""
    return {
        'at': point.at.isoformat(),
        'resolution': point.resolution.value,
        'outputMw': point.output_mw,
        'minOutputMw': point.min_output_mw,
        'maxOutputMw': point.max_output_mw,
        'energyMwh': point.energy_mwh,
        'samples': point.samples,
        'firstTick': point.first_tick,
        'lastTick': point.last_tick,
    }


def api_error(status: HTTPStatus, message: str, details: list[str] | None = None) -> dict:
    """The single error shape for this API. Ported from ``ApiError``."""
    return {
        'timestamp': timezone.now().isoformat(),
        'status': status.value,
        'error': status.phrase,
        'message': message,
        'details': details or [],
    }
