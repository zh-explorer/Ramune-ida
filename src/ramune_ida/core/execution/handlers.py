"""Worker-side handler for execute_python.

Runs arbitrary Python code in the IDA environment with
stdout/stderr capture and ``_result`` convention.

Long-running executions should be managed via async tasks + cancel
rather than hard timeouts.

.. note:: Must stay compatible with Python 3.10.
   See :mod:`ramune_ida.worker` docstring for details.
"""

from __future__ import annotations

import io
import sys
import traceback
from typing import Any

from ramune_ida.core import ToolError

_IDA_MODULES = ("idaapi", "idc", "idautils")


def _build_namespace() -> dict[str, Any]:
    """Pre-inject common IDA modules into the exec namespace."""
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    for name in _IDA_MODULES:
        try:
            ns[name] = __import__(name)
        except ImportError:
            pass
    return ns


def execute_python(params: dict[str, Any]) -> dict[str, Any]:
    """Execute arbitrary IDAPython code."""
    code = params.get("code", "")
    if not code:
        raise ToolError(-4, "Missing required parameter: code")

    namespace = _build_namespace()
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    error_msg = ""

    try:
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        exec(code, namespace)
    except Exception:
        error_msg = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return {
        "output": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "result": namespace.get("_result"),
        "error": error_msg,
    }
