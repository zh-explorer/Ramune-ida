"""Core built-in tools — plugin-style metadata + handlers.

Each sub-package (analysis, execution, ...) provides:
  - ``metadata.py`` with a ``TOOLS`` list (tool name, description, params)
  - ``handlers.py`` with handler functions (name matches tool name)

Discovery is handled by :mod:`ramune_ida.worker.plugins`.

.. note:: Must stay compatible with Python 3.10 (runs in Worker).
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations


class ToolError(Exception):
    """Raised by tool handlers for structured error responses.

    *code* should be a negative integer matching
    :class:`~ramune_ida.protocol.ErrorCode` values.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_addr(name_or_hex: str) -> int:
    """Resolve a name or hex address string to an integer EA.

    Accepts ``0x…`` hex literals, plain decimal integers, or IDA names.
    Raises :class:`ToolError` when the name cannot be found.

    IDA modules are imported lazily so this file can be imported
    without ``idapro`` present (e.g. during ``--list-plugins``).
    """
    import ida_name  # noqa: delay import

    if name_or_hex.startswith(("0x", "0X")):
        try:
            return int(name_or_hex, 16)
        except ValueError:
            pass

    try:
        return int(name_or_hex)
    except ValueError:
        pass

    addr = ida_name.get_name_ea(0, name_or_hex)
    if addr == 0xFFFFFFFFFFFFFFFF:  # BADADDR
        raise ToolError(-12, "get_name_ea(0, '%s') returned BADADDR" % name_or_hex)
    return addr
