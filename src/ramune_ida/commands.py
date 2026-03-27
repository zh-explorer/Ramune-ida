"""Typed command definitions for IPC between Server and Worker.

Each ``Command`` subclass is self-contained: it declares the IPC
method, the parameters (as dataclass fields), and a nested ``Result``
class that describes the expected response.

Use ``COMMAND_TYPES`` or ``command_from_params()`` to reconstruct a
typed Command from wire-format data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields as dc_fields
from typing import Any, ClassVar

from ramune_ida.protocol import Method, Request


# ---------------------------------------------------------------------------
# Command base
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Command:
    """Base class for all IPC commands.

    Subclasses declare ``method: ClassVar[Method]`` and typed fields
    for parameters.  Each subclass also contains a nested ``Result``
    dataclass that mirrors the expected response payload.
    """

    method: ClassVar[Method]

    def to_params(self) -> dict[str, Any]:
        return asdict(self) if dc_fields(self) else {}

    def to_request(self, req_id: str) -> Request:
        return Request(id=req_id, method=self.method.value, params=self.to_params())


# ---------------------------------------------------------------------------
# Lifecycle commands
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Ping(Command):
    method: ClassVar[Method] = Method.PING

    @dataclass(slots=True)
    class Result:
        status: str = "pong"

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)


@dataclass(slots=True)
class Shutdown(Command):
    method: ClassVar[Method] = Method.SHUTDOWN

    @dataclass(slots=True)
    class Result:
        status: str = "shutdown"

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)


# ---------------------------------------------------------------------------
# Database commands
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OpenDatabase(Command):
    method: ClassVar[Method] = Method.OPEN_DATABASE
    path: str = ""
    auto_analysis: bool = True

    @dataclass(slots=True)
    class Result:
        path: str = ""

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)


@dataclass(slots=True)
class CloseDatabase(Command):
    method: ClassVar[Method] = Method.CLOSE_DATABASE
    save: bool = True

    @dataclass(slots=True)
    class Result:
        def to_dict(self) -> dict[str, Any]:
            return {}


@dataclass(slots=True)
class SaveDatabase(Command):
    method: ClassVar[Method] = Method.SAVE_DATABASE

    @dataclass(slots=True)
    class Result:
        def to_dict(self) -> dict[str, Any]:
            return {}


# ---------------------------------------------------------------------------
# Analysis commands
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Decompile(Command):
    method: ClassVar[Method] = Method.DECOMPILE
    func: str = ""

    @dataclass(slots=True)
    class Result:
        addr: str = ""
        code: str = ""

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)


@dataclass(slots=True)
class Disasm(Command):
    method: ClassVar[Method] = Method.DISASM
    addr: str = ""
    count: int = 20

    @dataclass(slots=True)
    class Result:
        start_addr: str = ""
        lines: list[dict[str, Any]] = field(default_factory=list)

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMAND_TYPES: dict[str, type[Command]] = {
    cls.method.value: cls  # type: ignore[attr-defined]
    for cls in (
        Ping, Shutdown,
        OpenDatabase, CloseDatabase, SaveDatabase,
        Decompile, Disasm,
    )
}


def command_from_params(method: str, params: dict[str, Any]) -> Command:
    """Reconstruct a typed Command from a method name and params dict."""
    cls = COMMAND_TYPES.get(method)
    if cls is None:
        raise ValueError(f"Unknown method: {method}")
    return cls(**params) if params else cls()
