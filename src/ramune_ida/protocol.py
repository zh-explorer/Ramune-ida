"""Shared protocol types for IPC between Pool and Worker.

Includes message format (Request/Response), error codes, and task status.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import IntEnum, Enum
from typing import Any


# ---------------------------------------------------------------------------
# IPC error codes
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# IPC messages (Pool ↔ Worker, JSON line protocol over dedicated fd pair)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Request:
    """Message from Pool to Worker."""

    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }
        if self.timeout is not None:
            d["timeout"] = self.timeout
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Request:
        return cls(
            id=data["id"],
            method=data["method"],
            params=data.get("params", {}),
            timeout=data.get("timeout"),
        )


@dataclass(slots=True)
class Response:
    """Message from Worker to Pool."""

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


# ---------------------------------------------------------------------------
# Task status (shared across layers)
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
