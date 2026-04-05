"""Worker-side handlers for Web UI internal tools.

These tools are tagged mcp:false — they are loaded by the Worker
but NOT registered as MCP tools. The Web API calls them directly
via PluginInvocation.

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

from typing import Any

from ramune_ida.core import ToolError, resolve_addr as _resolve_addr


# ── resolve ────────────────────────────────────────────────────


def resolve(params: dict[str, Any]) -> dict[str, Any]:
    """Resolve a name or address to its type and location.

    Returns {type, addr, name?, func_name?, func_addr?, size?}.
    type is one of: function, code, data, string, unknown.
    """
    import idaapi
    import ida_bytes
    import ida_funcs
    import ida_name

    target = params.get("target", "")
    if not target:
        raise ToolError(-4, "Missing required parameter: target")

    try:
        addr = _resolve_addr(target)
    except ToolError:
        return {"type": "unknown", "target": target, "error": "Cannot resolve"}

    flags = ida_bytes.get_flags(addr)
    name = ida_name.get_name(addr) or ""

    # Check if it's a function entry
    func = ida_funcs.get_func(addr)
    if func and func.start_ea == addr:
        return {
            "type": "function",
            "addr": hex(addr),
            "name": ida_funcs.get_func_name(addr) or name,
            "size": func.end_ea - func.start_ea,
        }

    # Check if it's code inside a function
    if ida_bytes.is_code(flags):
        result: dict[str, Any] = {
            "type": "code",
            "addr": hex(addr),
            "name": name or None,
        }
        if func:
            result["func_name"] = ida_funcs.get_func_name(func.start_ea)
            result["func_addr"] = hex(func.start_ea)
        return result

    # Check if it's a string
    if ida_bytes.is_strlit(flags):
        import idc
        str_val = idc.get_strlit_contents(addr, -1, idc.get_str_type(addr))
        return {
            "type": "string",
            "addr": hex(addr),
            "name": name or None,
            "value": str_val.decode("utf-8", errors="replace") if str_val else "",
            "size": ida_bytes.get_item_size(addr),
        }

    # Check if it's data
    if ida_bytes.is_data(flags):
        return {
            "type": "data",
            "addr": hex(addr),
            "name": name or None,
            "size": ida_bytes.get_item_size(addr),
        }

    # Unknown / unexplored
    result = {
        "type": "unknown",
        "addr": hex(addr),
        "name": name or None,
    }
    if func:
        result["func_name"] = ida_funcs.get_func_name(func.start_ea)
        result["func_addr"] = hex(func.start_ea)
    return result


# ── list_local_types ───────────────────────────────────────────


def list_local_types(params: dict[str, Any]) -> dict[str, Any]:
    """List local types from the IDB's type library."""
    import ida_typeinf

    til = ida_typeinf.get_idati()
    items: list[dict[str, Any]] = []

    # IDA 9: use get_ordinal_count or iterate until failure
    qty = getattr(ida_typeinf, 'get_ordinal_qty', None)
    if qty:
        count = qty(til)
    else:
        # Fallback: try get_ordinal_count or probe
        count = getattr(til, 'get_ordinal_count', lambda: 0)()
        if count == 0:
            # Probe: try ordinals until we fail
            count = 10000

    for ordinal in range(1, count + 1):
        name = ida_typeinf.get_numbered_type_name(til, ordinal)
        if not name:
            if ordinal > 100 and not items:
                break  # No types found after many tries
            continue
        tif = ida_typeinf.tinfo_t()
        if tif.get_numbered_type(til, ordinal):
            type_str = str(tif)
            kind = "unknown"
            if tif.is_struct():
                kind = "struct"
            elif tif.is_union():
                kind = "union"
            elif tif.is_enum():
                kind = "enum"
            elif tif.is_typedef():
                kind = "typedef"
            elif tif.is_func():
                kind = "funcptr"
            items.append({
                "ordinal": ordinal,
                "name": name,
                "kind": kind,
                "type": type_str,
            })

    return {"total": len(items), "items": items}


# ── linear_view ────────────────────────────────────────────────


