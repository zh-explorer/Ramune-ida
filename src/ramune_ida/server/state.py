"""AppState — centralised server-level state.

Manages the collection of Projects, the global Limiter, the OutputStore,
and the periodic auto-save background task.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil

from ramune_ida.config import ServerConfig
from ramune_ida.limiter import Limiter
from ramune_ida.project import Project
from ramune_ida.commands import CloseDatabase
from ramune_ida.server.output import OutputStore

log = logging.getLogger(__name__)


def _generate_project_id(exe_path: str) -> str:
    name = os.path.basename(exe_path)
    suffix = secrets.token_hex(4)
    return f"{name}-{suffix}"


class AppState:
    """Shared state accessible from all MCP tools and resources."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.limiter = Limiter(
            soft_limit=config.soft_limit,
            hard_limit=config.hard_limit,
        )
        self.projects: dict[str, Project] = {}
        self.default_project_id: str | None = None
        self.output_store = OutputStore(
            max_length=config.output_max_length,
            max_outputs_per_project=config.output_max_per_project,
        )

        self._auto_save_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        os.makedirs(self.config.resolved_work_base_dir, exist_ok=True)
        if self.config.auto_save_interval > 0:
            self._auto_save_task = asyncio.create_task(
                self._auto_save_loop(), name="auto-save"
            )

    async def shutdown(self) -> None:
        if self._auto_save_task is not None:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
        for project in list(self.projects.values()):
            project.force_close()
        self.projects.clear()
        self.default_project_id = None
        log.info("Server shutdown complete")

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------

    def open_project(
        self,
        exe_path: str,
        project_id: str | None = None,
    ) -> Project:
        """Create a new Project.  Does **not** spawn a worker (lazy)."""
        real = os.path.realpath(exe_path)

        if project_id is None:
            project_id = _generate_project_id(real)
        if project_id in self.projects:
            raise ValueError(f"Project ID '{project_id}' already exists")

        work_dir = os.path.join(
            self.config.resolved_work_base_dir, project_id
        )
        os.makedirs(work_dir, exist_ok=True)

        idb_path = os.path.splitext(real)[0] + ".i64"

        project = Project(
            project_id=project_id,
            exe_path=real,
            idb_path=idb_path,
            work_dir=work_dir,
            limiter=self.limiter,
            worker_python=self.config.worker_python,
        )
        self.projects[project_id] = project

        if self.default_project_id is None:
            self.default_project_id = project_id

        log.info("Opened project %s (%s)", project_id, real)
        return project

    async def close_project(self, project_id: str) -> None:
        """Gracefully close then destroy a project."""
        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(f"Unknown project: {project_id}")

        if project._handle is not None:
            try:
                await asyncio.wait_for(
                    project.execute(CloseDatabase()), timeout=30.0
                )
            except Exception:
                log.warning(
                    "Graceful close failed for %s, forcing", project_id
                )
            project.force_close()

        self.projects.pop(project_id, None)
        self.output_store.discard_project(project_id)

        if self.default_project_id == project_id:
            self.default_project_id = (
                next(iter(self.projects)) if self.projects else None
            )

        if os.path.isdir(project.work_dir):
            shutil.rmtree(project.work_dir, ignore_errors=True)

        log.info("Closed project %s", project_id)

    def resolve_project(self, project_id: str | None = None) -> Project:
        """Route to a specific project or the default one."""
        if project_id is not None:
            project = self.projects.get(project_id)
            if project is None:
                raise KeyError(f"Unknown project: {project_id}")
            return project
        if self.default_project_id is None:
            raise RuntimeError("No project is open")
        project = self.projects.get(self.default_project_id)
        if project is None:
            raise RuntimeError("Default project not found")
        return project

    # ------------------------------------------------------------------
    # Auto-save
    # ------------------------------------------------------------------

    async def _auto_save_loop(self) -> None:
        interval = self.config.auto_save_interval
        while True:
            await asyncio.sleep(interval)
            for pid in list(self.limiter.active_projects):
                project = self.projects.get(pid)
                if project is None or project._handle is None:
                    continue
                try:
                    await project.save()
                except Exception:
                    log.warning(
                        "Auto-save failed for %s", pid, exc_info=True
                    )
