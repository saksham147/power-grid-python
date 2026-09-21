"""Request and response bodies for the customer HTTP API.

Plain functions rather than a serializer framework: there is no DRF here and each shape
is a handful of fields. The parsers report every bad field at once, then build the domain
object, whose own constructor is the last line of defence for the invariants.
"""
import math
import re
from collections import Counter
from http import HTTPStatus

from django.utils import timezone

from simulation.clock import day_number, time_of_day

from ..application import CurrentDemand
from ..domain import ConsumerUnit, DemandProfile, Zone
from .exceptions import RequestValidationError

# Ids appear in URLs (``zones/<id>/``), so an id containing a slash could be created but
# never addressed again. Restricting them keeps every resource reachable. Leading
# alphanumeric rules out "." and ".." (which clients normalise away).
_ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
_ID_RULE = 'must be 1-64 characters: letters, digits, ".", "_" or "-", starting with a letter or digit'
_NAME_MAX_LENGTH = 200


def _id(value, label: str, errors: list[str]):
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        errors.append(f'{label}: {_ID_RULE}')
    return value


def _name(body: dict, errors: list[str]):
    name = body.get('name')
    if not isinstance(name, str) or not name.strip():
        errors.append('name: must not be blank')
    elif len(name) > _NAME_MAX_LENGTH:
        errors.append(f'name: must be at most {_NAME_MAX_LENGTH} characters')
    return name


def _profile(body: dict, errors: list[str]):
    name = body.get('type')
    if not isinstance(name, str) or name not in DemandProfile.__members__:
        errors.append(f'type: must be one of {list(DemandProfile.__members__)}')
        return None
    return DemandProfile[name]


def _capacity(body: dict, errors: list[str]):
    """The capacity as a float, or None after recording why it is unacceptable. Booleans
    and NaN/Infinity are rejected: Python's JSON parser accepts the latter, and they would
    slip past a bare ``> 0`` check."""
    value = body.get('capacityKw')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append('capacityKw: must be a number')
    elif value <= 0:
        errors.append('capacityKw: must be positive')
    else:
        return float(value)
    return None


def parse_create_zone(body: dict) -> Zone:
    errors: list[str] = []
    zone_id = _id(body.get('zoneId'), 'zoneId', errors)
    name = _name(body, errors)
    if errors:
        raise RequestValidationError(errors)
    return Zone(zone_id, name)


def parse_upgrade_zone(zone_id: str, body: dict) -> Zone:
    """New details for a zone: just a rename. The path is the identity being changed."""
    errors: list[str] = []
    _id(zone_id, 'zoneId (in the path)', errors)
    name = _name(body, errors)
    if errors:
        raise RequestValidationError(errors)
    return Zone(zone_id, name)


def parse_create_unit(body: dict) -> ConsumerUnit:
    errors: list[str] = []
    unit_id = _id(body.get('unitId'), 'unitId', errors)
    # The zone is deliberately not checked against the existing zones: a unit for a zone
    # created a moment later is not an error, and until that zone exists the unit simply
    # contributes to no zone's demand.
    zone_id = _id(body.get('zoneId'), 'zoneId', errors)
    name = _name(body, errors)
    profile = _profile(body, errors)
    capacity_kw = _capacity(body, errors)
    if errors:
        raise RequestValidationError(errors)
    return ConsumerUnit(unit_id, zone_id, name, profile, capacity_kw)


def parse_upgrade_unit(unit_id: str, body: dict) -> ConsumerUnit:
    """New details for a unit, including which zone it belongs to. Unlike a power plant's
    type, a unit's type only selects a demand curve, so nothing needs it frozen."""
    errors: list[str] = []
    _id(unit_id, 'unitId (in the path)', errors)
    zone_id = _id(body.get('zoneId'), 'zoneId', errors)
    name = _name(body, errors)
    profile = _profile(body, errors)
    capacity_kw = _capacity(body, errors)
    if errors:
        raise RequestValidationError(errors)
    return ConsumerUnit(unit_id, zone_id, name, profile, capacity_kw)


def zone_response(zone: Zone) -> dict:
    return {'zoneId': zone.zone_id, 'name': zone.name}


def unit_response(unit: ConsumerUnit, demand_kw: float) -> dict:
    """A unit with its demand at the latest simulated moment. That figure is computed
    live from the demand model, not read back: the demand cache only stores zone totals."""
    return {
        'unitId': unit.unit_id,
        'zoneId': unit.zone_id,
        'name': unit.name,
        'type': unit.type.name,
        'capacityKw': float(unit.capacity_kw),
        'demandKw': float(demand_kw),
    }


def demand_response(current: CurrentDemand, zones: list[Zone], units: list[ConsumerUnit]) -> dict:
    """Every configured zone joined against the latest cached demand.

    The cache holds only demand figures, so names and unit counts come from the
    configuration. A zone with nothing cached for it -- no tick yet, or added since the
    last one -- reports 0 rather than being left out or failing the request. A cached zone
    that has since been removed from the configuration is not listed, though ``totalKw`` is
    still the total of the tick it describes.
    """
    unit_counts = Counter(unit.zone_id for unit in units)
    return {
        'tick': current.tick,
        'simulatedTime': time_of_day(current.tick),
        'simulatedDay': day_number(current.tick),
        'updatedAt': current.updated_at.isoformat() if current.updated_at else None,
        'totalKw': float(current.total_kw),
        'zones': [
            {
                'zoneId': zone.zone_id,
                'name': zone.name,
                'unitCount': unit_counts[zone.zone_id],
                'demandKw': float(current.demand_by_zone_id.get(zone.zone_id, 0.0)),
            }
            for zone in zones
        ],
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
