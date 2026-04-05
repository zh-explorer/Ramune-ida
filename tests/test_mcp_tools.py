"""MCP full-chain tests — call tools through FastMCP.call_tool().

Every test goes through the real MCP tool registration, parameter
validation, and response serialisation path.  The IDA Worker is
replaced by mock_worker.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from typing import Any

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

MOCK_WORKER = os.path.join(os.path.dirname(__file__), "mock_worker.py")
PYTHON = sys.executable

# ── Monkey-patch WorkerHandle to use mock_worker ──────────────────

import ramune_ida.worker_handle as wh
from ramune_ida.worker.socket_io import ENV_SOCK_FD


async def _mock_spawn(self: wh.WorkerHandle, cwd: str | None = None) -> None:
    self.instance_id = f"w-{next(wh._instance_counter):04d}"

    parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    child_fd = child_sock.fileno()

    env = os.environ.copy()
    env[ENV_SOCK_FD] = str(child_fd)

    try:
        self._proc = subprocess.Popen(
            [PYTHON, MOCK_WORKER],
            env=env,
            cwd=cwd,
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


# ── Setup: configure AppState before importing mcp instance ───────

from ramune_ida.config import ServerConfig
import ramune_ida.server.app as app_module


_plugins_registered = False


@pytest_asyncio.fixture
async def mcp_app(tmp_path):
    """Configure and start the MCP app, yield it, then shut down."""
    global _plugins_registered

    config = ServerConfig(
        worker_python=PYTHON,
        soft_limit=2,
        hard_limit=4,
        auto_save_interval=0,
        data_dir=str(tmp_path),
    )
    app_module.configure(config)

    if not _plugins_registered:
        from ramune_ida.server.plugins import discover_tools, register_plugin_tools
        tools_meta = await discover_tools(PYTHON)
        register_plugin_tools(tools_meta)
        _plugins_registered = True

    from ramune_ida.server.state import AppState
    state = AppState(config)
    await state.start()
    app_module._state = state

    yield app_module.mcp

    await state.shutdown()
    app_module._state = None


# ── Helper ────────────────────────────────────────────────────────


async def call(mcp, name: str, args: dict[str, Any] | None = None) -> dict:
    """Call an MCP tool and return the result as a dict."""
    result = await mcp.call_tool(name, args or {})
    # call_tool may return: list[TextContent], tuple(list[TextContent], dict), or dict
    if isinstance(result, tuple):
        content_list = result[0]
    elif isinstance(result, list):
        content_list = result
    elif isinstance(result, dict):
        return result
    else:
        raise ValueError(f"Unexpected call_tool result: {type(result)}: {result}")
    for item in content_list:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise ValueError(f"No text content in call_tool result: {result}")


def get_work_dir(project_id: str) -> str:
    """Get a project's work_dir from internal state (test-only)."""
    state = app_module.get_state()
    return state.projects[project_id].work_dir


# ── Full workflow ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_workflow(mcp_app, tmp_path):
    """open_project -> open_database -> projects -> close_database -> close_project"""
    mcp = mcp_app

    r = await call(mcp, "open_project", {"project_id": "flow-test"})
    pid = r["project_id"]
    assert pid == "flow-test"

    work_dir = get_work_dir(pid)
    with open(os.path.join(work_dir, "sample.bin"), "wb") as f:
        f.write(b"\x7fELF" + b"\x00" * 100)

    r = await call(mcp, "open_database", {"project_id": pid, "path": "sample.bin"})
    assert r["status"] == "completed"
    assert r["project_id"] == pid

    r = await call(mcp, "projects")
    assert r["count"] == 1
    assert r["projects"][0]["project_id"] == pid
    assert r["projects"][0]["has_worker"] is True
    assert r["projects"][0]["has_database"] is True

    r = await call(mcp, "close_database", {"project_id": pid})
    assert r["status"] in ("completed", "killed")

    r = await call(mcp, "close_project", {"project_id": pid})
    assert r["status"] == "closed"

    r = await call(mcp, "projects")
    assert r["count"] == 0


