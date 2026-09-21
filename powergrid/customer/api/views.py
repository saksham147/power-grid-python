"""HTTP endpoints for the customer app, all under ``/api/customer/``:

* ``zones/``  and ``zones/<id>/``  -- list, create, rename, delete zones.
* ``units/``  and ``units/<id>/``  -- list, create, edit, delete consumer units.
* ``demand/``                      -- the live per-zone demand picture.

Every change takes effect on the very next demand tick, because the tick reads zones and
units fresh from storage each time rather than freezing them at startup.
"""
import json

from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from simulation.clock import day_number, is_weekend, minute_of_day

from .. import wiring
from ..domain import Season, demand_kw
from . import dto
from .errors import handle_api_errors
from .exceptions import ConflictError, RequestValidationError, UnsupportedMediaTypeError


def api_view(*methods):
    """Method filter + uniform error mapping for a JSON API view.

    CSRF is exempt because this is a token-less machine API, not a browser form; the
    cross-site-POST hole that leaves is closed by ``_read_json_body`` insisting on a JSON
    content type.
    """

    def decorator(view):
        return csrf_exempt(require_http_methods(methods)(handle_api_errors(view)))

    return decorator


def _read_json_body(request) -> dict:
    if request.content_type != 'application/json':
        raise UnsupportedMediaTypeError(
            f"Content-Type must be application/json, got {request.content_type or 'none'!r}")
    body = json.loads(request.body)
    if not isinstance(body, dict):
        raise RequestValidationError(['body: must be a JSON object'])
    return body


def _demand_at_latest_tick():
    """A function giving any unit's demand at the latest simulated moment (tick 0, a
    Monday midnight in spring, before the first tick has run)."""
    tick = wiring.demand_state().current().tick
    minute, weekend, season = minute_of_day(tick), is_weekend(tick), Season.of(day_number(tick))
    return lambda unit: demand_kw(unit, minute, weekend, season)


# ---- zones ------------------------------------------------------------------------------


@api_view('GET', 'POST')
def zones(request):
    if request.method == 'POST':
        return _create_zone(request)
    return JsonResponse([dto.zone_response(zone) for zone in wiring.zones().find_all()], safe=False)


def _create_zone(request):
    zone = dto.parse_create_zone(_read_json_body(request))

    repository = wiring.zones()
    # A create that silently replaced an existing zone would let a mistyped id overwrite
    # another zone's name; renaming is what PUT is for.
    if any(existing.zone_id == zone.zone_id for existing in repository.find_all()):
        raise ConflictError(f'A zone with id {zone.zone_id} already exists; use PUT to rename it')
    repository.save(zone)

    response = JsonResponse(dto.zone_response(zone), status=201)
    response['Location'] = reverse('customer-zone-detail', args=[zone.zone_id])
    return response


@api_view('PUT', 'DELETE')
def zone_detail(request, zone_id):
    if request.method == 'DELETE':
        return _delete_zone(zone_id)
    return _upsert_zone(request, zone_id)


def _upsert_zone(request, zone_id):
    """Renames a zone. An upsert rather than update-or-404: a PUT to an id that does not
    exist yet creates it, so repeating a request is always safe."""
    zone = dto.parse_upgrade_zone(zone_id, _read_json_body(request))
    wiring.zones().save(zone)
    return JsonResponse(dto.zone_response(zone))


def _delete_zone(zone_id):
    """Removes a zone and, since a unit without a zone is meaningless, its units.

    Units first. If the process dies between the two calls, retrying the delete finishes
    the job; the other order could strand units that keep contributing demand to a zone
    that no longer exists. Deleting an id that is not there is a no-op, so a retry after
    success is also safe.
    """
    wiring.units().delete_by_zone_id(zone_id)
    wiring.zones().delete(zone_id)
    return HttpResponse(status=204)


# ---- units ------------------------------------------------------------------------------


@api_view('GET', 'POST')
def units(request):
    if request.method == 'POST':
        return _create_unit(request)
    demand_of = _demand_at_latest_tick()
    return JsonResponse([dto.unit_response(unit, demand_of(unit)) for unit in wiring.units().find_all()], safe=False)


def _create_unit(request):
    unit = dto.parse_create_unit(_read_json_body(request))

    repository = wiring.units()
    if any(existing.unit_id == unit.unit_id for existing in repository.find_all()):
        raise ConflictError(f'A unit with id {unit.unit_id} already exists; use PUT to change it')
    repository.save(unit)

    response = JsonResponse(dto.unit_response(unit, _demand_at_latest_tick()(unit)), status=201)
    response['Location'] = reverse('customer-unit-detail', args=[unit.unit_id])
    return response


@api_view('PUT', 'DELETE')
def unit_detail(request, unit_id):
    if request.method == 'DELETE':
        wiring.units().delete(unit_id)
        return HttpResponse(status=204)

    unit = dto.parse_upgrade_unit(unit_id, _read_json_body(request))
    wiring.units().save(unit)
    return JsonResponse(dto.unit_response(unit, _demand_at_latest_tick()(unit)))


# ---- demand -----------------------------------------------------------------------------


@api_view('GET')
def demand(request):
    """The whole picture as of the latest tick: every configured zone, plus the context
    they share. Tick 0 with an empty ``updatedAt`` means no tick has run yet."""
    current = wiring.demand_state().current()
    return JsonResponse(dto.demand_response(current, wiring.zones().find_all(), wiring.units().find_all()))
