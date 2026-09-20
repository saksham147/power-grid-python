"""Exceptions Producer's HTTP API raises, ported from ``Producer.api`` (Java).

Each maps to one HTTP status in ``errors.handle_api_errors``.
"""


class PlantNotFoundException(Exception):
    """No plant with the requested id. Mapped to 404."""

    def __init__(self, plant_id):
        super().__init__(f'No plant with id {plant_id}')


class UnsupportedMediaTypeError(Exception):
    """A request body that is not JSON. Mapped to 415.

    Also what stops a web page on another origin from writing to this (unauthenticated)
    API with a "simple" cross-site POST: browsers only send ``application/json``
    after a CORS preflight, which nothing here answers.
    """


class RequestValidationError(ValueError):
    """The request body failed validation. Mapped to 400 with one message per bad
    field in ``details``, like Spring's ``MethodArgumentNotValidException``."""

    def __init__(self, details: list[str]):
        super().__init__('Request body failed validation')
        self.details = details
