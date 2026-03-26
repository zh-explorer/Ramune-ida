"""Command dispatch: routes method names to handler functions."""

from __future__ import annotations

from typing import Any, Callable

from ramune_ida.protocol import Request, Response, ErrorCode

Handler = Callable[[dict[str, Any]], Any]

_HANDLERS: dict[str, Handler] = {}


def handler(method: str) -> Callable[[Handler], Handler]:
    """Register a function as the handler for *method*."""
    def decorator(fn: Handler) -> Handler:
        _HANDLERS[method] = fn
        return fn
    return decorator


def dispatch(request: Request) -> Response:
    """Look up the handler for *request.method* and call it."""
    fn = _HANDLERS.get(request.method)
    if fn is None:
        return Response.fail(
            request.id,
            ErrorCode.METHOD_NOT_FOUND,
            f"Unknown method: {request.method}",
        )
    try:
        result = fn(request.params)
        return Response.ok(request.id, result)
    except HandlerError as exc:
        return Response.fail(request.id, exc.code, str(exc))
    except Exception as exc:
        return Response.fail(
            request.id,
            ErrorCode.INTERNAL_ERROR,
            f"{type(exc).__name__}: {exc}",
        )


class HandlerError(Exception):
    """Raised by handlers to return a structured error."""

    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
