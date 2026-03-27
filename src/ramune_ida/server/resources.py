"""MCP Resources — read-only metadata exposed to AI clients.

Resources let the AI discover what files and outputs exist, along with
their HTTP download URLs, without spending a tool-call turn.

Principle: **Resources are for discovery, HTTP routes are for transfer.**
"""

from __future__ import annotations

import json
import os
import time

from ramune_ida.server.app import mcp, get_state


# ── Projects overview ─────────────────────────────────────────────


@mcp.resource(
    "projects://overview",
    description=(
        "All open projects at a glance: IDs, default pointer, worker "
        "state, active task counts, and instance limits.  Read this "
        "instead of calling a tool to check project status."
    ),
)
def projects_overview() -> str:
    state = get_state()
    projects = []
    for pid, project in state.projects.items():
        projects.append({
            "project_id": pid,
            "has_worker": project._handle is not None,
            "active_tasks": len(project._tasks),
        })

    limiter = state.limiter
    return json.dumps({
        "default_project_id": state.default_project_id,
        "projects": projects,
        "instance_count": limiter.instance_count,
        "soft_limit": limiter._soft_limit,
        "hard_limit": limiter._hard_limit,
        "over_soft_limit": limiter.over_soft_limit,
    })


# ── Project metadata ──────────────────────────────────────────────


@mcp.resource(
    "project://{project_id}/status",
    description=(
        "Detailed project status: paths, worker state, active tasks, "
        "output count, and whether it is the default project."
    ),
)
def project_status(project_id: str) -> str:
    state = get_state()
    project = state.projects.get(project_id)
    if project is None:
        return json.dumps({"error": f"Unknown project: {project_id}"})

    tasks = [t.to_dict() for t in project._tasks.values()]

    output_count = len(state.output_store.list_outputs(project_id))

    idle = round(time.monotonic() - project.last_accessed, 1) if project.last_accessed > 0 else None

    return json.dumps({
        "project_id": project_id,
        "exe_path": project.exe_path,
        "idb_path": project.idb_path,
        "work_dir": project.work_dir,
        "is_default": state.default_project_id == project_id,
        "has_worker": project._handle is not None,
        "idle_seconds": idle,
        "tasks": tasks,
        "output_count": output_count,
    })


# ── Project files ─────────────────────────────────────────────────


@mcp.resource(
    "project://{project_id}/files",
    description=(
        "Complete file listing for a project: work_dir contents with "
        "sizes and HTTP download URLs.  This is the single entry point "
        "for discovering all downloadable files in a project."
    ),
)
def project_files(project_id: str) -> str:
    state = get_state()
    project = state.projects.get(project_id)
    if project is None:
        return json.dumps({"error": f"Unknown project: {project_id}"})

    files: list[dict] = []
    work_dir = project.work_dir
    if os.path.isdir(work_dir):
        for root, dirs, filenames in os.walk(work_dir):
            for name in filenames:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, work_dir)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = None
                files.append({
                    "name": rel,
                    "size": size,
                    "download_url": f"/files/{project_id}/{rel}",
                })

    return json.dumps({
        "project_id": project_id,
        "work_dir": work_dir,
        "files": files,
    })


# ── Truncated outputs ─────────────────────────────────────────────


@mcp.resource(
    "outputs://{project_id}",
    description=(
        "Truncated output listing for a project with download URLs. "
        "Only outputs that were truncated by the server appear here."
    ),
)
def project_outputs(project_id: str) -> str:
    state = get_state()
    if project_id not in state.projects:
        return json.dumps({"error": f"Unknown project: {project_id}"})

    raw = state.output_store.list_outputs(project_id)
    outputs = []
    for oid, path in raw.items():
        size = None
        try:
            size = os.path.getsize(path)
        except OSError:
            pass
        outputs.append({
            "output_id": oid,
            "size": size,
            "download_url": f"/files/{project_id}/outputs/{oid}.txt",
        })

    return json.dumps({
        "project_id": project_id,
        "count": len(outputs),
        "outputs": outputs,
    })


# ── Staging area ──────────────────────────────────────────────────


@mcp.resource(
    "files://staging",
    description=(
        "Files in the staging area (uploaded but not yet opened as a project). "
        "Use the path value with open_project to start analysis."
    ),
)
def staging_files() -> str:
    state = get_state()
    staging_dir = os.path.join(
        state.config.resolved_work_base_dir, "_staging"
    )
    files = []
    if os.path.isdir(staging_dir):
        for entry in os.scandir(staging_dir):
            if entry.is_file():
                files.append({
                    "name": entry.name,
                    "path": entry.path,
                    "size": entry.stat().st_size,
                    "download_url": f"/files/{entry.name}",
                })
    return json.dumps({
        "staging_dir": staging_dir,
        "files": files,
    })
