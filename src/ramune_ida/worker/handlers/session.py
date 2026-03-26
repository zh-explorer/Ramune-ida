"""Handlers for IDA database operations (open, close, save)."""

from __future__ import annotations

from typing import Any

import idapro

from ramune_ida.protocol import ErrorCode
from ramune_ida.worker.dispatch import handler, HandlerError


@handler("open_database")
def handle_open_database(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if not path:
        raise HandlerError(ErrorCode.INVALID_PARAMS, "Missing required parameter: path")

    auto_analysis = params.get("auto_analysis", True)

    rc = idapro.open_database(path, auto_analysis)
    if rc != 0:
        raise HandlerError(
            ErrorCode.DATABASE_OPEN_FAILED,
            f"open_database returned error code {rc} for {path}",
        )

    return {"path": path}


@handler("close_database")
def handle_close_database(params: dict[str, Any]) -> dict[str, Any]:
    save = params.get("save", True)
    idapro.close_database(save=save)
    return {}


@handler("save_database")
def handle_save_database(params: dict[str, Any]) -> dict[str, Any]:
    import ida_loader
    ida_loader.save_database("", 0)
    return {}
