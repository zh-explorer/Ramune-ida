"""Unit tests for Project + Limiter."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import ClassVar

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ramune_ida.commands import Command, Decompile, Ping
from ramune_ida.protocol import TaskStatus
from ramune_ida.project import Project, Task
from ramune_ida.limiter import Limiter

MOCK_WORKER = os.path.join(os.path.dirname(__file__), "mock_worker.py")
PYTHON = sys.executable


# ------------------------------------------------------------------
# Test-only command for the mock_worker "slow_command" handler
# ------------------------------------------------------------------

class _FakeMethod:
    value = "slow_command"


@dataclass(slots=True)
class _SlowCommand(Command):
    method: ClassVar = _FakeMethod()  # type: ignore[assignment]
    delay: int = 5


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _limiter(**kw) -> Limiter:
    defaults = dict(soft_limit=0, hard_limit=0)
    defaults.update(kw)
    return Limiter(**defaults)


def _project(
    lim: Limiter, pid: str = "p-001", path: str = "/tmp/test.i64"
) -> Project:
    return Project(
        project_id=pid,
        exe_path=f"/tmp/{pid}.exe",
        idb_path=path,
        work_dir=f"/tmp/work/{pid}",
        limiter=lim,
        worker_python=PYTHON,
    )


# ------------------------------------------------------------------
# Monkey-patch WorkerHandle.spawn to use mock_worker.py
# ------------------------------------------------------------------

import socket
import subprocess

import ramune_ida.worker_handle as wh
from ramune_ida.worker.socket_io import ENV_SOCK_FD


async def _mock_spawn(self: wh.WorkerHandle) -> None:
    self.instance_id = f"w-{next(wh._instance_counter):04d}"

    parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    child_fd = child_sock.fileno()

    env = os.environ.copy()
    env[ENV_SOCK_FD] = str(child_fd)

    try:
        self._proc = subprocess.Popen(
            [PYTHON, MOCK_WORKER],
            env=env,
            pass_fds=(child_fd,),
        )
    except Exception:
        parent_sock.close()
        child_sock.close()
        raise
    finally:
        child_sock.close()

    parent_sock.setblocking(False)
    self._reader, self._writer = await asyncio.open_connection(sock=parent_sock)

    ready = await self._recv()
    if ready.error:
        raise wh.WorkerDead(f"mock worker failed: {ready.error.message}")


@pytest.fixture(autouse=True)
def _patch_spawn(monkeypatch):
    monkeypatch.setattr(wh.WorkerHandle, "spawn", _mock_spawn)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_basic():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        task = await p.execute(Decompile(func="main"))
        assert isinstance(task, Task)
        assert task.status == TaskStatus.COMPLETED
        assert task.result["echo"] == "decompile"
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_lazy_spawn():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        assert lim.instance_count == 0
        await p.execute(Ping())
        assert lim.instance_count == 1
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_project_keeps_handle():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        await p.execute(Ping())
        h1 = p._handle
        await p.execute(Ping())
        h2 = p._handle
        assert h1 is h2
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_each_project_own_handle():
    lim = _limiter()
    p1 = _project(lim, "p1", "/tmp/a.i64")
    p2 = _project(lim, "p2", "/tmp/b.i64")
    try:
        await p1.execute(Ping())
        await p2.execute(Ping())
        assert p1._handle is not p2._handle
        assert lim.instance_count == 2
    finally:
        p1.force_close()
        p2.force_close()


@pytest.mark.asyncio
async def test_hard_limit():
    lim = _limiter(hard_limit=1)
    p1 = _project(lim, "p1", "/tmp/a.i64")
    p2 = _project(lim, "p2", "/tmp/b.i64")
    try:
        t1 = await p1.execute(Ping())
        assert t1.status == TaskStatus.COMPLETED

        t2 = await p2.execute(Ping())
        assert t2.status == TaskStatus.FAILED
        assert "no instance" in t2.error.message
    finally:
        p1.force_close()


@pytest.mark.asyncio
async def test_over_soft_limit():
    lim = _limiter(soft_limit=2, hard_limit=4)
    projects = [_project(lim, f"p{i}", f"/tmp/{i}.i64") for i in range(3)]
    try:
        await projects[0].execute(Ping())
        await projects[1].execute(Ping())
        assert not lim.over_soft_limit

        await projects[2].execute(Ping())
        assert lim.over_soft_limit
        assert lim.instance_count == 3

        projects[0].force_close()
        assert not lim.over_soft_limit
    finally:
        for p in projects:
            p.force_close()


@pytest.mark.asyncio
async def test_unlimited():
    lim = _limiter()
    projects = [_project(lim, f"p{i}", f"/tmp/{i}.i64") for i in range(5)]
    try:
        for p in projects:
            await p.execute(Ping())
        assert lim.instance_count == 5
    finally:
        for p in projects:
            p.force_close()


@pytest.mark.asyncio
async def test_force_close():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    await p.execute(Ping())
    assert lim.instance_count == 1

    p.force_close()
    assert p._handle is None
    assert lim.instance_count == 0


@pytest.mark.asyncio
async def test_execute_timeout():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        task = await p.execute(_SlowCommand(delay=3), timeout=0.5)
        assert task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)

        await asyncio.sleep(4)

        fetched = await p.get_task_result(task.task_id)
        assert fetched is not None
        assert fetched.status == TaskStatus.COMPLETED
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_cancel_running():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        task = await p.execute(_SlowCommand(delay=30), timeout=0.5)
        old_iid = p._handle.instance_id

        p.cancel_task(task.task_id)
        await task._coro

        assert task.status == TaskStatus.CANCELLED
        assert p._handle is None

        t2 = await p.execute(Ping())
        assert t2.status == TaskStatus.COMPLETED
        assert p._handle.instance_id != old_iid
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_sticky_dispatch():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        t1 = await p.execute(Ping())
        h1 = p._handle
        t2 = await p.execute(Decompile(func="foo"))
        h2 = p._handle

        assert t1.status == TaskStatus.COMPLETED
        assert t2.status == TaskStatus.COMPLETED
        assert h1 is h2
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_done_cleanup():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        task = await p.execute(Ping())
        assert task.status == TaskStatus.COMPLETED
        assert task.task_id not in p._tasks
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_save():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        await p.execute(Ping())
        await p.save()
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_task_to_dict():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        task = await p.execute(Ping())
        d = task.to_dict()
        assert d["task_id"] == task.task_id
        assert d["method"] == "ping"
        assert d["status"] == "completed"
        assert "result" in d
    finally:
        p.force_close()


@pytest.mark.asyncio
async def test_task_is_done():
    lim = _limiter()
    p = _project(lim, "p1", "/tmp/a.i64")
    try:
        task = await p.execute(Ping())
        assert task.is_done
        assert task.error is None
    finally:
        p.force_close()
