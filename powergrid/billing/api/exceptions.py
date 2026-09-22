"""Exceptions this API raises that aren't already defined at the use-case level;
each maps to one status in ``errors.handle_api_errors``.

``billing.InsufficientFundsException`` (402) and ``billing.PlantTypeLockedException``
(403) are handled directly from ``..billing``; these two cover request handling
itself, and ``ZoneNotBilledException`` covers the one read-side domain failure.
"""


class UnsupportedMediaTypeError(Exception):
    """A request body that is not JSON. Mapped to 415.

    Also what stops a web page on another origin from writing to this (unauthenticated)
    API with a "simple" cross-site POST: browsers only send ``application/json`` after
    a CORS preflight, which nothing here answers.
    """


class RequestValidationError(ValueError):
    """The request body failed validation. Mapped to 400, with one message per bad
    field in ``details``."""

    def __init__(self, details: list[str]):
        super().__init__('Request body failed validation')
        self.details = details


class ZoneNotBilledException(Exception):
    """No wallet exists yet for this zone -- it has never been billed for a tick."""

    def __init__(self, zone_id: str):
        super().__init__(f"No wallet for zone {zone_id} -- it hasn't been billed for a tick yet.")
