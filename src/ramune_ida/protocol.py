"""IPC protocol between MCP Server and Worker processes.

JSON line protocol over stdin/stdout pipes.
Each message is a single line of JSON terminated by newline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Any


class ErrorCode(IntEnum):
    UNKNOWN = -1
    INVALID_REQUEST = -2
    METHOD_NOT_FOUND = -3
    INVALID_PARAMS = -4
    INTERNAL_ERROR = -5
    DATABASE_NOT_OPEN = -10
    DATABASE_OPEN_FAILED = -11
    FUNCTION_NOT_FOUND = -12
    DECOMPILE_FAILED = -13
    TIMEOUT = -14
    PYTHON_EXEC_ERROR = -15


@dataclass(slots=True)
class Request:
    """Message from MCP Server to Worker."""

    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "method": self.method, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Request:
        return cls(
            id=data["id"],
            method=data["method"],
            params=data.get("params", {}),
        )


@dataclass(slots=True)
class Response:
    """Message from Worker to MCP Server."""

    id: str
    result: Any = None
    error: ErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id}
        if self.error is not None:
            d["error"] = asdict(self.error)
        else:
            d["result"] = self.result
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Response:
        error_data = data.get("error")
        return cls(
            id=data["id"],
            result=data.get("result"),
            error=ErrorInfo(**error_data) if error_data else None,
        )

    @classmethod
    def ok(cls, req_id: str, result: Any = None) -> Response:
        return cls(id=req_id, result=result)

    @classmethod
    def fail(cls, req_id: str, code: ErrorCode, message: str) -> Response:
        return cls(id=req_id, error=ErrorInfo(code=int(code), message=message))


@dataclass(slots=True)
class ErrorInfo:
    code: int
    message: str