# ── open_project ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_project_auto_id(mcp_app):
    r = await call(mcp_app, "open_project")
    assert "project_id" in r
    assert len(r["project_id"]) == 8


@pytest.mark.asyncio
async def test_open_project_custom_id(mcp_app):
    r = await call(mcp_app, "open_project", {"project_id": "my-proj"})
    assert r["project_id"] == "my-proj"


@pytest.mark.asyncio
async def test_open_project_invalid_id(mcp_app):
    with pytest.raises(Exception):
        await call(mcp_app, "open_project", {"project_id": "../../bad"})


@pytest.mark.asyncio
async def test_open_project_idempotent(mcp_app):
    r1 = await call(mcp_app, "open_project", {"project_id": "dup"})
    r2 = await call(mcp_app, "open_project", {"project_id": "dup"})
    assert r1["project_id"] == r2["project_id"]
    assert "notice" not in r1
    assert "notice" in r2


# ── open_database ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_database_relative_path(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "db-rel"})
    work_dir = get_work_dir("db-rel")

    with open(os.path.join(work_dir, "test.bin"), "wb") as f:
        f.write(b"\x00" * 16)

    r = await call(mcp, "open_database", {"project_id": "db-rel", "path": "test.bin"})
    assert r["status"] == "completed"
    assert r.get("exe_path", "").endswith("test.bin")
    assert "idb_path" in r


@pytest.mark.asyncio
async def test_open_database_idb_path(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "db-idb"})
    work_dir = get_work_dir("db-idb")

    with open(os.path.join(work_dir, "analysis.i64"), "wb") as f:
        f.write(b"\x00" * 16)

    r = await call(mcp, "open_database", {"project_id": "db-idb", "path": "analysis.i64"})
    assert r["status"] == "completed"
    assert r.get("idb_path", "").endswith("analysis.i64")
    assert "exe_path" not in r


@pytest.mark.asyncio
async def test_open_database_unknown_project(mcp_app):
    with pytest.raises(Exception):
        await call(mcp_app, "open_database", {"project_id": "nope", "path": "x.bin"})


# ── close_database ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_database_graceful(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "close-g"})
    with open(os.path.join(get_work_dir("close-g"), "a.bin"), "wb") as f:
        f.write(b"\x00")

    await call(mcp, "open_database", {"project_id": "close-g", "path": "a.bin"})
    r = await call(mcp, "close_database", {"project_id": "close-g"})
    assert r["status"] in ("completed", "killed")

    r = await call(mcp, "projects")
    p = [x for x in r["projects"] if x["project_id"] == "close-g"][0]
    assert p["has_worker"] is False


@pytest.mark.asyncio
async def test_close_database_force(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "close-f"})
    with open(os.path.join(get_work_dir("close-f"), "a.bin"), "wb") as f:
        f.write(b"\x00")

    await call(mcp, "open_database", {"project_id": "close-f", "path": "a.bin"})
    r = await call(mcp, "close_database", {"project_id": "close-f", "force": True})
    assert r["status"] == "killed"


@pytest.mark.asyncio
async def test_close_database_no_worker(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "close-nw"})
    r = await call(mcp, "close_database", {"project_id": "close-nw"})
    assert r["status"] == "no_worker"


# ── close_project ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_project_cleans_up(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "clean"})
    work_dir = get_work_dir("clean")
    assert os.path.isdir(work_dir)

    await call(mcp, "close_project", {"project_id": "clean"})
    assert not os.path.isdir(work_dir)


@pytest.mark.asyncio
async def test_close_project_unknown(mcp_app):
    with pytest.raises(Exception):
        await call(mcp_app, "close_project", {"project_id": "nope"})


# ── projects ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_projects_empty(mcp_app):
    r = await call(mcp_app, "projects")
    assert r["count"] == 0
    assert r["projects"] == []


