"""Handlers for IDA database operations (open, close, save)."""

from __future__ import annotations

import idapro

from ramune_ida.commands import CloseDatabase, OpenDatabase, SaveDatabase
from ramune_ida.protocol import ErrorCode, Method
from ramune_ida.worker.dispatch import handler, HandlerError


@handler(Method.OPEN_DATABASE)
def handle_open_database(cmd: OpenDatabase) -> dict[str, str]:
    if not cmd.path:
        raise HandlerError(ErrorCode.INVALID_PARAMS, "Missing required parameter: path")

    rc = idapro.open_database(cmd.path, cmd.auto_analysis)
    if rc != 0:
        raise HandlerError(
            ErrorCode.DATABASE_OPEN_FAILED,
            f"open_database returned error code {rc} for {cmd.path}",
        )

    return {"path": cmd.path}


@handler(Method.CLOSE_DATABASE)
def handle_close_database(cmd: CloseDatabase) -> dict:
    idapro.close_database(save=cmd.save)
    return {}


@handler(Method.SAVE_DATABASE)
def handle_save_database(cmd: SaveDatabase) -> dict:
    import ida_loader
    ida_loader.save_database("", 0)
    return {}
