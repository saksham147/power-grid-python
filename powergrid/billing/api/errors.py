"""Turns the exceptions this API raises into uniform error responses.

Without it every failure would surface as a bare 500 for cases that are plainly not a
bug: a malformed body, an unbilled zone, a locked plant type, an unaffordable spend.
"""
import functools
import logging
from http import HTTPStatus

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import JsonResponse

from ..billing import InsufficientFundsException, PlantTypeLockedException
from . import dto
from .exceptions import RequestValidationError, UnsupportedMediaTypeError, ZoneNotBilledException

logger = logging.getLogger(__name__)


def handle_api_errors(view):
    """Wraps a view so the exceptions it can raise become error responses.

    Only ``ValueError`` (which covers malformed JSON) and the domain's own
    ``ValidationError`` are treated as the caller's fault. Anything else is a bug and
    is left to surface as a 500 rather than be dressed up as a 400.
    """

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except UnsupportedMediaTypeError as e:
            return _respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, str(e))
        except ZoneNotBilledException as e:
            return _respond(HTTPStatus.NOT_FOUND, str(e))
        # 402: the one HTTP status whose name already says exactly what went wrong.
        except InsufficientFundsException as e:
            return _respond(HTTPStatus.PAYMENT_REQUIRED, str(e))
        # 403: well-formed request, simply not yet permitted -- distinct from 402's
        # "permitted, but can't afford it".
        except PlantTypeLockedException as e:
            return _respond(HTTPStatus.FORBIDDEN, str(e))
        except RequestValidationError as e:
            return _respond(HTTPStatus.BAD_REQUEST, str(e), e.details)
        except DjangoValidationError as e:
            return _respond(HTTPStatus.BAD_REQUEST, '; '.join(e.messages))
        except ValueError as e:
            return _respond(HTTPStatus.BAD_REQUEST, str(e))

    return wrapper


def _respond(status: HTTPStatus, message: str, details: list[str] | None = None):
    return JsonResponse(dto.api_error(status, message, details), status=status.value)