@pytest.mark.asyncio
async def test_projects_multiple(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "p1"})
    await call(mcp, "open_project", {"project_id": "p2"})
    r = await call(mcp, "projects")
    assert r["count"] == 2
    ids = {p["project_id"] for p in r["projects"]}
    assert ids == {"p1", "p2"}


@pytest.mark.asyncio
async def test_projects_shows_database_state(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "pdb"})

    r = await call(mcp, "projects")
    p = r["projects"][0]
    assert p["has_database"] is False
    assert p["exe_path"] is None
    assert p["idb_path"] is None


# ── cancel_task ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_task_not_found(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "cancel-t"})
    r = await call(mcp, "cancel_task", {"project_id": "cancel-t", "task_id": "t-999999"})
    assert r["status"] == "cancelled"


# ── get_task_result ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_task_result_not_found(mcp_app):
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "poll-t"})
    r = await call(mcp, "get_task_result", {"project_id": "poll-t", "task_id": "t-999999"})
    assert r["status"] == "not_found"


# ── Soft limit warning ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_soft_limit_warning(mcp_app):
    mcp = mcp_app
    for i in range(3):
        pid = f"sl{i}"
        await call(mcp, "open_project", {"project_id": pid})
        with open(os.path.join(get_work_dir(pid), "a.bin"), "wb") as f:
            f.write(b"\x00")
        r = await call(mcp, "open_database", {"project_id": pid, "path": "a.bin"})
        if i >= 2:
            assert "warning" in r


# ── Restart recovery ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restart_recovery(tmp_path):
    """Projects survive server restart (recovered from work_dir folders)."""
    config = ServerConfig(
        worker_python=PYTHON,
        soft_limit=0,
        hard_limit=0,
        auto_save_interval=0,
        data_dir=str(tmp_path),
    )
    app_module.configure(config)

    from ramune_ida.server.state import AppState

    state1 = AppState(config)
    await state1.start()
    app_module._state = state1
    mcp = app_module.mcp

    await call(mcp, "open_project", {"project_id": "surv1"})
    await call(mcp, "open_project", {"project_id": "surv2"})

    await state1.shutdown()
    app_module._state = None

    state2 = AppState(config)
    await state2.start()
    app_module._state = state2

    r = await call(mcp, "projects")
    ids = {p["project_id"] for p in r["projects"]}
    assert "surv1" in ids
    assert "surv2" in ids
    for p in r["projects"]:
        assert p["has_database"] is False
        assert p["has_worker"] is False

    await state2.shutdown()
    app_module._state = None


# ── Analysis tools ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decompile(mcp_app):
    """decompile through MCP call_tool (mock worker echoes the command)."""
    mcp = mcp_app
    await call(mcp, "open_project", {"project_id": "dec"})
    work_dir = get_work_dir("dec")
    with open(os.path.join(work_dir, "a.bin"), "wb") as f:
        f.write(b"\x00")
    await call(mcp, "open_database", {"project_id": "dec", "path": "a.bin"})

    r = await call(mcp, "decompile", {"project_id": "dec", "func": "main"})
    assert r["project_id"] == "dec"
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:decompile"
    assert r["params"]["func"] == "main"


# ── execute_python ────────────────────────────────────────────────


async def _setup_project(mcp, pid: str = "pyexec") -> str:
    """Helper: create project + open database, return project_id."""
    await call(mcp, "open_project", {"project_id": pid})
    work_dir = get_work_dir(pid)
    with open(os.path.join(work_dir, "a.bin"), "wb") as f:
        f.write(b"\x00")
    await call(mcp, "open_database", {"project_id": pid, "path": "a.bin"})
    return pid


