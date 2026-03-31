"""Session management — tool implementations.

Pure async functions.  Registration (name, description) lives in
``tools/__init__.py``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from ramune_ida.commands import CloseDatabase, Ping
from ramune_ida.server.app import get_state


# ── Project lifecycle ─────────────────────────────────────────────


async def open_project(
    ctx: Context,
    project_id: str | None = None,
) -> dict:
    state = get_state()
    project = state.open_project(project_id)
    return {
        "project_id": project.project_id,
        "work_dir": project.work_dir,
    }


async def close_project(
    project_id: str,
    ctx: Context,
) -> dict:
    state = get_state()
    await state.close_project(project_id)
    return {"status": "closed", "project_id": project_id}


async def projects(ctx: Context) -> dict:
    state = get_state()
    result = []
    for pid, project in state.projects.items():
        entry: dict[str, Any] = {
            "project_id": pid,
            "exe_path": project.exe_path,
            "idb_path": project.idb_path,
            "has_worker": project._handle is not None,
            "has_database": project.has_database,
        }
        result.append(entry)
    return {
        "projects": result,
        "count": len(result),
        "instance_count": state.limiter.instance_count,
    }


# ── Database lifecycle ────────────────────────────────────────────


async def open_database(
    project_id: str,
    path: Annotated[str, Field(description="Binary or IDB path, relative to work_dir")],
    ctx: Context,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)

    if not os.path.isabs(path):
        path = os.path.join(project.work_dir, path)
    path = os.path.realpath(path)

    project.set_database(path)
    task = await project.execute(Ping(), timeout=300.0)

    result: dict[str, Any] = {
        "project_id": project_id,
        "status": task.status.value,
    }
    result["idb_path"] = project.idb_path
    if project.exe_path:
        result["exe_path"] = project.exe_path
    if not task.is_done:
        result["task_id"] = task.task_id
    if state.limiter.over_soft_limit:
        result["warning"] = (
            f"Instance count ({state.limiter.instance_count}) "
            f"exceeds soft limit ({state.limiter._soft_limit}). "
            f"Consider closing idle projects."
        )
    return result


async def close_database(
    project_id: str,
    ctx: Context,
    force: bool = False,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    if project._handle is None:
        return {"status": "no_worker", "project_id": project_id}

    if force:
        project.force_close()
        return {"status": "killed", "project_id": project_id}

    try:
        task = await asyncio.wait_for(
            project.execute(CloseDatabase()), timeout=30.0
        )
        status = task.status.value
    except Exception:
        project.force_close()
        status = "killed"

    if project._handle is not None:
        project._handle.kill()
        project._handle = None
        project._limiter.on_destroyed(project.project_id)

    return {"status": status, "project_id": project_id}


# ── Async tasks ───────────────────────────────────────────────────


async def get_task_result(
    task_id: str,
    project_id: str,
    ctx: Context,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    task = await project.get_task_result(task_id)
    if task is None:
        still_pending = task_id in project._tasks
        if still_pending:
            t = project._tasks[task_id]
            return t.to_dict() | {"project_id": project_id}
        return {
            "task_id": task_id,
            "status": "not_found",
            "project_id": project_id,
        }
    return task.to_dict() | {"project_id": project_id}


async def cancel_task(
    task_id: str,
    project_id: str,
    ctx: Context,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    project.cancel_task(task_id)
    return {"task_id": task_id, "status": "cancelled", "project_id": project_id}
