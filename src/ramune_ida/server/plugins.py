"""Plugin discovery and dynamic MCP tool registration.

Discovers tools by calling the Worker's ``--list-plugins`` mode
(which does NOT load ``idapro``), then dynamically builds and
registers an MCP tool function for each discovered tool.

FastMCP coupling (verified against mcp 1.26.0)
-----------------------------------------------
This module relies on two FastMCP internal behaviours.  If a
future mcp release breaks registration, check these first:

1. ``Tool.from_function`` reads ``inspect.signature(fn)`` to build
   a Pydantic arg model.  We satisfy this by setting
   ``_tool_fn.__signature__``.

2. ``func_metadata`` (func_metadata.py) iterates
   ``signature.parameters`` and feeds them into
   ``pydantic.create_model``.  Our ``Annotated[T, Field(...)]``
   annotations are consumed here for descriptions / defaults.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from typing import Annotated, Any

from pydantic import Field

from ramune_ida.commands import PluginInvocation
from ramune_ida.server.app import get_state, register_tool
from ramune_ida.worker.plugins import ENV_PLUGIN_DIR
from ramune_ida.worker.tags import TAG_MCP_FALSE

log = logging.getLogger(__name__)

# ── Discovery ─────────────────────────────────────────────────────


async def discover_tools(
    worker_python: str,
    plugin_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Run ``worker_python -m ramune_ida.worker.main --list-plugins``.

    Returns a list of tool metadata dicts, or an empty list on error.
    """
    env = dict(os.environ)
    if plugin_dir:
        env[ENV_PLUGIN_DIR] = plugin_dir

    try:
        proc = await asyncio.create_subprocess_exec(
            worker_python, "-m", "ramune_ida.worker.main", "--list-plugins",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            log.warning(
                "Plugin discovery exited with code %d: %s",
                proc.returncode,
                stderr.decode(errors="replace").strip(),
            )
            return []

        tools: list[dict[str, Any]] = json.loads(stdout)
        log.info("Discovered %d plugin tool(s)", len(tools))
        return tools

    except FileNotFoundError:
        log.warning(
            "Worker python %r not found — skipping plugin discovery",
            worker_python,
        )
        return []
    except Exception:
        log.warning("Plugin discovery failed", exc_info=True)
        return []


# ── Registration ──────────────────────────────────────────────────

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def register_plugin_tools(tools_metadata: list[dict[str, Any]]) -> int:
    """Create and register an MCP tool for each metadata entry.

    Returns the number of tools successfully registered.
    """
    count = 0
    for meta in tools_metadata:
        tags = meta.get("tags", [])
        if TAG_MCP_FALSE in tags:
            log.info("Skipping MCP registration for %s (mcp:false)", meta.get("name", "?"))
            continue
        try:
            _register_one(meta)
            count += 1
        except Exception:
            log.warning(
                "Failed to register plugin tool %r",
                meta.get("name", "?"),
                exc_info=True,
            )
    return count


def _register_one(meta: dict[str, Any]) -> None:
    tool_name: str = meta["name"]
    description: str = meta["description"]
    params_spec: dict[str, dict] = meta.get("params", {})
    default_timeout: int = meta.get("timeout", 30)

    required_params: list[inspect.Parameter] = []
    optional_params: list[inspect.Parameter] = []

    for pname, pdef in params_spec.items():
        base_type = _TYPE_MAP.get(pdef.get("type", "string"), str)
        desc = pdef.get("description")
        annotation: Any = (
            Annotated[base_type, Field(description=desc)] if desc else base_type
        )

        required = pdef.get("required", True)
        default_val = pdef.get("default", inspect.Parameter.empty)

        if required:
            required_params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                )
            )
        else:
            if default_val is inspect.Parameter.empty:
                default_val = None
                annotation = annotation | None  # type: ignore[operator]
            optional_params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                    default=default_val,
                )
            )

    parameters = [
        inspect.Parameter(
            "project_id",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=str,
        ),
        *required_params,
        *optional_params,
    ]

    sig = inspect.Signature(parameters, return_annotation=dict)

    _tool_name = tool_name
    _default_timeout = default_timeout

    async def _tool_fn(**kwargs: Any) -> dict[str, Any]:
        project_id: str = kwargs.pop("project_id")
        timeout_val = float(_default_timeout)

        state = get_state()
        project = state.resolve_project(project_id)
        invocation = PluginInvocation(_tool_name, kwargs)
        task = await project.execute(invocation, timeout=timeout_val)  # type: ignore[arg-type]
        return task.to_mcp_result(project_id)

    _tool_fn.__name__ = tool_name
    _tool_fn.__qualname__ = tool_name

    _tool_fn.__signature__ = sig  # type: ignore[attr-defined]

    register_tool(description=description)(_tool_fn)
    log.info("Registered plugin tool: %s", tool_name)
