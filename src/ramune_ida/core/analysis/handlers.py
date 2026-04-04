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
    """Disassemble instructions starting at *addr*.

    If *addr* belongs to a function and *count* is not given,
    disassembles the entire function.  Otherwise disassembles
    *count* instructions (default 20).
    """
    import ida_funcs
    import ida_ua
    import idc

    addr_str = params.get("addr", "")
    count = params.get("count", None)

    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")

    addr = _resolve_addr(addr_str)

    # If no explicit count, try to disassemble the whole function
    func = ida_funcs.get_func(addr)
    if count is None and func is not None:
        start = func.start_ea
        end = func.end_ea
        func_name = ida_funcs.get_func_name(start)
        lines: list[str] = []
        cur = start
        while cur < end:
            insn = ida_ua.insn_t()
            length = ida_ua.decode_insn(insn, cur)
            if length == 0:
                break
            lines.append(idc.GetDisasm(cur))
            cur += length
        return {
            "start_addr": hex(start),
            "end_addr": hex(end),
            "func_name": func_name,
            "count": len(lines),
            "disasm": "\n".join(lines),
        }

    # Fallback: fixed count
    if count is None:
        count = 20
    lines = []
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


def linear_view(params: dict[str, Any]) -> dict[str, Any]:
    """Linear disassembly view — returns lines for an address range.

    Each line has: addr, type (code/data/string/align/func_header/separator/unknown),
    text, and optional metadata (func_name, xrefs, etc.).
    """
    import idaapi
    import ida_bytes
    import ida_funcs
    import ida_lines
    import ida_name
    import ida_segment
    import ida_ua
    import idautils
    import idc

    addr_str = params.get("addr", "")
    count = params.get("count", 100) or 100
    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")

    addr = _resolve_addr(addr_str)

    lines: list[dict[str, Any]] = []
    cur = addr

    # Snap to nearest head
    if not ida_bytes.is_head(ida_bytes.get_flags(cur)):
        cur = ida_bytes.next_head(cur, idaapi.BADADDR)
        if cur == idaapi.BADADDR:
            return {"start": hex(addr), "lines": [], "count": 0}

    emitted = 0
    prev_func_ea: int | None = None

    while emitted < count and cur != idaapi.BADADDR:
        flags = ida_bytes.get_flags(cur)
        seg = ida_segment.getseg(cur)
        seg_name = ida_segment.get_segm_name(seg) if seg else ""

        # Check if we're entering a new function — emit header
        func = ida_funcs.get_func(cur)
        if func and func.start_ea == cur and func.start_ea != prev_func_ea:
            fname = ida_funcs.get_func_name(cur)
            # Separator
            lines.append({
                "addr": hex(cur),
                "type": "separator",
                "text": "",
                "segment": seg_name,
            })
            # Function header
            lines.append({
                "addr": hex(cur),
                "type": "func_header",
                "text": f"{fname} proc near",
                "func_name": fname,
                "segment": seg_name,
            })
            # Xrefs to function
            xrefs_to = list(idautils.XrefsTo(cur))
            if xrefs_to:
                xref_strs = []
                for xr in xrefs_to[:5]:
                    xf = ida_funcs.get_func(xr.frm)
                    if xf:
                        xn = ida_funcs.get_func_name(xf.start_ea)
                        xref_strs.append(f"{xn}+{xr.frm - xf.start_ea:#x}")
                    else:
                        xref_strs.append(hex(xr.frm))
                suffix = f" ..." if len(xrefs_to) > 5 else ""
                lines.append({
                    "addr": hex(cur),
                    "type": "xref_comment",
                    "text": f"; CODE XREF: {', '.join(xref_strs)}{suffix}",
                    "segment": seg_name,
                })
            emitted += 1
            prev_func_ea = func.start_ea

        if ida_bytes.is_code(flags):
            # Code line
            mnem = idc.print_insn_mnem(cur)
            disasm_text = idc.GetDisasm(cur)
            operands = disasm_text[len(mnem):].strip() if mnem and disasm_text.startswith(mnem) else disasm_text
            insn = ida_ua.insn_t()
            length = ida_ua.decode_insn(insn, cur)
            size = length if length > 0 else 1

            line: dict[str, Any] = {
                "addr": hex(cur),
                "type": "code",
                "mnemonic": mnem,
                "operands": operands,
                "size": size,
                "segment": seg_name,
            }
            # Add function context
            if func:
                line["func_name"] = ida_funcs.get_func_name(func.start_ea)
            lines.append(line)
            cur = cur + size
        elif ida_bytes.is_data(flags):
            size = ida_bytes.get_item_size(cur)
            name = ida_name.get_name(cur) or ""
            # Determine data type
            if ida_bytes.is_strlit(flags):
                str_val = idc.get_strlit_contents(cur, -1, idc.get_str_type(cur))
                text = f'"{str_val.decode("utf-8", errors="replace")}"' if str_val else '""'
                lines.append({
                    "addr": hex(cur),
                    "type": "string",
                    "text": text,
                    "name": name,
                    "size": size,
                    "segment": seg_name,
                })
            else:
                # Generic data
                data_text = idc.GetDisasm(cur)
                lines.append({
                    "addr": hex(cur),
                    "type": "data",
                    "text": data_text,
                    "name": name,
                    "size": size,
                    "segment": seg_name,
                })
            cur = cur + size
        elif ida_bytes.is_align(flags):
            size = ida_bytes.get_item_size(cur)
            lines.append({
                "addr": hex(cur),
                "type": "align",
                "text": f"align {size:#x}",
                "size": size,
                "segment": seg_name,
            })
            cur = cur + size
        else:
            # Unknown / unexplored — coalesce runs of same-value bytes
            byte_val = ida_bytes.get_byte(cur)
            run_start = cur
            run_len = 1
            cur += 1
            while cur != idaapi.BADADDR and run_len < 0x10000:
                nflags = ida_bytes.get_flags(cur)
                if ida_bytes.is_head(nflags) and (ida_bytes.is_code(nflags) or ida_bytes.is_data(nflags)):
                    break
                nb = ida_bytes.get_byte(cur)
                if nb != byte_val:
                    break
                run_len += 1
                cur += 1

            if run_len >= 64:
                lines.append({
                    "addr": hex(run_start),
                    "type": "unknown",
                    "text": f"db {byte_val:#04x} x {run_len}",
                    "size": run_len,
                    "segment": seg_name,
                })
            else:
                lines.append({
                    "addr": hex(run_start),
                    "type": "unknown",
                    "text": f"db {byte_val:#04x}",
                    "size": 1,
                    "segment": seg_name,
                })

        emitted += 1

    # Check if we're at the end of a function — emit endp
    if func and cur >= func.end_ea and prev_func_ea == func.start_ea:
        fname = ida_funcs.get_func_name(func.start_ea)
        lines.append({
            "addr": hex(func.end_ea),
            "type": "func_end",
            "text": f"{fname} endp",
            "func_name": fname,
        })

    next_addr = hex(cur) if cur != idaapi.BADADDR else None

    return {
        "start": hex(addr),
        "next": next_addr,
        "count": len(lines),
        "lines": lines,
    }


