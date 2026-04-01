"""Worker-side handlers for data reading tools.

Each function receives ``params: dict`` and returns ``dict``.
IDA modules are imported inside function bodies so the module
itself can be imported safely without IDA (e.g. during --list-plugins).

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

from typing import Any

from ramune_ida.core import ToolError, resolve_addr


def examine(params: dict[str, Any]) -> dict[str, Any]:
    """Examine an address — auto-detect type and return value."""
    import ida_bytes
    import idc

    addr_str = params.get("addr", "")
    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")
    max_count = int(params.get("count", 0) or 0)

    ea = resolve_addr(addr_str)
    flags = ida_bytes.get_flags(ea)
    result: dict[str, Any] = {"addr": hex(ea)}

    if ida_bytes.is_strlit(flags):
        raw = idc.get_strlit_contents(ea)
        result["type"] = "string"
        result["value"] = raw.decode("utf-8", errors="replace") if raw else ""

    elif ida_bytes.is_code(flags):
        result["type"] = "code"
        result["value"] = idc.GetDisasm(ea)

    elif ida_bytes.is_data(flags):
        item_sz = idc.get_item_size(ea)
        if ida_bytes.is_qword(flags):
            elem_sz = 8
            n = item_sz // elem_sz
            if n > 1:
                n = min(n, max_count) if max_count else n
                result["type"] = "qword[]"
                result["count"] = n
                result["values"] = [idc.get_qword(ea + i * elem_sz) for i in range(n)]
            else:
                result["type"] = "qword"
                result["value"] = idc.get_qword(ea)
        elif ida_bytes.is_dword(flags):
            elem_sz = 4
            n = item_sz // elem_sz
            if n > 1:
                n = min(n, max_count) if max_count else n
                result["type"] = "dword[]"
                result["count"] = n
                result["values"] = [idc.get_wide_dword(ea + i * elem_sz) for i in range(n)]
            else:
                result["type"] = "dword"
                result["value"] = idc.get_wide_dword(ea)
        elif ida_bytes.is_word(flags):
            elem_sz = 2
            n = item_sz // elem_sz
            if n > 1:
                n = min(n, max_count) if max_count else n
                result["type"] = "word[]"
                result["count"] = n
                result["values"] = [idc.get_wide_word(ea + i * elem_sz) for i in range(n)]
            else:
                result["type"] = "word"
                result["value"] = idc.get_wide_word(ea)
        elif ida_bytes.is_byte(flags):
            n = item_sz
            if n > 1:
                n = min(n, max_count) if max_count else n
                result["type"] = "byte[]"
                result["count"] = n
                raw = ida_bytes.get_bytes(ea, n)
                result["values"] = list(raw) if raw else []
            else:
                result["type"] = "byte"
                result["value"] = idc.get_wide_byte(ea)
        else:
            raw = ida_bytes.get_bytes(ea, item_sz) if item_sz > 0 else b""
            result["type"] = "data"
            result["value"] = raw.hex() if raw else ""
            result["size"] = item_sz

    elif ida_bytes.is_struct(flags):
        item_sz = idc.get_item_size(ea)
        raw = ida_bytes.get_bytes(ea, item_sz) if item_sz > 0 else b""
        result["type"] = "struct"
        result["value"] = raw.hex() if raw else ""
        result["size"] = item_sz

    else:
        n = max_count if max_count else 16
        raw = ida_bytes.get_bytes(ea, n)
        result["type"] = "unknown"
        result["value"] = raw.hex() if raw else ""
        result["count"] = n

    return result


def get_bytes(params: dict[str, Any]) -> dict[str, Any]:
    """Read raw bytes at an address."""
    import ida_bytes

    addr_str = params.get("addr", "")
    if not addr_str:
        raise ToolError(-4, "Missing required parameter: addr")
    size = params.get("size")
    if not size:
        raise ToolError(-4, "Missing required parameter: size")
    size = int(size)

    ea = resolve_addr(addr_str)
    raw = ida_bytes.get_bytes(ea, size)
    if raw is None:
        raise ToolError(-12, "get_bytes(%s, %d) returned None" % (hex(ea), size))

    return {"addr": hex(ea), "size": size, "bytes": raw.hex()}