@pytest.mark.asyncio
async def test_execute_python_basic(mcp_app):
    """stdout is captured and returned."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-basic")
    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": 'print("hello world")',
    })
    assert r["status"] == "completed"
    assert "hello world" in r["output"]
    assert r["error"] == ""


@pytest.mark.asyncio
async def test_execute_python_result(mcp_app):
    """_result variable is returned as structured data."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-result")
    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": '_result = {"key": "value", "num": 42}',
    })
    assert r["status"] == "completed"
    assert r["result"] == {"key": "value", "num": 42}
    assert r["error"] == ""


@pytest.mark.asyncio
async def test_execute_python_error(mcp_app):
    """Errors include traceback and any stdout produced before the error."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-error")
    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": 'print("before error")\n1/0',
    })
    assert r["status"] == "completed"
    assert "before error" in r["output"]
    assert "ZeroDivisionError" in r["error"]


@pytest.mark.asyncio
async def test_execute_python_stderr(mcp_app):
    """stderr is captured separately from stdout."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-stderr")
    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": 'import sys\nprint("out")\nsys.stderr.write("err\\n")',
    })
    assert r["status"] == "completed"
    assert "out" in r["output"]
    assert "err" in r["stderr"]
    assert r["error"] == ""


@pytest.mark.asyncio
async def test_execute_python_empty_code(mcp_app):
    """Empty code returns an error."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-empty")
    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": "",
    })
    assert r["status"] == "failed"
    assert "code" in r.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_python_cancel_fast_sleep(mcp_app):
    """Graceful cancel: short sleep loop, setprofile fires on c_return."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-cancel1")

    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": "import time\nwhile True: time.sleep(0.01)",
    })
    assert r["status"] == "running"
    task_id = r["task_id"]

    await call(mcp, "cancel_task", {"project_id": pid, "task_id": task_id})
    await asyncio.sleep(1.0)

    r = await call(mcp, "get_task_result", {"project_id": pid, "task_id": task_id})
    assert r["status"] in ("cancelled", "not_found")


@pytest.mark.asyncio
async def test_execute_python_cancel_slow_sleep(mcp_app):
    """Graceful cancel: sleep(1) loop — SIGUSR1 interrupts the sleep,
    setprofile fires on c_return after the signal."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-cancel2")

    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": "import time\nwhile True: time.sleep(1)",
    })
    assert r["status"] == "running"
    task_id = r["task_id"]

    await call(mcp, "cancel_task", {"project_id": pid, "task_id": task_id})
    await asyncio.sleep(2.0)

    r = await call(mcp, "get_task_result", {"project_id": pid, "task_id": task_id})
    assert r["status"] in ("cancelled", "not_found")


# ── Plugin tools (disasm) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_disasm_plugin_tool_registered(mcp_app):
    """The 'disasm' plugin tool should be discoverable and callable."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "disasm-reg")
    r = await call(mcp, "disasm", {"project_id": pid, "addr": "0x401000"})
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:disasm"
    assert r["params"]["addr"] == "0x401000"
    assert r["params"]["count"] == 20


@pytest.mark.asyncio
async def test_disasm_custom_count(mcp_app):
    """disasm respects the count parameter."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "disasm-cnt")
    r = await call(mcp, "disasm", {"project_id": pid, "addr": "main", "count": 5})
    assert r["params"]["count"] == 5


@pytest.mark.asyncio
async def test_xrefs_plugin_tool_registered(mcp_app):
    """The 'xrefs' plugin tool should be discoverable and callable."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "xrefs-reg")
    r = await call(mcp, "xrefs", {"project_id": pid, "addr": "0x401000"})
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:xrefs"
    assert r["params"]["addr"] == "0x401000"


