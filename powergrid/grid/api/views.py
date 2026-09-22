"""HTTP endpoints for the grid app, all under ``/api/grid/``:

* ``status/``               -- a point-in-time read of the clock and Grid's tracked
                                supply/demand totals.
* ``frequency-deviation/``  -- manually sets the deviation every subsequent tick
                                carries, switching automatic control off.

There is no start or stop endpoint: the tick loop runs from ``simulation``'s own
``runsimulation`` command at a fixed pace, so the only thing a caller can change here
is the grid condition every subsequent tick carries.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .. import wiring
from ..status import set_frequency_deviation, snapshot
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


@api_view('GET')
def status(request):
    return JsonResponse(dto.status_response(snapshot(wiring.state_tracker())))


@api_view('PUT')
def frequency_deviation(request):
    deviation_hz = dto.parse_frequency_deviation_request(_read_json_body(request))
    new_status = set_frequency_deviation(wiring.state_tracker(), deviation_hz)
    return JsonResponse(dto.status_response(new_status))
