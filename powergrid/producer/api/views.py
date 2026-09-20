"""HTTP endpoints for Producer's fleet, generation history and status.

Ported from Power-Grid's ``Producer.api`` (Java): ``PowerPlantController``,
``GenerationHistoryController`` and ``SimulationController``. Plain Django views, all
under ``/api/producer/`` (see ``producer.urls``).

Not ported: ``GET plants/{id}/forecast`` and the ``producer.plants`` roster events it
sits beside. The roster feeds Billing, and neither has a consumer here yet.
"""
import datetime
import json

from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from producer import history
from producer.models import GenerationRecord, PowerPlant
from simulation.clock import REAL_TIME_PER_TICK_SECONDS, day_number, time_of_day
from simulation.models import SimulationState

from . import dto
from .errors import handle_api_errors
from .exceptions import PlantNotFoundException, RequestValidationError, UnsupportedMediaTypeError

# One simulated day of raw ticks.
DEFAULT_HISTORY_LIMIT = 288
# A week of raw history is ~120k rows per plant; nothing should pull that in one response.
MAX_HISTORY_LIMIT = 5000
DEFAULT_HISTORY_WINDOW = datetime.timedelta(hours=24)

# What an upgrade may write. Never energy_mwh: the tick adds to it from a read it took
# earlier, so a whole-row save from here could overwrite a fresh total with a stale
# one. With these lists the two only ever share current_output_mw, which the next tick
# recomputes anyway. Likewise the tick's own write-back never touches ratings or active.
_UPGRADE_FIELDS = ['name', 'capacity_mw', 'min_output_mw', 'base_output_mw', 'current_output_mw']
_ACTIVE_FIELDS = ['active']


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


def _get_plant_or_404(plant_id: int) -> PowerPlant:
    try:
        return PowerPlant.objects.get(pk=plant_id)
    except PowerPlant.DoesNotExist:
        raise PlantNotFoundException(plant_id)


def _bool_param(request, name: str, default: bool) -> bool:
    value = request.GET.get(name)
    if value is None:
        return default
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    raise ValueError(f"{name} must be 'true' or 'false', got {value!r}")


def _int_param(request, name: str, default: int) -> int:
    value = request.GET.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f'{name} must be an integer, got {value!r}')


def _instant_param(request, name: str) -> datetime.datetime | None:
    value = request.GET.get(name)
    if value is None:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{name} must be an ISO-8601 instant such as 2026-01-01T00:00:00Z, got {value!r}')
    return parsed.replace(tzinfo=datetime.timezone.utc) if timezone.is_naive(parsed) else parsed


@api_view('GET', 'POST')
def plants(request):
    if request.method == 'POST':
        return _create_plant(request)
    return _list_plants(request)


def _list_plants(request):
    """``activeOnly`` restricts to plants that take part in a tick, which is what makes
    a listing comparable against a tick's event count."""
    queryset = PowerPlant.objects.order_by('id')
    if _bool_param(request, 'activeOnly', False):
        queryset = queryset.filter(active=True)
    return JsonResponse([dto.plant_response(plant) for plant in queryset], safe=False)


def _create_plant(request):
    plant = PowerPlant(**dto.parse_create_plant_request(_read_json_body(request)))
    plant.save()

    response = JsonResponse(dto.plant_response(plant), status=201)
    response['Location'] = reverse('producer-plant-detail', args=[plant.id])
    return response


@api_view('GET', 'PUT', 'DELETE')
def plant_detail(request, plant_id):
    if request.method == 'PUT':
        return _upgrade_plant(request, plant_id)
    if request.method == 'DELETE':
        return _delete_plant(plant_id)
    return JsonResponse(dto.plant_response(_get_plant_or_404(plant_id)))


def _upgrade_plant(request, plant_id):
    """Re-rates a unit. PUT rather than PATCH because every field is required: a
    partial upgrade would need per-field null handling to say what a second call
    already can. All ratings apply together through ``PowerPlant.upgrade``, so a plant
    is never left halfway through a re-rating."""
    fields = dto.parse_upgrade_plant_request(_read_json_body(request))

    plant = _get_plant_or_404(plant_id)
    plant.upgrade(**fields)
    plant.save(update_fields=_UPGRADE_FIELDS)
    return JsonResponse(dto.plant_response(plant))


def _delete_plant(plant_id):
    """Removes a unit permanently; deactivating via ``PATCH .../active/`` is the
    reversible option. History already written for the plant is kept -- it carries its
    own id and type and outlives the plant."""
    _get_plant_or_404(plant_id).delete()
    return HttpResponse(status=204)


@api_view('PATCH')
def plant_active(request, plant_id):
    """Takes a plant in or out of service -- the way to watch total generation move
    without touching any plant's ratings."""
    active = dto.parse_update_active_request(_read_json_body(request))

    plant = _get_plant_or_404(plant_id)
    plant.active = active
    plant.save(update_fields=_ACTIVE_FIELDS)
    return JsonResponse(dto.plant_response(plant))


@api_view('GET')
def plant_history(request, plant_id):
    """A plant's generation history: raw per-tick points for the last day, rolled-up
    per-minute points beyond, newest first.

    ``from`` (inclusive) and ``to`` (exclusive) are ISO-8601 instants -- write the
    offset as ``Z`` or ``%2B00:00``, since a bare ``+`` in a query string decodes to a
    space. They default to 24 hours before ``to``, and ``to`` to now.

    A deleted plant's id still returns its history, because history outlives the
    plant. The consequence is that an id that never existed returns an empty list
    rather than 404 -- no table is left to say whether it ever did.
    """
    limit = _int_param(request, 'limit', DEFAULT_HISTORY_LIMIT)
    if not 1 <= limit <= MAX_HISTORY_LIMIT:
        raise ValueError(f'limit must be between 1 and {MAX_HISTORY_LIMIT}, got {limit}')

    end = _instant_param(request, 'to') or timezone.now()
    start = _instant_param(request, 'from') or end - DEFAULT_HISTORY_WINDOW
    if not start < end:
        raise ValueError(f'from ({start.isoformat()}) must be before to ({end.isoformat()})')

    points = history.history(plant_id, start, end, limit)
    return JsonResponse([dto.history_point_response(point) for point in points], safe=False)


@api_view('GET')
def status(request):
    """Point-in-time view of the fleet against the shared simulation clock, ported
    from ``SimulationController``.

    There is no start or stop: the loop runs from ``manage.py runsimulation`` at a
    fixed pace, and the grid condition (frequency deviation) is set on the shared
    ``simulation`` app, not here. ``fleetEnergyMwh`` is each plant's lifetime total
    summed, so it survives a restart.
    """
    state = SimulationState.load()
    latest = GenerationRecord.objects.filter(tick_number=state.current_tick)

    return JsonResponse({
        'tickNumber': state.current_tick,
        'simulatedTime': time_of_day(state.current_tick),
        'simulatedDay': day_number(state.current_tick),
        'tickIntervalSeconds': REAL_TIME_PER_TICK_SECONDS,
        'frequencyDeviation': state.frequency_deviation_hz,
        'plantCount': PowerPlant.objects.filter(active=True).count(),
        'lastEventCount': latest.count(),
        'fleetOutputMw': latest.aggregate(total=Sum('output_mw'))['total'] or 0.0,
        'fleetEnergyMwh': PowerPlant.objects.aggregate(total=Sum('energy_mwh'))['total'] or 0.0,
    })