def func_view(params: dict[str, Any]) -> dict[str, Any]:
    """Structured function view for Web UI: decompile + disasm + line mapping."""
    import idaapi
    import ida_funcs
    import ida_hexrays
    import ida_lines
    import ida_ua
    import idc

    func_str = params.get("func", "")
    if not func_str:
        raise ToolError(-4, "Missing required parameter: func")

    addr = _resolve_addr(func_str)
    func_obj = ida_funcs.get_func(addr)
    if func_obj is None:
        raise ToolError(-12, "get_func(%s) returned None" % hex(addr))

    start_ea = func_obj.start_ea
    end_ea = func_obj.end_ea
    func_name = ida_funcs.get_func_name(start_ea)

    # ── Decompile ───────────────────────────────────────────────
    try:
        cfunc = ida_hexrays.decompile(start_ea)
    except ida_hexrays.DecompilationFailure as exc:
        raise ToolError(-13, str(exc))
    if cfunc is None:
        raise ToolError(-13, "decompile(%s) returned None" % hex(start_ea))

    pseudocode = cfunc.get_pseudocode()
    num_lines = pseudocode.size()

    # ── Build line ↔ addr mapping ───────────────────────────────
    # Use eamap (EA → cinsnptrvec_t): keys are real code EAs.
    # For each EA, the cinsn_t objects tell us which statement owns it.
    # Use boundaries (cinsn_t → rangeset_t) to group EAs by statement.
    # Then assign each statement to a pseudocode line by matching
    # the statement's EA to the pseudocode rendering order.
    #
    # Approach: collect all eamap EAs. For each, find the owning
    # cinsn_t and its .ea. Group by cinsn.ea. Then assign groups
    # to pseudocode lines using boundaries' EA ranges.

    addr_lines: dict[int, set[int]] = {}   # EA → set of line numbers
    line_addrs: dict[int, set[int]] = {}   # line number → set of EAs

    # Collect all eamap EAs and their owning cinsn EAs
    ea_to_cinsn_ea: dict[int, int] = {}
    for eamap_ea in cfunc.eamap:
        eamap_ea_int = int(eamap_ea)
        if eamap_ea_int < start_ea or eamap_ea_int >= end_ea:
            continue
        for cinsn in cfunc.eamap[eamap_ea]:
            try:
                cea = int(cinsn.ea)
                if cea != idaapi.BADADDR:
                    ea_to_cinsn_ea[eamap_ea_int] = cea
                    break
            except (TypeError, ValueError):
                pass

    # Build cinsn_ea → set of covered instruction EAs
    cinsn_groups: dict[int, set[int]] = {}
    for ea, cea in ea_to_cinsn_ea.items():
        cinsn_groups.setdefault(cea, set()).add(ea)

    # Assign pseudocode lines: boundaries maps cinsn_t → EA ranges.
    # For each boundary entry, find all eamap EAs in its range.
    # The boundary entries appear in pseudocode order.
    # We assign line numbers based on the order of unique cinsn EAs
    # encountered while scanning the pseudocode top-to-bottom.

    # Simpler: for each pseudocode line, use a heuristic.
    # The pseudocode text contains addresses as colored tags.
    # Tags use \x01\x28 + 16-char hex. These are ctree item
    # indices or internal IDs. Items with index < treeitems.size()
    # can be looked up safely.

    _COLOR_ON = '\x01'
    _ADDR_TAG = '\x28'
    ti_size = cfunc.treeitems.size()

    for line_idx in range(num_lines):
        sl = pseudocode.at(line_idx)
        raw = sl.line
        found_eas: set[int] = set()
        i = 0
        while i < len(raw) - 17:
            if raw[i] == _COLOR_ON and raw[i + 1] == _ADDR_TAG:
                hex_str = raw[i + 2: i + 18]
                try:
                    item_id = int(hex_str, 16)
                    if item_id < ti_size:
                        ti = cfunc.treeitems.at(item_id)
                        try:
                            ea = int(ti.ea)
                        except (TypeError, ValueError):
                            ea = idaapi.BADADDR
                        if ea != idaapi.BADADDR and start_ea <= ea < end_ea:
                            found_eas.add(ea)
                            # Also add all EAs from the same cinsn group
                            cea = ea_to_cinsn_ea.get(ea, ea)
                            for group_ea in cinsn_groups.get(cea, ()):
                                found_eas.add(group_ea)
                except (ValueError, IndexError, RuntimeError):
                    pass
                i += 18
            else:
                i += 1
        if found_eas:
            line_addrs[line_idx] = found_eas
            for ea in found_eas:
                addr_lines.setdefault(ea, set()).add(line_idx)

    # ── Disassemble ─────────────────────────────────────────────
    disasm_lines: list[dict[str, Any]] = []
    cur = start_ea
    while cur < end_ea:
        insn = ida_ua.insn_t()
        length = ida_ua.decode_insn(insn, cur)
        if length == 0:
            break
        mnem = idc.print_insn_mnem(cur)
        text = idc.GetDisasm(cur)
        operands = text[len(mnem):].strip() if mnem and text.startswith(mnem) else text

        mapped_lines = sorted(addr_lines.get(cur, []))
        disasm_lines.append({
            "addr": hex(cur),
            "size": length,
            "mnemonic": mnem,
            "operands": operands,
            "decompile_lines": mapped_lines,
        })
        cur += length

    # ── Build decompile output ──────────────────────────────────
    decompile_lines: list[dict[str, Any]] = []
    for line_idx in range(num_lines):
        sl = pseudocode.at(line_idx)
        text = ida_lines.tag_remove(sl.line)
        mapped_addrs = sorted(hex(a) for a in line_addrs.get(line_idx, []))
        decompile_lines.append({
            "line": line_idx,
            "text": text,
            "addrs": mapped_addrs,
        })

    return {
        "func": {
            "addr": hex(start_ea),
            "end": hex(end_ea),
            "name": func_name,
        },
        "decompile": decompile_lines,
        "disasm": disasm_lines,
    }