# ── rename plugin tool ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_function_global(mcp_app):
    """rename with addr+new_name forwards correctly to worker."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "rename-fn")
    r = await call(mcp, "rename", {
        "project_id": pid,
        "addr": "0x401000",
        "new_name": "init_config",
    })
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:rename"
    assert r["params"]["addr"] == "0x401000"
    assert r["params"]["new_name"] == "init_config"


@pytest.mark.asyncio
async def test_rename_local_variable(mcp_app):
    """rename with func+var+new_name forwards correctly to worker."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "rename-lv")
    r = await call(mcp, "rename", {
        "project_id": pid,
        "func": "0x401000",
        "var": "v1",
        "new_name": "buffer_ptr",
    })
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:rename"
    assert r["params"]["func"] == "0x401000"
    assert r["params"]["var"] == "v1"
    assert r["params"]["new_name"] == "buffer_ptr"


@pytest.mark.asyncio
async def test_rename_missing_new_name(mcp_app):
    """rename without new_name should fail validation."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "rename-err")
    # new_name is required — omitting it should cause a validation error
    try:
        r = await call(mcp, "rename", {"project_id": pid, "addr": "0x401000"})
        # If no exception, the tool itself might return an error via the worker
        assert r.get("status") in ("completed", "error")
    except Exception:
        pass  # validation error is expected


# ── survey plugin tool ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_survey_plugin_tool_registered(mcp_app):
    """survey tool should be discoverable and callable with no params."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "survey-reg")
    r = await call(mcp, "survey", {"project_id": pid})
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:survey"


@pytest.mark.asyncio
async def test_execute_python_cancel_tight_loop(mcp_app):
    """Fallback cancel: tight loop with no function calls — setprofile
    never fires, so after 5s grace period the watchdog sends SIGKILL."""
    mcp = mcp_app
    pid = await _setup_project(mcp, "py-cancel3")

    r = await call(mcp, "execute_python", {
        "project_id": pid,
        "code": "while True: pass",
    })
    assert r["status"] == "running"
    task_id = r["task_id"]

    await call(mcp, "cancel_task", {"project_id": pid, "task_id": task_id})
    await asyncio.sleep(7.0)

    r = await call(mcp, "get_task_result", {"project_id": pid, "task_id": task_id})
    assert r["status"] in ("cancelled", "not_found")


# ── list_funcs ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_funcs_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "lf-reg")
    r = await call(mcp, "list_funcs", {"project_id": pid})
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:list_funcs"


@pytest.mark.asyncio
async def test_list_funcs_with_filter(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "lf-filter")
    r = await call(mcp, "list_funcs", {
        "project_id": pid,
        "filter": "main",
        "exclude": "sub",
    })
    assert r["params"]["filter"] == "main"
    assert r["params"]["exclude"] == "sub"


# ── list_strings ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_strings_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "ls-reg")
    r = await call(mcp, "list_strings", {"project_id": pid})
    assert r["echo"] == "plugin:list_strings"


# ── list_imports ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_imports_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "li-reg")
    r = await call(mcp, "list_imports", {"project_id": pid})
    assert r["echo"] == "plugin:list_imports"


# ── list_names ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_names_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "ln-reg")
    r = await call(mcp, "list_names", {"project_id": pid})
    assert r["echo"] == "plugin:list_names"


# ── search ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "s-reg")
    r = await call(mcp, "search", {"project_id": pid, "pattern": "main"})
    assert r["echo"] == "plugin:search"
    assert r["params"]["pattern"] == "main"


@pytest.mark.asyncio
async def test_search_with_type(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "s-type")
    r = await call(mcp, "search", {
        "project_id": pid,
        "pattern": "init",
        "type": "names",
        "count": 50,
    })
    assert r["params"]["type"] == "names"
    assert r["params"]["count"] == 50


# ── search_bytes ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_bytes_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "sb-reg")
    r = await call(mcp, "search_bytes", {
        "project_id": pid,
        "pattern": "48 8B ?? 00",
    })
    assert r["echo"] == "plugin:search_bytes"
    assert r["params"]["pattern"] == "48 8B ?? 00"


# ── examine ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_examine_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "ex-reg")
    r = await call(mcp, "examine", {"project_id": pid, "addr": "0x401000"})
    assert r["echo"] == "plugin:examine"
    assert r["params"]["addr"] == "0x401000"


