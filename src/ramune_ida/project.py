"""Project — a work context for reverse engineering.

A Project is a workspace (work_dir + project_id).  It may or may not
have a database (IDB) open.  Call ``set_database(path)`` before the
first ``execute()`` to bind a binary/IDB.

Owns a WorkerHandle (1:1). Each task is an asyncio.Task
serialized through an execution lock.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import signal
import time
from typing import Any, TYPE_CHECKING

from ramune_ida.commands import Command, OpenDatabase, SaveDatabase
from ramune_ida.protocol import ErrorCode, ErrorInfo, Method, TaskStatus
from ramune_ida.worker_handle import WorkerDead, WorkerHandle

if TYPE_CHECKING:
    from ramune_ida.limiter import Limiter

log = logging.getLogger(__name__)

_task_counter = itertools.count(1)


def _make_task_id() -> str:
    return f"t-{next(_task_counter):06d}"


# ---------------------------------------------------------------------------
# Task — encapsulated unit of work
# ---------------------------------------------------------------------------

class Task:
    """A unit of work submitted by the MCP layer.

    All attributes are read-only properties.  State transitions go
    through explicit methods (``start``, ``complete``, ``fail``,
    ``cancel``) so the lifecycle is always consistent.
    """

    __slots__ = (
        "_task_id", "_command", "_status",
        "_result", "_error", "_coro",
        "_cancel_requested",
    )

    def __init__(self, task_id: str, command: Command) -> None:
        self._task_id = task_id
        self._command = command
        self._status = TaskStatus.PENDING
        self._result: Any = None
        self._error: ErrorInfo | None = None
        self._coro: asyncio.Task[None] | None = None
        self._cancel_requested = False

    def __repr__(self) -> str:
        return f"Task({self._task_id!r}, {self._command.method.value}, {self._status.value})"

    # -- Read-only properties (for MCP layer) -------------------------------

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def command(self) -> Command:
        return self._command

    @property
    def method(self) -> Method:
        return self._command.method

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def result(self) -> Any:
        return self._result

    @property
    def error(self) -> ErrorInfo | None:
        return self._error

    @property
    def is_done(self) -> bool:
        return self._coro is not None and self._coro.done()

    # -- State transition methods (for Project internally) ------------------

    def start(self) -> None:
        self._status = TaskStatus.RUNNING

    def complete(self, result: Any) -> None:
        self._status = TaskStatus.COMPLETED
        self._result = result

    def fail(self, error: ErrorInfo) -> None:
        self._status = TaskStatus.FAILED
        self._error = error

    def cancel(self, *, kill_coro: bool = True) -> None:
        self._status = TaskStatus.CANCELLED
        if kill_coro and self._coro is not None and not self._coro.done():
            self._coro.cancel()

    # -- Serialisation for MCP layer ----------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Standard dict representation for polling / internal use."""
        d: dict[str, Any] = {
            "task_id": self._task_id,
            "method": self._command.method.value,
            "status": self._status.value,
        }
        if self._result is not None:
            d["result"] = self._result
        if self._error is not None:
            d["error"] = {"code": self._error.code, "message": self._error.message}
        return d

    def to_mcp_result(self, project_id: str) -> dict[str, Any]:
        """Flatten task into the standard MCP tool response dict.

        Unlike :meth:`to_dict` (which nests ``result``), this merges
        the worker result into the top-level dict — the format every
        MCP tool is expected to return.
        """
        result: dict[str, Any] = {
            "project_id": project_id,
            "status": self._status.value,
        }
        if self._result is not None:
            result.update(self._result)
        if self._error is not None:
            result["error"] = self._error.message
        if not self.is_done:
            result["task_id"] = self._task_id
        return result

    # -- Internal (set by Project) ------------------------------------------

    def _bind_coro(self, coro: asyncio.Task[None]) -> None:
        self._coro = coro


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class Project:
    """A work context bound to one IDB file.

    Each Project owns one WorkerHandle (1:1). Tasks are serialized
    through _exec_lock — asyncio.Lock acts as the natural FIFO queue.

    The worker instance can be closed gracefully via
    ``execute(CloseDatabase())`` (worker saves + exits on its own)
    or killed immediately via ``force_close()``.  Either way, the
    Project stays alive — the next ``execute()`` will spawn a fresh
    worker automatically.
    """

    def __init__(
        self,
        project_id: str,
        work_dir: str,
        limiter: Limiter,
        worker_python: str = "python",
        plugin_dir: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.work_dir = work_dir
        self._limiter = limiter
        self._worker_python = worker_python
        self._plugin_dir = plugin_dir

        self.exe_path: str | None = None
        self.idb_path: str | None = None

        self.last_accessed: float = 0.0
        self._handle: WorkerHandle | None = None
        self._exec_lock = asyncio.Lock()
        self._tasks: dict[str, Task] = {}

    def set_database(self, path: str) -> None:
        """Bind a binary or IDB to this project.

        If *path* is an IDB (.i64/.idb), open it directly.
        Otherwise treat it as a binary — IDA creates a new IDB from it.
        """
        if path.lower().endswith((".i64", ".idb")):
            self.idb_path = path
            self.exe_path = None
        else:
            self.exe_path = path
            self.idb_path = os.path.splitext(path)[0] + ".i64"

    @property
    def has_database(self) -> bool:
        return self.idb_path is not None or self.exe_path is not None

    @property
    def open_path(self) -> str | None:
        """Path to pass to idapro.open_database().

        Prefers an existing IDB; falls back to the binary.
        """
        if self.idb_path and os.path.isfile(self.idb_path):
            return self.idb_path
        return self.exe_path

    def __repr__(self) -> str:
        return f"Project(id={self.project_id!r}, exe={self.exe_path!r}, idb={self.idb_path!r})"

    @property
    def has_active_tasks(self) -> bool:
        return any(not t.is_done for t in self._tasks.values())

    # ==================================================================
    # Public API
    # ==================================================================

    def _submit(self, cmd: Command) -> Task:
        """Create a Task, enqueue it, and return immediately."""
        task = Task(task_id=_make_task_id(), command=cmd)
        task._bind_coro(
            asyncio.create_task(self._exec_one(task), name=f"task-{task.task_id}")
        )
        self._tasks[task.task_id] = task
        return task

    async def execute(self, cmd: Command, timeout: float | None = None) -> Task:
        """Submit a command and optionally wait for completion."""
        task = self._submit(cmd)
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

        if task.is_done:
            self._tasks.pop(task.task_id, None)

        return task

    async def get_task_result(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task is not None and task.is_done:
            return self._tasks.pop(task_id)
        return None

    def cancel_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.is_done:
            return
        if task.status == TaskStatus.RUNNING and self._handle is not None:
            task._cancel_requested = True
            self._handle.send_signal(signal.SIGUSR1)
            asyncio.ensure_future(self._delayed_kill(task))
        else:
            task.cancel()

    def force_close(self) -> None:
        """Cancel all tasks and kill the worker immediately."""
        if self._handle is not None:
            self._handle.kill()
            self._handle = None
            self._limiter.on_destroyed(self.project_id)
        for task in self._tasks.values():
            if not task.is_done:
                task.cancel()
        self._tasks.clear()

    async def _delayed_kill(self, task: Task, grace: float = 5.0) -> None:
        """Watchdog: if the worker doesn't respond within *grace* seconds
        after SIGUSR1, force-kill it so the cancel actually takes effect."""
        await asyncio.sleep(grace)
        if task.is_done:
            return
        log.warning(
            "Graceful cancel timed out for %s, killing worker",
            task.task_id,
        )
        if self._handle is not None:
            self._handle.kill()
            self._handle = None
            self._limiter.on_destroyed(self.project_id)

    async def save(self) -> Task:
        """Queue a save_database task (waits for completion).

        Flushes to IDA component files and also packs a .i64 snapshot
        so that crash recovery can fall back to it.
        """
        return await self.execute(SaveDatabase(idb_path=self.idb_path))

    # ==================================================================
    # Task execution
    # ==================================================================

    async def _exec_one(self, task: Task) -> None:
        try:
            async with self._exec_lock:
                await self._ensure_worker()
                task.start()
                req = task.command.to_request(task.task_id)
                resp = await self._handle.execute(req)
                if task.status == TaskStatus.CANCELLED:
                    return
                if task._cancel_requested:
                    task.cancel(kill_coro=False)
                    return
                if resp.error:
                    task.fail(resp.error)
                else:
                    task.complete(resp.result)
        except asyncio.CancelledError:
            task.cancel()
        except WorkerDead:
            if self._handle is not None:
                self._handle.kill()
                self._handle = None
                self._limiter.on_destroyed(self.project_id)
            if task._cancel_requested:
                task.cancel(kill_coro=False)
            elif task.status != TaskStatus.CANCELLED:
                task.fail(ErrorInfo(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=(
                        "Worker crashed during execution. "
                        "Changes since last auto-save may be lost. "
                        "The next command will automatically restart the worker."
                    ),
                ))
        except Exception as exc:
            task.fail(ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message=str(exc)))

    async def _ensure_worker(self) -> None:
        if self._handle is not None:
            if self._handle.is_alive():
                return
            self._handle.kill()
            self._handle = None
            self._limiter.on_destroyed(self.project_id)
        if self.open_path is None:
            raise RuntimeError(
                "No database opened — call open_database first"
            )
        if not self._limiter.can_spawn:
            raise RuntimeError("no instance available")
        handle = WorkerHandle(python_path=self._worker_python, plugin_dir=self._plugin_dir)
        await handle.spawn(cwd=self.work_dir)
        self._limiter.on_spawned(self.project_id)
        try:
            req = OpenDatabase(path=self.open_path).to_request("__open__")
            resp = await handle.execute(req)
            if resp.error:
                raise RuntimeError(
                    f"open_database failed: {resp.error.message}"
                )
            save_req = SaveDatabase(idb_path=self.idb_path).to_request("__save_init__")
            await handle.execute(save_req)
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
