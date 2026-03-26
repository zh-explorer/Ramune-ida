"""Handlers for analysis operations (decompile, disasm, xrefs, etc.)."""

from __future__ import annotations

from typing import Any

from ramune_ida.protocol import ErrorCode
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


@handler("decompile")
def handle_decompile(params: dict[str, Any]) -> dict[str, Any]:
    import ida_hexrays

    func_ref = params.get("func")
    if not func_ref:
        raise HandlerError(ErrorCode.INVALID_PARAMS, "Missing required parameter: func")

    addr = _resolve_addr(func_ref)

    try:
        cfunc = ida_hexrays.decompile(addr)
    except ida_hexrays.DecompilationFailure as exc:
        raise HandlerError(ErrorCode.DECOMPILE_FAILED, f"Decompilation failed: {exc}")

    if cfunc is None:
        raise HandlerError(ErrorCode.DECOMPILE_FAILED, f"Decompilation returned None for {func_ref}")

    return {
        "addr": hex(addr),
        "code": str(cfunc),
    }


@handler("disasm")
def handle_disasm(params: dict[str, Any]) -> dict[str, Any]:
    import ida_ua
    import idc

    addr_ref = params.get("addr")
    if addr_ref is None:
        raise HandlerError(ErrorCode.INVALID_PARAMS, "Missing required parameter: addr")

    addr = _resolve_addr(str(addr_ref))
    count = params.get("count", 20)

    lines: list[dict[str, Any]] = []
    cur = addr
    for _ in range(count):
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
