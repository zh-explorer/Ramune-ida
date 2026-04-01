"""Worker-side handlers for annotation tools.

Each function receives ``params: dict`` and returns ``dict``.
IDA modules are imported inside function bodies so the module
itself can be imported safely without IDA (e.g. during --list-plugins).

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

from typing import Any

from ramune_ida.core import ToolError, resolve_addr


def rename(params: dict[str, Any]) -> dict[str, Any]:
    """Rename a function, global, or local variable.

    Routing:
      * ``func`` + ``var`` provided  → local variable rename
      * ``addr`` provided            → function / global rename
    """
    new_name = params.get("new_name", "")
    if not new_name:
        raise ToolError(-4, "Missing required parameter: new_name")

    func_str = params.get("func", "")
    var_str = params.get("var", "")

    if func_str and var_str:
        return _rename_local(func_str, var_str, new_name)

    addr_str = params.get("addr", "")
    if addr_str:
        return _rename_global_or_func(addr_str, new_name)

    raise ToolError(
        -4,
        "Provide addr+new_name (function/global) "
        "or func+var+new_name (local variable)",
    )


def _rename_global_or_func(addr_str: str, new_name: str) -> dict[str, Any]:
    """Rename a function or global via ``idaapi.set_name``."""
    import idaapi

    ea = resolve_addr(addr_str)
    old_name = idaapi.get_name(ea) or ""

    conflict_ea = idaapi.get_name_ea(idaapi.BADADDR, new_name)
    if conflict_ea != idaapi.BADADDR and conflict_ea != ea:
        raise ToolError(
            -14,
            "get_name_ea(BADADDR, '%s') returned %s, name conflict" % (new_name, hex(conflict_ea)),
        )

    ok = idaapi.set_name(ea, new_name, idaapi.SN_CHECK)
    if not ok:
        raise ToolError(-14, "set_name(%s, '%s', SN_CHECK) returned False" % (hex(ea), new_name))

    target_type = "function" if idaapi.get_func(ea) is not None else "global"
    return {
        "addr": hex(ea),
        "old_name": old_name,
        "new_name": new_name,
        "type": target_type,
    }


def _rename_local(
    func_str: str, var_name: str, new_name: str
) -> dict[str, Any]:
    """Rename a local variable / argument via ``ida_hexrays.rename_lvar``."""
    import idaapi
    import ida_funcs
    import ida_hexrays

    ea = resolve_addr(func_str)
    func = ida_funcs.get_func(ea)
    if func is None:
        raise ToolError(-12, "get_func(%s) returned None" % hex(ea))

    ok = ida_hexrays.rename_lvar(func.start_ea, var_name, new_name)
    if not ok:
        raise ToolError(
            -14,
            "rename_lvar(%s, '%s', '%s') returned False"
            % (hex(func.start_ea), var_name, new_name),
        )

    return {
        "func": hex(func.start_ea),
        "func_name": ida_funcs.get_func_name(func.start_ea),
        "old_name": var_name,
        "new_name": new_name,
        "type": "local",
    }


def get_comment(params: dict[str, Any]) -> dict[str, Any]:
    """Read comment at addr (disasm) or func (function header)."""
    import idc
    import ida_funcs

    func_str = params.get("func", "")
    addr_str = params.get("addr", "")

    if func_str:
        ea = resolve_addr(func_str)
        func = ida_funcs.get_func(ea)
        if func is None:
            raise ToolError(-12, "get_func(%s) returned None" % hex(ea))
        regular = idc.get_func_cmt(func.start_ea, 0) or ""
        repeatable = idc.get_func_cmt(func.start_ea, 1) or ""
        result: dict[str, Any] = {
            "func": hex(func.start_ea),
            "name": ida_funcs.get_func_name(func.start_ea),
        }
        if regular:
            result["comment"] = regular
        if repeatable:
            result["repeatable"] = repeatable
        if not regular and not repeatable:
            result["comment"] = None
        return result

    if addr_str:
        ea = resolve_addr(addr_str)
        regular = idc.get_cmt(ea, 0)
        repeatable = idc.get_cmt(ea, 1)
        result = {"addr": hex(ea)}
        if regular:
            result["comment"] = regular
        if repeatable:
            result["repeatable"] = repeatable
        if not regular and not repeatable:
            result["comment"] = None
        return result

    raise ToolError(
        -4,
        "Provide addr (disassembly comment) or func (function header comment)",
    )


def set_comment(params: dict[str, Any]) -> dict[str, Any]:
    """Set comment at addr (disasm) or func (function header)."""
    import idc
    import ida_funcs

    comment = params.get("comment")
    if comment is None:
        raise ToolError(-4, "Missing required parameter: comment")

    func_str = params.get("func", "")
    addr_str = params.get("addr", "")

    if func_str:
        ea = resolve_addr(func_str)
        func = ida_funcs.get_func(ea)
        if func is None:
            raise ToolError(-12, "get_func(%s) returned None" % hex(ea))
        ok = idc.set_func_cmt(func.start_ea, comment, 0)
        if not ok:
            raise ToolError(-14, "set_func_cmt(%s, ..., 0) returned False" % hex(func.start_ea))
        return {
            "func": hex(func.start_ea),
            "name": ida_funcs.get_func_name(func.start_ea),
            "comment": comment or None,
        }

    if addr_str:
        ea = resolve_addr(addr_str)
        ok = idc.set_cmt(ea, comment, 0)
        if not ok:
            raise ToolError(-14, "set_cmt(%s, ..., 0) returned False" % hex(ea))
        return {"addr": hex(ea), "comment": comment or None}

    raise ToolError(
        -4,
        "Provide addr+comment (disassembly) or func+comment (function header)",
    )
