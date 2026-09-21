"""Turns the exceptions the customer API raises into uniform error responses.

Without it every failure would surface as a bare 500, for cases that are plainly not a
bug: a malformed body, an id that is already taken, storage that is briefly unreachable.
"""
import functools
import logging
from http import HTTPStatus

import redis
from django.http import JsonResponse

from . import dto
from .exceptions import ConflictError, RequestValidationError, UnsupportedMediaTypeError

logger = logging.getLogger(__name__)


def handle_api_errors(view):
    """Wraps a view so the exceptions it can raise become error responses.

    Only ``ValueError`` (which covers malformed JSON and the domain's own validation) is
    treated as the caller's fault. Anything unexpected is a bug and is left to surface as
    a 500 rather than be dressed up as a 400.
    """

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except UnsupportedMediaTypeError as e:
            return _respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, str(e))
        except ConflictError as e:
            return _respond(HTTPStatus.CONFLICT, str(e))
        except RequestValidationError as e:
            return _respond(HTTPStatus.BAD_REQUEST, str(e), e.details)
        except redis.RedisError:
            # Reads raise when storage cannot be reached instead of answering with an
            # empty fleet, so the honest response is "try again shortly". The cause is
            # logged; the body does not leak connection details.
            logger.error('Storage unavailable while serving %s %s', request.method, request.path, exc_info=True)
            return _respond(HTTPStatus.SERVICE_UNAVAILABLE, 'Storage is unavailable; try again shortly')
        except ValueError as e:
            return _respond(HTTPStatus.BAD_REQUEST, str(e))

    return wrapper


def _respond(status: HTTPStatus, message: str, details: list[str] | None = None):
    return JsonResponse(dto.api_error(status, message, details), status=status.value)
