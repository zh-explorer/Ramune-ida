"""Session / project management — tool implementations.

Pure async functions.  Registration (name, description) lives in
``tools/__init__.py``.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ramune_ida.commands import CloseDatabase, Ping
from ramune_ida.server.app import get_state


def _soft_limit_warning(result: dict[str, Any]) -> dict[str, Any]:
    """Attach an advisory warning when the instance count exceeds soft_limit."""
    state = get_state()
    limiter = state.limiter
    if limiter.over_soft_limit:
        result["warning"] = (
            f"Instance count ({limiter.instance_count}/{limiter._hard_limit}) "
            f"exceeds soft limit ({limiter._soft_limit}). "
            f"Use close_database to release idle instances. "
            f"At hard limit, new open_project calls will be rejected."
        )
    return result


# ── Project lifecycle ─────────────────────────────────────────────


async def open_project(
    path: str,
    ctx: Context,
    project_id: str | None = None,
) -> dict:
    state = get_state()
    project = state.open_project(path, project_id)

    task = await project.execute(Ping(), timeout=300.0)

    result: dict = {
        "project_id": project.project_id,
        "exe_path": project.exe_path,
        "idb_path": project.idb_path,
        "work_dir": project.work_dir,
        "is_default": state.default_project_id == project.project_id,
        "status": task.status.value,
    }
    if not task.is_done:
        result["task_id"] = task.task_id
    return _soft_limit_warning(result)


async def close_project(
    ctx: Context,
    project_id: str | None = None,
) -> dict:
    state = get_state()
    pid = project_id or state.default_project_id
    if pid is None:
        raise ValueError("No project specified and no default project")
    await state.close_project(pid)
    return {"status": "closed", "project_id": pid}


# ── Worker instance management ────────────────────────────────────


async def close_database(
    ctx: Context,
    project_id: str | None = None,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    if project._handle is None:
        return {
            "status": "no_worker",
            "project_id": project.project_id,
        }
    task = await project.execute(CloseDatabase())
    if project._handle is not None:
        project._handle.kill()
        project._handle = None
        project._limiter.on_destroyed(project.project_id)
    return {
        "status": task.status.value,
        "project_id": project.project_id,
    }


async def force_close(
    ctx: Context,
    project_id: str | None = None,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    project.force_close()
    return {"status": "killed", "project_id": project.project_id}


# ── Navigation ────────────────────────────────────────────────────


async def switch_default(
    project_id: str,
    ctx: Context,
) -> dict:
    state = get_state()
    if project_id not in state.projects:
        raise KeyError(f"Unknown project: {project_id}")
    state.default_project_id = project_id
    return {"status": "ok", "default_project_id": project_id}


# ── Async task polling ────────────────────────────────────────────


async def get_task_result(
    task_id: str,
    ctx: Context,
    project_id: str | None = None,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    task = await project.get_task_result(task_id)
    if task is None:
        still_pending = task_id in project._tasks
        if still_pending:
            t = project._tasks[task_id]
            return t.to_dict() | {"project_id": project.project_id}
        return {
            "task_id": task_id,
            "status": "not_found",
            "project_id": project.project_id,
        }
    return task.to_dict() | {"project_id": project.project_id}
