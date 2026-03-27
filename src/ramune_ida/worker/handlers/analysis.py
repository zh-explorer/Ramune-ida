"""Handlers for analysis operations (decompile, disasm, xrefs, etc.)."""

from __future__ import annotations

from typing import Any

from ramune_ida.commands import Decompile, Disasm
from ramune_ida.protocol import ErrorCode, Method
from ramune_ida.worker.dispatch import handler, HandlerError


def _resolve_addr(func: str) -> int:
    """Resolve a function name or hex address string to an integer address."""
    import ida_name

    if func.startswith("0x") or func.startswith("0X"):
        try:
            return int(func, 16)
        except ValueError:
            pass

    try:
        return int(func)
    except ValueError:
        pass

    addr = ida_name.get_name_ea(0, func)
    if addr == 0xFFFFFFFFFFFFFFFF:  # BADADDR
        raise HandlerError(ErrorCode.FUNCTION_NOT_FOUND, f"Cannot resolve: {func}")
    return addr


@handler(Method.DECOMPILE)
def handle_decompile(cmd: Decompile) -> dict[str, Any]:
    import ida_hexrays

    if not cmd.func:
        raise HandlerError(ErrorCode.INVALID_PARAMS, "Missing required parameter: func")

    addr = _resolve_addr(cmd.func)

    try:
        cfunc = ida_hexrays.decompile(addr)
    except ida_hexrays.DecompilationFailure as exc:
        raise HandlerError(ErrorCode.DECOMPILE_FAILED, f"Decompilation failed: {exc}")

    if cfunc is None:
        raise HandlerError(ErrorCode.DECOMPILE_FAILED, f"Decompilation returned None for {cmd.func}")

    return {
        "addr": hex(addr),
        "code": str(cfunc),
    }


@handler(Method.DISASM)
def handle_disasm(cmd: Disasm) -> dict[str, Any]:
    import ida_ua
    import idc

    if not cmd.addr:
        raise HandlerError(ErrorCode.INVALID_PARAMS, "Missing required parameter: addr")

    addr = _resolve_addr(cmd.addr)

    lines: list[dict[str, Any]] = []
    cur = addr
    for _ in range(cmd.count):
        insn = ida_ua.insn_t()
        length = ida_ua.decode_insn(insn, cur)
        if length == 0:
            break
        lines.append({
            "addr": hex(cur),
            "disasm": idc.GetDisasm(cur),
            "size": length,
        })
        cur += length

    return {"start_addr": hex(addr), "lines": lines}