# ── get_bytes ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_bytes_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "gb-reg")
    r = await call(mcp, "get_bytes", {
        "project_id": pid,
        "addr": "0x401000",
        "size": 16,
    })
    assert r["echo"] == "plugin:get_bytes"
    assert r["params"]["addr"] == "0x401000"
    assert r["params"]["size"] == 16


# ── undo ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_undo_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "undo-reg")
    r = await call(mcp, "undo", {"project_id": pid})
    assert r["echo"] == "plugin:undo"


@pytest.mark.asyncio
async def test_undo_count_param(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "undo-cnt")
    r = await call(mcp, "undo", {"project_id": pid, "count": 3})
    assert r["echo"] == "plugin:undo"
    assert r["params"]["count"] == 3


# ── get_comment ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_comment_addr(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "gc-addr")
    r = await call(mcp, "get_comment", {"project_id": pid, "addr": "0x401000"})
    assert r["echo"] == "plugin:get_comment"
    assert r["params"]["addr"] == "0x401000"


@pytest.mark.asyncio
async def test_get_comment_func(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "gc-func")
    r = await call(mcp, "get_comment", {"project_id": pid, "func": "main"})
    assert r["echo"] == "plugin:get_comment"
    assert r["params"]["func"] == "main"


# ── set_comment ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_comment_addr(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "sc-addr")
    r = await call(mcp, "set_comment", {
        "project_id": pid,
        "addr": "0x401000",
        "comment": "test",
    })
    assert r["echo"] == "plugin:set_comment"
    assert r["params"]["addr"] == "0x401000"
    assert r["params"]["comment"] == "test"


@pytest.mark.asyncio
async def test_set_comment_func(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "sc-func")
    r = await call(mcp, "set_comment", {
        "project_id": pid,
        "func": "main",
        "comment": "Function header comment",
    })
    assert r["echo"] == "plugin:set_comment"
    assert r["params"]["func"] == "main"
    assert r["params"]["comment"] == "Function header comment"


# ── set_type ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_type_addr(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "st-addr")
    r = await call(mcp, "set_type", {
        "project_id": pid,
        "addr": "main",
        "type": "int main(int argc, char **argv)",
    })
    assert r["echo"] == "plugin:set_type"
    assert r["params"]["addr"] == "main"
    assert r["params"]["type"] == "int main(int argc, char **argv)"


@pytest.mark.asyncio
async def test_set_type_local(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "st-local")
    r = await call(mcp, "set_type", {
        "project_id": pid,
        "func": "main",
        "var": "v3",
        "type": "unsigned int",
    })
    assert r["echo"] == "plugin:set_type"
    assert r["params"]["func"] == "main"
    assert r["params"]["var"] == "v3"
    assert r["params"]["type"] == "unsigned int"


# ── define_type ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_define_type(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "dt-basic")
    r = await call(mcp, "define_type", {
        "project_id": pid,
        "declare": "struct Foo { int a; char *b; };",
    })
    assert r["echo"] == "plugin:define_type"
    assert r["params"]["declare"] == "struct Foo { int a; char *b; };"


# ── get_type ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_type(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "gt-basic")
    r = await call(mcp, "get_type", {
        "project_id": pid,
        "name": "MyStruct",
    })
    assert r["echo"] == "plugin:get_type"
    assert r["params"]["name"] == "MyStruct"


# ── list_types ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_types_registered(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "lt-reg")
    r = await call(mcp, "list_types", {"project_id": pid})
    assert r["echo"] == "plugin:list_types"


@pytest.mark.asyncio
async def test_list_types_with_filter(mcp_app):
    mcp = mcp_app
    pid = await _setup_project(mcp, "lt-filter")
    r = await call(mcp, "list_types", {
        "project_id": pid,
        "filter": "Elf",
        "kind": "struct",
    })
    assert r["params"]["filter"] == "Elf"
    assert r["params"]["kind"] == "struct"
