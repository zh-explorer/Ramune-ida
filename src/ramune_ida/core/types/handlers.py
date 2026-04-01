"""Worker-side handlers for type system tools.

Each function receives ``params: dict`` and returns ``dict``.
IDA modules are imported inside function bodies so the module
itself can be imported safely without IDA (e.g. during --list-plugins).

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

from typing import Any

from ramune_ida.core import ToolError, resolve_addr


def _parse_tinfo(text: str) -> Any:
    """Parse a C type string into ``tinfo_t``.

    Tries three strategies so callers can pass natural type text
    like ``"int"``, ``"MyStruct *"``, or ``"int (*)(void *, int)"``.
    """
    import ida_typeinf

    text = text.strip().rstrip(";").strip()
    if not text:
        raise ToolError(-4, "Type text is empty")

    til = ida_typeinf.get_idati()

    # 1. Named type in local type library (struct/enum/typedef names)
    tif = ida_typeinf.tinfo_t()
    if tif.get_named_type(til, text):
        return tif

    # 2. parse_decl with dummy variable name (basic types, pointers, …)
    for decl in (text + " __x;", text + " __x"):
        tif = ida_typeinf.tinfo_t()
        try:
            ret = ida_typeinf.parse_decl(tif, None, decl, ida_typeinf.PT_SIL)
            if ret and not tif.empty():
                return tif
        except Exception:
            pass

    # 3. tinfo_t constructor — handles function pointers like "int (*)(void *, int)"
    try:
        tif = ida_typeinf.tinfo_t(text)
        if not tif.empty():
            return tif
    except Exception:
        pass

    raise ToolError(-4, "parse_decl failed for: %s" % text)


def set_type(params: dict[str, Any]) -> dict[str, Any]:
    """Set type on a function/global (addr) or local variable (func+var).

    Routing:
      * ``func`` + ``var`` + ``type``  → local variable type via Hex-Rays
      * ``addr`` + ``type``            → function signature or global data type
    """
    type_str = params.get("type", "")
    if not type_str:
        raise ToolError(-4, "Missing required parameter: type")

    func_str = params.get("func", "")
    var_str = params.get("var", "")

    if func_str and var_str:
        return _set_type_local(func_str, var_str, type_str)

    addr_str = params.get("addr", "")
    if addr_str:
        return _set_type_addr(addr_str, type_str)

    raise ToolError(
        -4,
        "Provide addr+type (function/global) or func+var+type (local variable)",
    )


def _set_type_addr(addr_str: str, type_str: str) -> dict[str, Any]:
    """Set type on a function or global address."""
    import ida_typeinf
    import ida_nalt
    import idaapi
    import idc

    ea = resolve_addr(addr_str)
    func = idaapi.get_func(ea)

    old_tif = ida_typeinf.tinfo_t()
    ida_nalt.get_tinfo(old_tif, ea)
    old_type = str(old_tif) if not old_tif.empty() else None

    is_func_entry = func is not None and func.start_ea == ea

    if is_func_entry:
        text = type_str.strip()
        if not text.endswith(";"):
            text += ";"
        ok = idc.SetType(ea, text)
        if not ok:
            tif = _parse_tinfo(type_str)
            ok = ida_typeinf.apply_tinfo(ea, tif, ida_typeinf.PT_SIL)
        if not ok:
            raise ToolError(-14, "apply_tinfo(%s, ...) returned False" % hex(ea))
    else:
        tif = _parse_tinfo(type_str)
        ok = ida_typeinf.apply_tinfo(ea, tif, ida_typeinf.PT_SIL)
        if not ok:
            raise ToolError(-14, "apply_tinfo(%s, ...) returned False" % hex(ea))

    new_tif = ida_typeinf.tinfo_t()
    ida_nalt.get_tinfo(new_tif, ea)
    new_type = str(new_tif) if not new_tif.empty() else idc.get_type(ea)

    result: dict[str, Any] = {"addr": hex(ea)}
    if old_type:
        result["old_type"] = old_type
    result["new_type"] = new_type
    result["target"] = "function" if is_func_entry else "global"
    return result


def _set_type_local(
    func_str: str, var_name: str, type_str: str
) -> dict[str, Any]:
    """Set type on a local variable / argument via Hex-Rays."""
    import ida_funcs
    import ida_hexrays

    ea = resolve_addr(func_str)
    func = ida_funcs.get_func(ea)
    if func is None:
        raise ToolError(-12, "get_func(%s) returned None" % hex(ea))

    cfunc = ida_hexrays.decompile(func.start_ea)
    if cfunc is None:
        raise ToolError(-12, "decompile(%s) returned None" % hex(func.start_ea))

    target_lv = None
    for lv in cfunc.lvars:
        if lv.name == var_name:
            target_lv = lv
            break

    if target_lv is None:
        raise ToolError(
            -12,
            "lvar '%s' not found in cfunc.lvars at %s" % (var_name, hex(func.start_ea)),
        )

    old_type = str(target_lv.type())
    tif = _parse_tinfo(type_str)

    target_lv.set_lvar_type(tif)
    target_lv.set_user_type()

    return {
        "func": hex(func.start_ea),
        "func_name": ida_funcs.get_func_name(func.start_ea),
        "var": var_name,
        "old_type": old_type,
        "new_type": str(target_lv.type()),
    }


def define_type(params: dict[str, Any]) -> dict[str, Any]:
    """Declare C types (struct, enum, typedef, union) in the local type library."""
    import ida_typeinf
    import re

    declare = params.get("declare", "")
    if not declare:
        raise ToolError(-4, "Missing required parameter: declare")

    flags = ida_typeinf.PT_SIL | ida_typeinf.PT_TYP
    errors = ida_typeinf.parse_decls(None, declare, False, flags)

    # Extract declared type names and verify each one
    til = ida_typeinf.get_idati()
    names: list[str] = []
    # struct/union/enum: name follows keyword
    names += re.findall(r"(?:struct|union|enum)\s+(\w+)", declare)
    # typedef with function pointer: name is inside (*name)
    names += re.findall(r"typedef\s+.*?\(\s*\*\s*(\w+)\s*\)", declare)
    # typedef simple: last identifier before semicolon
    for m in re.finditer(r"typedef\s+[^;]+?(\w+)\s*;", declare):
        names.append(m.group(1))
    seen: set[str] = set()
    types: list[dict[str, Any]] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        tif = ida_typeinf.tinfo_t()
        if tif.get_named_type(til, name):
            entry: dict[str, Any] = {"name": name, "size": tif.get_size()}
            if tif.is_struct():
                entry["kind"] = "struct"
            elif tif.is_union():
                entry["kind"] = "union"
            elif tif.is_enum():
                entry["kind"] = "enum"
            else:
                entry["kind"] = "typedef"
            types.append(entry)

    if errors > 0 and not types:
        raise ToolError(-14, "parse_decls returned %d error(s), 0 types defined" % errors)

    result: dict[str, Any] = {"total": len(types), "errors": errors, "types": types}
    if errors > 0:
        result["warning"] = "%d parse error(s); some types may not have been created" % errors
    return result
