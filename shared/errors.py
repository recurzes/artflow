"""
Business-rule failures raised by the service layer.

Services raise these; they know nothing about HTTP. The API maps each class to a
status code in one place (api/errors.py), and the message is safe to show to users.
"""


class DomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    """The thing the caller referred to does not exist."""


class Forbidden(DomainError):
    """The caller is not allowed to do this."""


class Conflict(DomainError):
    """The request contradicts something that already exists."""


class InvalidState(Conflict):
    """The entity is not in a state that allows this action."""
