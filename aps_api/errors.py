"""API error contract (Phase 9 P3/P4).

A single structured error envelope (``{"error": {"code", "message",
"details"}}``) is returned for every non-2xx response so clients never have
to parse framework-specific shapes and never see stack traces or internal
implementation details.

Semantics preserved by the HTTP layer:

* valid request + feasible plan        -> 200 (schedule present)
* valid request + infeasible plan      -> 200 (schedule null, diagnostics)
* invalid request (bad JSON / schema)  -> 422 VALIDATION_ERROR
* invalid dataset document / objective -> 400 INVALID_PLANNING_REQUEST
* unexpected internal failure          -> 500 INTERNAL_ERROR (no details)

Solver infeasibility is deliberately NOT an HTTP error.
"""

from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from aps_api.schemas import ErrorResponse

VALIDATION_ERROR_CODE = "VALIDATION_ERROR"
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


class PlanningError(Exception):
    """A client-facing planning request error (mapped to HTTP 400)."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[List[Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def _error_payload(code: str, message: str, details: Optional[List[Any]] = None) -> Dict[str, Any]:
    return ErrorResponse(
        error={"code": code, "message": message, "details": details}
    ).model_dump(mode="json", exclude_none=True)


async def planning_error_handler(request: Request, exc: PlanningError) -> JSONResponse:
    """400 for a rejected planning request (invalid dataset/objective)."""
    return JSONResponse(
        status_code=400,
        content=_error_payload(exc.code, exc.message, exc.details),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 for a malformed request body / schema violation."""
    details = [
        {"loc": [str(part) for part in error.get("loc", [])],
         "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            VALIDATION_ERROR_CODE, "request validation failed", details
        ),
    )


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Envelope for framework-raised HTTP errors (404, 405, ...)."""
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(f"HTTP_{exc.status_code}", message),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """500 with no internal detail leaked to the client."""
    return JSONResponse(
        status_code=500,
        content=_error_payload(INTERNAL_ERROR_CODE, "internal server error"),
    )
