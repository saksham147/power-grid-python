"""Exceptions this API raises; each maps to one status in ``errors.handle_api_errors``."""


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
