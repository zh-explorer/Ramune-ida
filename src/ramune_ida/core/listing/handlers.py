"""Worker-side handlers for listing tools.

Each function receives ``params: dict`` and returns ``dict``.
IDA modules are imported inside function bodies so the module
itself can be imported safely without IDA (e.g. during --list-plugins).

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

from typing import Any, Callable


def _make_predicate(filter_str: str, exclude_str: str) -> Callable[[str], bool] | None:
    """Return a ``str -> bool`` predicate for substring include/exclude."""
    fl = filter_str.lower() if filter_str else ""
    ex = exclude_str.lower() if exclude_str else ""
    if fl and ex:
        return lambda v: fl in v.lower() and ex not in v.lower()
    if fl:
        return lambda v: fl in v.lower()
    if ex:
        return lambda v: ex not in v.lower()
    return None


def _extract_filter(params: dict[str, Any]) -> tuple[str, str]:
    """Extract common filter/exclude from params."""
    filter_str = params.get("filter") or ""
    exclude_str = params.get("exclude") or ""
    return filter_str, exclude_str


def _wrap(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total": len(items), "items": items}


def list_funcs(params: dict[str, Any]) -> dict[str, Any]:
    """List functions with addr, name, size."""
    import idaapi
    import idautils
    import idc

    pred = _make_predicate(*_extract_filter(params))

    items: list[dict[str, Any]] = []
    for ea in idautils.Functions():
        name = idc.get_name(ea, 0) or ""
        if pred and not pred(name):
            continue
        func = idaapi.get_func(ea)
        size = (func.end_ea - func.start_ea) if func else 0
        items.append({"addr": hex(ea), "name": name, "size": size})

    return _wrap(items)


def list_strings(params: dict[str, Any]) -> dict[str, Any]:
    """List strings found in the binary."""
    import idautils

    pred = _make_predicate(*_extract_filter(params))
    start_ea = params.get("start_ea")
    end_ea = params.get("end_ea")
    if start_ea is not None:
        start_ea = int(start_ea, 16) if isinstance(start_ea, str) else int(start_ea)
    if end_ea is not None:
        end_ea = int(end_ea, 16) if isinstance(end_ea, str) else int(end_ea)

    items: list[dict[str, Any]] = []
    for s in idautils.Strings():
        if start_ea is not None and s.ea < start_ea:
            continue
        if end_ea is not None and s.ea >= end_ea:
            continue
        value = str(s)
        if pred and not pred(value):
            continue
        items.append({"addr": hex(s.ea), "value": value, "length": s.length})

    return _wrap(items)


def list_imports(params: dict[str, Any]) -> dict[str, Any]:
    """List imported functions (flat, with module field)."""
    import ida_nalt

    pred = _make_predicate(*_extract_filter(params))

    items: list[dict[str, Any]] = []
    for i in range(ida_nalt.get_import_module_qty()):
        mod_name = ida_nalt.get_import_module_name(i) or ""
        collected: list[dict[str, Any]] = []

        def _cb(
            ea: int,
            name: str | None,
            ordinal: int,
            _out: list = collected,
            _mod: str = mod_name,
            _pred: Callable | None = pred,
        ) -> bool:
            n = name or ("ord#%d" % ordinal)
            if _pred and not _pred(n):
                return True
            _out.append({"module": _mod, "name": n, "addr": hex(ea)})
            return True

        ida_nalt.enum_import_names(i, _cb)
        items.extend(collected)

    return _wrap(items)


def list_names(params: dict[str, Any]) -> dict[str, Any]:
    """List all named addresses."""
    import idautils

    pred = _make_predicate(*_extract_filter(params))

    items: list[dict[str, Any]] = []
    for ea, name in idautils.Names():
        if pred and not pred(name):
            continue
        items.append({"addr": hex(ea), "name": name})

    return _wrap(items)


def _classify_tinfo(tif: Any) -> str:
    """Return kind string for a tinfo_t."""
    if tif.is_struct():
        return "struct"
    if tif.is_union():
        return "union"
    if tif.is_enum():
        return "enum"
    return "typedef"


def list_types(params: dict[str, Any]) -> dict[str, Any]:
    """List types in the local type library."""
    import ida_typeinf

    pred = _make_predicate(*_extract_filter(params))
    kind_filter = (params.get("kind") or "").lower()

    til = ida_typeinf.get_idati()
    limit = ida_typeinf.get_ordinal_limit(til)

    items: list[str] = []
    for ordinal in range(1, limit):
        tif = ida_typeinf.tinfo_t()
        if not tif.get_numbered_type(til, ordinal):
            continue
        name = tif.get_type_name()
        if not name:
            continue

        kind = _classify_tinfo(tif)
        if kind_filter and kind != kind_filter:
            continue
        if pred and not pred(name):
            continue

        size = tif.get_size()
        if kind == "typedef":
            items.append("typedef %s" % name)
        else:
            items.append("%s %s // sizeof=0x%X" % (kind, name, size))

    return {"total": len(items), "items": items}
