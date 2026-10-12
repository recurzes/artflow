from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from shared.errors import Conflict, DomainError, Forbidden, NotFound

# Most specific class first; InvalidState is a Conflict.
_STATUS_CODES: tuple[tuple[type[DomainError], int], ...] = (
    (NotFound, status.HTTP_404_NOT_FOUND),
    (Forbidden, status.HTTP_403_FORBIDDEN),
    (Conflict, status.HTTP_409_CONFLICT),
)


def status_code_for(exc: DomainError) -> int:
    for error_type, code in _STATUS_CODES:
        if isinstance(exc, error_type):
            return code
    return status.HTTP_400_BAD_REQUEST


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=status_code_for(exc), content={"detail": exc.message})
