"""AppState — centralised server-level state.

Manages the collection of Projects, the global Limiter, the OutputStore,
and the periodic auto-save background task.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil

from ramune_ida.config import ServerConfig
from ramune_ida.limiter import Limiter
from ramune_ida.project import Project
from ramune_ida.commands import CloseDatabase, Shutdown
from ramune_ida.server.output import OutputStore

log = logging.getLogger(__name__)


class AppState:
    """Shared state accessible from all MCP tools and resources."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.limiter = Limiter(
            soft_limit=config.soft_limit,
            hard_limit=config.hard_limit,
        )
        self.projects: dict[str, Project] = {}
        self.output_store = OutputStore(
            max_length=config.output_max_length,
            preview_length=config.output_preview_length,
            max_outputs_per_project=config.output_max_per_project,
        )

        self._project_lock = asyncio.Lock()
        self._auto_save_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        base = self.config.resolved_work_base_dir
        os.makedirs(base, exist_ok=True)
        self._recover_projects(base)
        if self.config.auto_save_interval > 0:
            self._auto_save_task = asyncio.create_task(
                self._auto_save_loop(), name="auto-save"
            )

    def _recover_projects(self, base: str) -> None:
        """Restore Project objects from existing work_dir folders."""
        for entry in os.scandir(base):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            project_id = entry.name
            if not self._VALID_PROJECT_ID.match(project_id):
                continue
            project = Project(
                project_id=project_id,
                work_dir=entry.path,
                limiter=self.limiter,
                worker_python=self.config.worker_python,
                plugin_dir=self.config.resolved_plugin_dir,
            )
            self.projects[project_id] = project
            log.info("Recovered project %s", project_id)


    async def shutdown(self) -> None:
        if self._auto_save_task is not None:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass

        # Graceful close: save databases before killing workers
        active = [
            p for p in self.projects.values()
            if p._handle is not None and p._handle.is_alive()
        ]
        if active:
            log.info("Closing %d database(s)...", len(active))
            await asyncio.gather(
                *(self._graceful_close(p) for p in active),
                return_exceptions=True,
            )

        for project in list(self.projects.values()):
            project.force_close()

        for pid in list(self.projects):
            self.output_store.discard_project(pid)

        self.projects.clear()
        log.info("Server shutdown complete")

    async def _graceful_close(
        self, project: Project, timeout: float = 10.0,
    ) -> None:
        """Send CloseDatabase(save=True) with timeout, log on failure."""
        try:
            await asyncio.wait_for(
                project.execute(CloseDatabase(save=True)), timeout=timeout,
            )
            await asyncio.wait_for(
                project.execute(Shutdown()), timeout=5.0,
            )
            log.info("Saved and closed %s", project.project_id)
        except Exception as exc:
            log.warning(
                "Graceful close failed for %s: %s", project.project_id, exc,
            )

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------

    _VALID_PROJECT_ID = re.compile(r"^[A-Za-z0-9_\-\.]{1,64}$")

    async def open_project(
        self, project_id: str | None = None
    ) -> tuple[Project, bool]:
        """Return ``(project, created)`` — idempotent and lock-protected.

        If *project_id* already exists the existing Project is returned
        with ``created=False``.
        """
        async with self._project_lock:
            if project_id is None:
                project_id = secrets.token_hex(4)
            if not self._VALID_PROJECT_ID.match(project_id):
                raise ValueError(
                    f"Invalid project_id: {project_id!r} — "
                    f"use only A-Z a-z 0-9 _ - . (max 64 chars)"
                )
            if project_id in self.projects:
                return self.projects[project_id], False

            work_dir = os.path.join(
                self.config.resolved_work_base_dir, project_id
            )
            os.makedirs(work_dir, exist_ok=True)

            project = Project(
                project_id=project_id,
                work_dir=work_dir,
                limiter=self.limiter,
                worker_python=self.config.worker_python,
                plugin_dir=self.config.resolved_plugin_dir,
            )
            self.projects[project_id] = project
            log.info("Opened project %s", project_id)
            return project, True

    async def close_project(self, project_id: str) -> None:
        """Gracefully close then destroy a project."""
        async with self._project_lock:
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

            if os.path.isdir(project.work_dir):
                shutil.rmtree(project.work_dir, ignore_errors=True)

            log.info("Closed project %s", project_id)

    def resolve_project(self, project_id: str) -> Project:
        """Look up a project by ID.  Raises KeyError if not found."""
        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(f"Unknown project: {project_id}")
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
