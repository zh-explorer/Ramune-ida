"""FastMCP application instance and lifespan management.

All tool / resource / custom-route modules import ``register_tool`` and
``mcp`` from here.  ``register_tool`` is a drop-in replacement for
``@mcp.tool`` that automatically passes every return value through
:meth:`OutputStore.process` when the result contains a ``project_id``.
Results without a ``project_id`` are returned as-is (no truncation).

``get_state()`` is the canonical way to obtain the shared
:class:`AppState` from within any handler.
"""

from __future__ import annotations

import inspect
import os
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, AsyncIterator, Callable

from mcp.server.fastmcp import FastMCP

from ramune_ida.config import ServerConfig
from ramune_ida.server.state import AppState

# Module-level singletons ---------------------------------------------------

_config: ServerConfig | None = None
_state: AppState | None = None


def configure(config: ServerConfig) -> None:
    """Set the configuration before ``mcp.run()``."""
    global _config
    _config = config


def get_state() -> AppState:
    """Return the active AppState.  Raises if the server is not started."""
    if _state is None:
        raise RuntimeError("Server not initialised — AppState is None")
    return _state


# Lifespan -------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    global _state
    assert _config is not None, "Call configure() before starting the server"
    state = AppState(_config)
    await state.start()
    _state = state
    try:
        yield {}
    finally:
        await state.shutdown()
        _state = None


# FastMCP instance -----------------------------------------------------------

mcp = FastMCP("ramune-ida", lifespan=_lifespan)


# Auto-truncating tool decorator --------------------------------------------

def _resolve_project_context(
    state: AppState, result: Any
) -> tuple[str | None, str | None]:
    """Extract project_id from a tool result and return *(pid, output_dir)*.

    Returns ``(None, None)`` when truncation should be skipped.
    """
    if not isinstance(result, dict):
        return None, None
    pid = result.get("project_id")
    if pid is None:
        return None, None
    project = state.projects.get(pid)
    if project is None:
        return None, None
    return pid, os.path.join(project.work_dir, "outputs")


def register_tool(*deco_args: Any, **deco_kwargs: Any) -> Any:
    """Register an MCP tool with automatic output truncation.

    Drop-in replacement for ``@mcp.tool``.  Preserves the original
    function signature so FastMCP / Pydantic can generate the correct
    JSON schema.  After the tool function returns, the result is passed
    through ``OutputStore.process()`` **only if** the result contains a
    valid ``project_id``.  Otherwise the result is returned as-is.
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*args, **kwargs)
            try:
                state = get_state()
                pid, output_dir = _resolve_project_context(state, result)
                if pid is not None and output_dir is not None:
                    return state.output_store.process(result, pid, output_dir)
            except RuntimeError:
                pass
            return result

        wrapper.__signature__ = inspect.signature(fn)
        return mcp.tool(*deco_args, **deco_kwargs)(wrapper)

    if deco_args and callable(deco_args[0]) and not deco_kwargs:
        return decorator(deco_args[0])
    return decorator


# Trigger tool / resource / route registration by importing submodules.
# These imports MUST stay after ``mcp`` and ``register_tool`` are defined.
import ramune_ida.server.tools  # noqa: F401, E402
import ramune_ida.server.files  # noqa: F401, E402
import ramune_ida.server.resources  # noqa: F401, E402