def linear_view(params: dict[str, Any]) -> dict[str, Any]:
    """Linear disassembly view — returns lines for an address range.

    Supports forward and backward traversal.
    Returns: {start, lines[], has_more, boundary_addr}
    """
    import idaapi
    import ida_bytes
    import ida_funcs
    import ida_name
    import ida_segment
    import ida_ua
    import idautils
    import idc

    addr_str = params.get("addr", "")
    count = params.get("count", 100) or 100
    direction = params.get("direction", "forward") or "forward"
    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")

    addr = _resolve_addr(addr_str)

    def _snap_to_head(ea: int) -> int:
        """Snap to nearest head, skipping gaps between segments."""
        if ea == idaapi.BADADDR:
            return idaapi.BADADDR
        if ida_bytes.is_head(ida_bytes.get_flags(ea)):
            return ea
        # Try forward
        nxt = ida_bytes.next_head(ea, idaapi.BADADDR)
        return nxt

    def _next_head_skip_gaps(ea: int) -> int:
        """Advance to next head, skipping segment gaps."""
        nxt = ida_bytes.next_head(ea, idaapi.BADADDR)
        if nxt != idaapi.BADADDR:
            return nxt
        # In a gap — find next segment
        seg = ida_segment.get_next_seg(ea)
        return seg.start_ea if seg else idaapi.BADADDR

    def _prev_head_skip_gaps(ea: int) -> int:
        """Go to previous head, skipping segment gaps backward."""
        prev = ida_bytes.prev_head(ea, 0)
        if prev != idaapi.BADADDR:
            return prev
        # In a gap — find previous segment
        seg = ida_segment.getseg(ea)
        if seg and ea == seg.start_ea:
            # At start of segment, go to previous segment
            pseg = ida_segment.get_prev_seg(ea)
            if pseg:
                # Find last head in previous segment
                last = ida_bytes.prev_head(pseg.end_ea, pseg.start_ea)
                return last if last != idaapi.BADADDR else pseg.start_ea
        if seg is None:
            pseg = ida_segment.get_prev_seg(ea)
            if pseg:
                last = ida_bytes.prev_head(pseg.end_ea, pseg.start_ea)
                return last if last != idaapi.BADADDR else pseg.start_ea
        return idaapi.BADADDR

    def _emit_line(ea: int) -> dict[str, Any] | None:
        """Emit a single line for the head at ea. Returns None if invalid."""
        flags = ida_bytes.get_flags(ea)
        seg = ida_segment.getseg(ea)
        if seg is None:
            return None
        seg_name = ida_segment.get_segm_name(seg) or ""
        func = ida_funcs.get_func(ea)

        if ida_bytes.is_code(flags):
            mnem = idc.print_insn_mnem(ea)
            disasm_text = idc.GetDisasm(ea)
            operands = disasm_text[len(mnem):].strip() if mnem and disasm_text.startswith(mnem) else disasm_text
            insn = ida_ua.insn_t()
            length = ida_ua.decode_insn(insn, ea)
            line: dict[str, Any] = {
                "addr": hex(ea),
                "type": "code",
                "mnemonic": mnem,
                "operands": operands,
                "size": length if length > 0 else 1,
                "segment": seg_name,
            }
            if func:
                line["func_name"] = ida_funcs.get_func_name(func.start_ea)
            return line
        elif ida_bytes.is_data(flags):
            size = ida_bytes.get_item_size(ea)
            name = ida_name.get_name(ea) or ""
            if ida_bytes.is_strlit(flags):
                str_val = idc.get_strlit_contents(ea, -1, idc.get_str_type(ea))
                text = f'"{str_val.decode("utf-8", errors="replace")}"' if str_val else '""'
                return {"addr": hex(ea), "type": "string", "text": text,
                        "name": name, "size": size, "segment": seg_name}
            else:
                return {"addr": hex(ea), "type": "data", "text": idc.GetDisasm(ea),
                        "name": name, "size": size, "segment": seg_name}
        elif ida_bytes.is_align(flags):
            size = ida_bytes.get_item_size(ea)
            return {"addr": hex(ea), "type": "align",
                    "text": f"align {size:#x}", "size": size, "segment": seg_name}
        else:
            # Unknown — coalesce same-value runs
            byte_val = ida_bytes.get_byte(ea)
            run_end = ea + 1
            while run_end != idaapi.BADADDR and (run_end - ea) < 0x10000:
                nf = ida_bytes.get_flags(run_end)
                if ida_bytes.is_head(nf) and (ida_bytes.is_code(nf) or ida_bytes.is_data(nf)):
                    break
                if ida_bytes.get_byte(run_end) != byte_val:
                    break
                run_end += 1
            run_len = run_end - ea
            if run_len >= 64:
                return {"addr": hex(ea), "type": "unknown",
                        "text": f"db {byte_val:#04x} x {run_len}",
                        "size": run_len, "segment": seg_name}
            else:
                return {"addr": hex(ea), "type": "unknown",
                        "text": f"db {byte_val:#04x}",
                        "size": 1, "segment": seg_name}

    def _emit_func_header(ea: int) -> list[dict[str, Any]]:
        """Emit function header lines if ea is a function start."""
        func = ida_funcs.get_func(ea)
        if not func or func.start_ea != ea:
            return []
        seg = ida_segment.getseg(ea)
        seg_name = ida_segment.get_segm_name(seg) if seg else ""
        fname = ida_funcs.get_func_name(ea)
        result = [
            {"addr": hex(ea), "type": "separator", "text": "", "segment": seg_name},
            {"addr": hex(ea), "type": "func_header", "text": f"{fname} proc near",
             "func_name": fname, "segment": seg_name},
        ]
        xrefs_to = list(idautils.XrefsTo(ea))
        if xrefs_to:
            xref_strs = []
            for xr in xrefs_to[:5]:
                xf = ida_funcs.get_func(xr.frm)
                if xf:
                    xn = ida_funcs.get_func_name(xf.start_ea)
                    xref_strs.append(f"{xn}+{xr.frm - xf.start_ea:#x}")
                else:
                    xref_strs.append(hex(xr.frm))
            suffix = " ..." if len(xrefs_to) > 5 else ""
            result.append({
                "addr": hex(ea), "type": "xref_comment",
                "text": f"; CODE XREF: {', '.join(xref_strs)}{suffix}",
                "segment": seg_name,
            })
        return result

    # ── Forward traversal ───────────────────────────────────────
    if direction == "forward":
        cur = _snap_to_head(addr)
        if cur == idaapi.BADADDR:
            return {"lines": [], "has_more": False, "boundary_addr": hex(addr)}

        lines: list[dict[str, Any]] = []
        seen_funcs: set[int] = set()
        emitted = 0

        while emitted < count and cur != idaapi.BADADDR:
            seg = ida_segment.getseg(cur)
            if seg is None:
                next_seg = ida_segment.get_next_seg(cur)
                if next_seg is None:
                    break
                cur = next_seg.start_ea
                continue

            # Function header
            func = ida_funcs.get_func(cur)
            if func and func.start_ea == cur and cur not in seen_funcs:
                lines.extend(_emit_func_header(cur))
                seen_funcs.add(cur)

            line = _emit_line(cur)
            if line:
                lines.append(line)
                size = line.get("size", 1)
                cur = _next_head_skip_gaps(cur) if size <= 1 else cur + size
            else:
                cur = _next_head_skip_gaps(cur)
            emitted += 1

        # Check if there's more
        has_more = cur != idaapi.BADADDR
        if has_more and ida_segment.getseg(cur) is None:
            has_more = ida_segment.get_next_seg(cur) is not None

        return {
            "lines": lines,
            "has_more": has_more,
            "boundary_addr": hex(cur) if cur != idaapi.BADADDR else None,
        }

    # ── Backward traversal ──────────────────────────────────────
    else:
        cur = addr
        # Snap to head at or before addr
        if not ida_bytes.is_head(ida_bytes.get_flags(cur)):
            cur = ida_bytes.prev_head(cur, 0)
        if cur == idaapi.BADADDR:
            return {"lines": [], "has_more": False, "boundary_addr": hex(addr)}

        lines = []
        emitted = 0

        while emitted < count and cur != idaapi.BADADDR:
            seg = ida_segment.getseg(cur)
            if seg is None:
                cur = _prev_head_skip_gaps(cur)
                continue

            line = _emit_line(cur)
            if line:
                lines.append(line)
            # Function header (prepend before the function's first instruction)
            func = ida_funcs.get_func(cur)
            if func and func.start_ea == cur:
                for hdr in reversed(_emit_func_header(cur)):
                    lines.append(hdr)

            cur = _prev_head_skip_gaps(cur)
            emitted += 1

        # Reverse to get forward order
        lines.reverse()

        has_more = cur != idaapi.BADADDR

        return {
            "lines": lines,
            "has_more": has_more,
            "boundary_addr": hex(cur) if cur != idaapi.BADADDR else None,
        }


# ── func_view ──────────────────────────────────────────────────


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
    addr_lines: dict[int, set[int]] = {}
    line_addrs: dict[int, set[int]] = {}

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

    cinsn_groups: dict[int, set[int]] = {}
    for ea, cea in ea_to_cinsn_ea.items():
        cinsn_groups.setdefault(cea, set()).add(ea)

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
