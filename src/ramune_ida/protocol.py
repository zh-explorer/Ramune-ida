"""Shared protocol types for IPC between Server and Worker.

This module defines the **wire format** and **shared enums**:

- ``Method`` — central registry of every IPC method name
- ``Request`` / ``Response`` — wire-format messages
- ``ErrorCode`` / ``ErrorInfo`` — structured errors
- ``TaskStatus`` — lifecycle states for async tasks

Typed command definitions (parameters + result) live in
:mod:`ramune_ida.commands`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


@dataclass(slots=True)
class ErrorInfo:
    code: int
    message: str


# ---------------------------------------------------------------------------
# Method enum — central registry of every IPC method
# ---------------------------------------------------------------------------

class Method(str, Enum):
    PING = "ping"
    SHUTDOWN = "shutdown"
    OPEN_DATABASE = "open_database"
    CLOSE_DATABASE = "close_database"
    SAVE_DATABASE = "save_database"
    DECOMPILE = "decompile"
    DISASM = "disasm"


# ---------------------------------------------------------------------------
# IPC messages (Server ↔ Worker, JSON line protocol over socketpair)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Request:
    """Wire-format message from Server to Worker."""

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
    """Wire-format message from Worker to Server."""

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


# ---------------------------------------------------------------------------
# Task status (shared across layers)
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
