"""Request and response bodies for the distributor HTTP API.

Plain functions rather than a serializer framework: there is no DRF here and each
shape is a handful of fields.
"""
import datetime
import math
import re
from http import HTTPStatus

from django.utils import timezone

from ..distribution import GridStateTracker
from ..domain import ZoneCapacity
from .exceptions import RequestValidationError

# Zone ids appear in URLs (zones/<id>/), so an id containing a slash could be created
# but never addressed again. Also the id Customer uses for the same zone should line
# up with this one, so it follows the same rule customer.api.dto applies to its own ids.
_ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
_ID_RULE = 'must be 1-64 characters: letters, digits, ".", "_" or "-", starting with a letter or digit'
_NAME_MAX_LENGTH = 200


def _id(value, label: str, errors: list[str]):
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        errors.append(f'{label}: {_ID_RULE}')
    return value


def _zone_name(body: dict, errors: list[str]):
    name = body.get('zoneName')
    if not isinstance(name, str) or not name.strip():
        errors.append('zoneName: must not be blank')
    elif len(name) > _NAME_MAX_LENGTH:
        errors.append(f'zoneName: must be at most {_NAME_MAX_LENGTH} characters')
    return name


def _capacity_kw(body: dict, errors: list[str]):
    """The capacity as a float, or None after recording why it is unacceptable.
    Booleans and NaN/Infinity are rejected: Python's JSON parser accepts the latter,
    and they would otherwise slip past a bare ``> 0`` comparison."""
    value = body.get('capacityKw')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append('capacityKw: must be a number')
    elif value <= 0:
        errors.append('capacityKw: must be positive')
    else:
        return float(value)
    return None


def parse_create_zone_capacity(body: dict) -> tuple[str, str, float]:
    """A new (or replaced) zone capacity, with the zone id carried in the body."""
    errors: list[str] = []
    zone_id = _id(body.get('zoneId'), 'zoneId', errors)
    zone_name = _zone_name(body, errors)
    capacity_kw = _capacity_kw(body, errors)
    if errors:
        raise RequestValidationError(errors)
    return zone_id, zone_name, capacity_kw


def parse_update_zone_capacity(zone_id: str, body: dict) -> tuple[str, str, float]:
    """New name and capacity for a zone, with the zone id carried by the URL path."""
    errors: list[str] = []
    _id(zone_id, 'zoneId (in the path)', errors)
    zone_name = _zone_name(body, errors)
    capacity_kw = _capacity_kw(body, errors)
    if errors:
        raise RequestValidationError(errors)
    return zone_id, zone_name, capacity_kw


def zone_capacity_response(capacity: ZoneCapacity, current_demand_kw: float,
                            updated_at: datetime.datetime | None) -> dict:
    """A zone's capacity as reported over HTTP, joined against its latest known demand
    so the caller can see draw against capacity live.

    ``over_capacity`` is purely informational: ``DistributionService`` allocates supply
    by demand share regardless of any capacity assigned here, so this never changes
    what the zone is actually delivered.
    """
    return {
        'zoneId': capacity.zone_id,
        'zoneName': capacity.zone_name,
        'capacityKw': float(capacity.capacity_kw),
        'currentDemandKw': float(current_demand_kw),
        'overCapacity': current_demand_kw > capacity.capacity_kw,
        'updatedAt': updated_at.isoformat() if updated_at else None,
    }


def status_response(state: GridStateTracker) -> dict:
    """A point-in-time view of what distributor currently knows -- not a substitute
    for the raw or rolled-up balance history, which carries the real per-zone detail
    this collapses into one system-wide snapshot."""
    total_supply_kw = state.total_supply_kw()
    total_demand_kw = state.total_demand_kw()
    return {
        'totalSupplyKw': float(total_supply_kw),
        'totalDemandKw': float(total_demand_kw),
        'balanceKw': float(total_supply_kw - total_demand_kw),
        'trackedPlantCount': state.tracked_plant_count(),
        'trackedZoneCount': state.tracked_zone_count(),
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
