"""HTTP endpoints for the distributor app, all under ``/api/distributor/``:

* ``status/``       -- system-wide supply/demand snapshot.
* ``zones/``        -- list zone capacities, or create/replace one (an upsert keyed by
                        the ``zoneId`` in the body).
* ``zones/<id>/``   -- update (an upsert) or delete a zone's capacity.

None of this touches the merge itself: ``DistributionService`` still allocates supply
purely by demand share, whatever capacity is assigned here.
"""
import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .. import models as orm
from .. import wiring
from . import dto
from .errors import handle_api_errors
from .exceptions import RequestValidationError, UnsupportedMediaTypeError


def api_view(*methods):
    """Method filter + uniform error mapping for a JSON API view.

    CSRF is exempt because this is a token-less machine API, not a browser form; the
    cross-site-POST hole that leaves is closed by ``_read_json_body`` insisting on a
    JSON content type.
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


def _updated_at(zone_id: str):
    return orm.ZoneCapacity.objects.filter(pk=zone_id).values_list('updated_at', flat=True).first()


def _updated_at_by_zone(zone_ids) -> dict:
    return dict(orm.ZoneCapacity.objects.filter(zone_id__in=zone_ids).values_list('zone_id', 'updated_at'))


@api_view('GET')
def status(request):
    return JsonResponse(dto.status_response(wiring.state_tracker()))


@api_view('GET', 'POST')
def zones(request):
    if request.method == 'POST':
        return _create_zone_capacity(request)
    return _list_zone_capacities(request)


def _list_zone_capacities(request):
    state = wiring.state_tracker()
    capacities = wiring.zone_capacity_service().list()
    updated_at_by_zone = _updated_at_by_zone([c.zone_id for c in capacities])
    return JsonResponse([
        dto.zone_capacity_response(c, state.demand_kw_for(c.zone_id), updated_at_by_zone.get(c.zone_id))
        for c in capacities
    ], safe=False)


def _create_zone_capacity(request):
    """An upsert keyed by the ``zoneId`` in the body. POST is not create-only here the
    way it is for plants or customer units: a capacity has no identity beyond its zone
    id, so "create" and "replace" are the same operation, and there is nothing a 409
    on a repeat call would protect."""
    zone_id, zone_name, capacity_kw = dto.parse_create_zone_capacity(_read_json_body(request))
    capacity = wiring.zone_capacity_service().upsert(zone_id, zone_name, capacity_kw)
    state = wiring.state_tracker()
    return JsonResponse(dto.zone_capacity_response(capacity, state.demand_kw_for(capacity.zone_id), _updated_at(capacity.zone_id)))


@api_view('PUT', 'DELETE')
def zone_detail(request, zone_id):
    if request.method == 'DELETE':
        return _delete_zone_capacity(zone_id)
    return _update_zone_capacity(request, zone_id)


def _update_zone_capacity(request, zone_id):
    """Renames/re-rates a zone's capacity. An upsert, not an update-or-404: a PUT to
    an id with no capacity yet creates one, so repeating a request is always safe."""
    zone_id, zone_name, capacity_kw = dto.parse_update_zone_capacity(zone_id, _read_json_body(request))
    capacity = wiring.zone_capacity_service().upsert(zone_id, zone_name, capacity_kw)
    state = wiring.state_tracker()
    return JsonResponse(dto.zone_capacity_response(capacity, state.demand_kw_for(capacity.zone_id), _updated_at(capacity.zone_id)))


def _delete_zone_capacity(zone_id):
    """Removes a zone's assigned capacity. Raises (mapped to 404) if none is assigned
    -- there being nothing to delete is the caller's mistake, unlike the idempotent
    upsert above."""
    wiring.zone_capacity_service().delete(zone_id)
    return HttpResponse(status=204)
