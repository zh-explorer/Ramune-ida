"""Project — a work context bound to one IDB file.

Owns a WorkerHandle (1:1). Each task is an asyncio.Task
serialized through an execution lock.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ramune_ida.protocol import ErrorInfo, Request, TaskStatus
from ramune_ida.worker_handle import WorkerDead, WorkerHandle

if TYPE_CHECKING:
    from ramune_ida.limiter import Limiter

log = logging.getLogger(__name__)

_task_counter = itertools.count(1)


def _make_task_id() -> str:
    return f"t-{next(_task_counter):06d}"


@dataclass
class Task:
    """A unit of work submitted by the MCP layer."""

    task_id: str
    project: Project
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: ErrorInfo | None = None
    _coro: asyncio.Task[None] | None = field(default=None, repr=False)


class Project:
    """A work context bound to one IDB file.

    Each Project owns one WorkerHandle (1:1). Tasks are serialized
    through _exec_lock — asyncio.Lock acts as the natural FIFO queue.

    The worker instance can be closed gracefully via
    ``execute("close_database")`` (worker saves + exits on its own)
    or killed immediately via ``force_close()``.  Either way, the
    Project stays alive — the next ``execute()`` will spawn a fresh
    worker automatically.
    """

    def __init__(
        self,
        project_id: str,
        exe_path: str,
        idb_path: str,
        work_dir: str,
        limiter: Limiter,
        worker_python: str = "python",
    ) -> None:
        self.project_id = project_id
        self.exe_path = exe_path
        self.idb_path = idb_path
        self.work_dir = work_dir
        self._limiter = limiter
        self._worker_python = worker_python

        self.last_accessed: float = 0.0
        self._handle: WorkerHandle | None = None
        self._exec_lock = asyncio.Lock()
        self._tasks: dict[str, Task] = {}

    def __repr__(self) -> str:
        return f"Project(id={self.project_id!r}, idb={self.idb_path!r})"

    @property
    def has_active_tasks(self) -> bool:
        return any(not t._coro.done() for t in self._tasks.values())

    # ==================================================================
    # Public API
    # ==================================================================

    def _submit(self, method: str, params: dict[str, Any] | None = None) -> Task:
        """Create a Task, enqueue it, and return immediately."""
        task = Task(
            task_id=_make_task_id(),
            project=self,
            method=method,
            params=params or {},
        )
        task._coro = asyncio.create_task(
            self._exec_one(task), name=f"task-{task.task_id}"
        )
        self._tasks[task.task_id] = task
        return task

    async def execute(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Task:
        task = self._submit(method, params)
        self.last_accessed = time.monotonic()

        if timeout is not None and timeout > 0:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task._coro), timeout=timeout
                )
            except asyncio.TimeoutError:
                pass
        else:
            await task._coro

        if task._coro.done():
            self._tasks.pop(task.task_id, None)

        return task

    async def get_task_result(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task is not None and task._coro.done():
            return self._tasks.pop(task_id)
        return None

    def cancel(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task._coro.done():
            return
        was_running = task.status == TaskStatus.RUNNING
        task.status = TaskStatus.CANCELLED
        if was_running and self._handle is not None:
            self._handle.kill()
            self._handle = None
            self._limiter.on_destroyed(self.project_id)
        else:
            task._coro.cancel()

    def force_close(self) -> None:
        """Cancel all tasks and kill the worker immediately.

        Entirely synchronous — never yields to the event loop, so no
        race conditions.  The Project remains usable; subsequent
        ``execute()`` calls will spawn a fresh worker.
        """
        if self._handle is not None:
            self._handle.kill()
            self._handle = None
            self._limiter.on_destroyed(self.project_id)
        for task in self._tasks.values():
            if not task._coro.done():
                task.status = TaskStatus.CANCELLED
                task._coro.cancel()
        self._tasks.clear()

    async def save(self) -> Task:
        """Queue a save_database task (waits for completion)."""
        return await self.execute("save_database")

    # ==================================================================
    # Task execution
    # ==================================================================

    async def _exec_one(self, task: Task) -> None:
        try:
            async with self._exec_lock:
                await self._ensure_worker()
                task.status = TaskStatus.RUNNING
                req = Request(
                    id=task.task_id,
                    method=task.method,
                    params=task.params,
                )
                resp = await self._handle.execute(req)
                if task.status == TaskStatus.CANCELLED:
                    return
                if resp.error:
                    task.status = TaskStatus.FAILED
                    task.error = resp.error
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = resp.result
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
        except WorkerDead:
            if self._handle is not None:
                self._handle = None
                self._limiter.on_destroyed(self.project_id)
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.FAILED
                task.error = ErrorInfo(
                    code=-5, message="worker died during execution"
                )
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = ErrorInfo(code=-5, message=str(exc))

    async def _ensure_worker(self) -> None:
        if self._handle is not None:
            if self._handle.is_alive():
                return
            self._handle.kill()
            self._handle = None
            self._limiter.on_destroyed(self.project_id)
        if not self._limiter.can_spawn:
            raise RuntimeError("no instance available")
        handle = WorkerHandle(python_path=self._worker_python)
        await handle.spawn()
        self._limiter.on_spawned(self.project_id)
        try:
            req = Request(
                id="__open__",
                method="open_database",
                params={"path": self.exe_path},
            )
            resp = await handle.execute(req)
            if resp.error:
                raise RuntimeError(
                    f"open_database failed: {resp.error.message}"
                )
        except Exception:
            handle.kill()
            self._limiter.on_destroyed(self.project_id)
            raise
        self._handle = handle
        log.info(
            "Worker %s ready (total=%d)",
            handle.instance_id,
            self._limiter.instance_count,
        )
