"""Worker-side handlers for analysis tools.

Each function receives ``params: dict`` and returns ``dict``.
IDA modules are imported inside function bodies so the module
itself can be imported safely without IDA (e.g. during --list-plugins).

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

from typing import Any

from ramune_ida.core import ToolError, resolve_addr as _resolve_addr


def decompile(params: dict[str, Any]) -> dict[str, Any]:
    """Decompile the function at *func* (name or hex address)."""
    import ida_funcs
    import ida_hexrays

    func_str = params.get("func", "")
    if not func_str:
        raise ToolError(-4, "Missing required parameter: func")

    addr = _resolve_addr(func_str)

    func_obj = ida_funcs.get_func(addr)
    if func_obj is None:
        raise ToolError(-12, "get_func(%s) returned None" % hex(addr))

    try:
        cfunc = ida_hexrays.decompile(func_obj.start_ea)
    except ida_hexrays.DecompilationFailure as exc:
        raise ToolError(-13, str(exc))

    if cfunc is None:
        raise ToolError(-13, "decompile(%s) returned None" % hex(func_obj.start_ea))

    return {
        "addr": hex(func_obj.start_ea),
        "name": ida_funcs.get_func_name(func_obj.start_ea),
        "code": str(cfunc),
    }


def disasm(params: dict[str, Any]) -> dict[str, Any]:
    """Disassemble *count* instructions starting at *addr*."""
    import ida_ua
    import idc

    addr_str = params.get("addr", "")
    count = params.get("count", 20)

    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")

    addr = _resolve_addr(addr_str)

    lines: list[str] = []
    cur = addr
    for _ in range(count):
        insn = ida_ua.insn_t()
        length = ida_ua.decode_insn(insn, cur)
        if length == 0:
            break
        lines.append(idc.GetDisasm(cur))
        cur += length

    return {"start_addr": hex(addr), "count": len(lines), "disasm": "\n".join(lines)}


def xrefs(params: dict[str, Any]) -> dict[str, Any]:
    """List cross-references to *addr* (name or hex address)."""
    import ida_funcs
    import idautils

    addr_str = params.get("addr", "")
    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")

    addr = _resolve_addr(addr_str)

    lines: list[str] = []
    for xref in idautils.XrefsTo(addr):
        frm = xref.frm
        func = ida_funcs.get_func(frm)
        if func is not None:
            name = ida_funcs.get_func_name(func.start_ea)
            offset = frm - func.start_ea
            lines.append(f"{frm:#x}  {name}+{offset:#x}")
        else:
            lines.append(f"{frm:#x}")

    return {"addr": hex(addr), "total": len(lines), "xrefs": "\n".join(lines)}


# ── filetype constant → human-readable name ──────────────────────

_FILETYPE_NAMES: dict[int, str] = {
    0: "EXE",     # f_EXE_old
    1: "COM",     # f_COM_old
    2: "BIN",
    10: "COFF",
    11: "PE",
    18: "ELF",
    20: "AOUT",
    25: "Mach-O",
}


def survey(params: dict[str, Any]) -> dict[str, Any]:
    """Return a compact overview of the loaded binary."""
    import idaapi
    import ida_entry
    import ida_ida
    import ida_nalt
    import ida_segment
    import idautils
    import idc

    # ── identity ─────────────────────────────────────────────────
    filetype = ida_ida.inf_get_filetype()
    fmt = _FILETYPE_NAMES.get(filetype, "unknown(%d)" % filetype)
    if ida_ida.inf_is_dll():
        kind = "DLL" if filetype == 11 else "shared library"
    else:
        kind = "executable"
    type_str = "%s %s" % (fmt, kind)

    procname = ida_ida.inf_get_procname()
    if procname == "metapc":
        arch = "x86_64" if ida_ida.inf_is_64bit() else "x86"
    elif procname in ("ARM", "ARMB"):
        arch = "arm64" if ida_ida.inf_is_64bit() else "arm"
    else:
        arch = "%s%s" % (procname, "/64" if ida_ida.inf_is_64bit() else "")

    # ── segments ─────────────────────────────────────────────────
    segments: list[dict[str, str]] = []
    last_end = 0
    for seg_ea in idautils.Segments():
        seg = idaapi.getseg(seg_ea)
        if seg is None:
            continue
        perm = ""
        if seg.perm & idaapi.SEGPERM_READ:
            perm += "r"
        if seg.perm & idaapi.SEGPERM_WRITE:
            perm += "w"
        if seg.perm & idaapi.SEGPERM_EXEC:
            perm += "x"
        segments.append({
            "name": ida_segment.get_segm_name(seg),
            "start": hex(seg.start_ea),
            "end": hex(seg.end_ea),
            "perm": perm or "---",
        })
        if seg.end_ea > last_end:
            last_end = seg.end_ea

    base = idaapi.get_imagebase()
    size = last_end - base if last_end > base else last_end

    # ── entry point ──────────────────────────────────────────────
    start_ea = ida_ida.inf_get_start_ea()
    entry = hex(start_ea)

    import ida_name
    main_ea = ida_name.get_name_ea(0, "main")
    main_addr = hex(main_ea) if main_ea != idaapi.BADADDR else None

    # ── exports (from ida_entry, excluding program start) ────────
    exports: list[dict[str, str]] = []
    for i in range(ida_entry.get_entry_qty()):
        ordinal = ida_entry.get_entry_ordinal(i)
        ea = ida_entry.get_entry(ordinal)
        name = ida_entry.get_entry_name(ordinal) or ""
        if ea == start_ea:
            continue
        exports.append({"addr": hex(ea), "name": name})

    # ── function statistics ──────────────────────────────────────
    total = named = unnamed = library = 0
    for ea in idautils.Functions():
        total += 1
        name = idc.get_name(ea, 0) or ""
        func = idaapi.get_func(ea)
        flags = func.flags if func else 0
        if flags & idaapi.FUNC_LIB:
            library += 1
        elif name.startswith("sub_"):
            unnamed += 1
        else:
            named += 1

    # ── imports summary ──────────────────────────────────────────
    modules: list[str] = []
    total_imports = 0
    for i in range(ida_nalt.get_import_module_qty()):
        mod_name = ida_nalt.get_import_module_name(i) or ""
        modules.append(mod_name)
        count = [0]

        def _cb(_ea: int, _name: str | None, _ordinal: int,
                _count: list[int] = count) -> bool:
            _count[0] += 1
            return True

        ida_nalt.enum_import_names(i, _cb)
        total_imports += count[0]

    result: dict[str, Any] = {
        "file": ida_nalt.get_root_filename(),
        "type": type_str,
        "arch": arch,
        "base": hex(base),
        "size": hex(size),
        "entry": entry,
    }
    if main_addr is not None:
        result["main"] = main_addr
    result["segments"] = segments
    result["exports"] = exports
    result["functions"] = {
        "total": total,
        "named": named,
        "unnamed": unnamed,
        "library": library,
    }
    result["imports"] = {
        "total": total_imports,
        "modules": modules,
    }
    return result
