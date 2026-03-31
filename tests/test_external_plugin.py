"""End-to-end test for external plugin discovery and invocation.

Uses the echo_test plugin in tests/plugins/ to verify:
  1. --list-plugins discovers external plugins via RAMUNE_PLUGIN_DIR
  2. Server registers discovered tools as MCP tools
  3. MCP tool calls are forwarded to the worker as PluginInvocations
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
PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "plugins")
PYTHON = sys.executable

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
            [PYTHON, MOCK_WORKER], env=env, cwd=cwd, pass_fds=(child_fd,),
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


from ramune_ida.config import ServerConfig
import ramune_ida.server.app as app_module

_registered = False


@pytest_asyncio.fixture
async def mcp(tmp_path):
    global _registered

    config = ServerConfig(
        worker_python=PYTHON,
        soft_limit=2,
        hard_limit=4,
        auto_save_interval=0,
        work_base_dir=str(tmp_path / "projects"),
    )
    app_module.configure(config)

    if not _registered:
        from ramune_ida.server.plugins import discover_tools, register_plugin_tools
        tools_meta = await discover_tools(PYTHON, plugin_dir=PLUGIN_DIR)
        register_plugin_tools(tools_meta)
        _registered = True

    from ramune_ida.server.state import AppState
    state = AppState(config)
    await state.start()
    app_module._state = state

    yield app_module.mcp

    await state.shutdown()
    app_module._state = None


async def call(mcp_app, name: str, args: dict[str, Any] | None = None) -> dict:
    result = await mcp_app.call_tool(name, args or {})
    if isinstance(result, tuple):
        content_list = result[0]
    elif isinstance(result, list):
        content_list = result
    elif isinstance(result, dict):
        return result
    else:
        raise ValueError(f"Unexpected: {type(result)}: {result}")
    for item in content_list:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise ValueError(f"No text content: {result}")


async def _setup(mcp_app, pid: str) -> str:
    r = await call(mcp_app, "open_project", {"project_id": pid})
    work_dir = r["work_dir"]
    with open(os.path.join(work_dir, "a.bin"), "wb") as f:
        f.write(b"\x00")
    await call(mcp_app, "open_database", {"project_id": pid, "path": "a.bin"})
    return pid


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_echo_test_discovered(mcp):
    """echo_test from external plugin dir is registered as MCP tool."""
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert "echo_test" in names
    assert "echo_write_test" in names
    assert "echo_unsafe_test" in names


@pytest.mark.asyncio
async def test_echo_test_call(mcp):
    """echo_test invocation goes through the full MCP → Worker pipeline."""
    pid = await _setup(mcp, "ep-echo")
    r = await call(mcp, "echo_test", {
        "project_id": pid,
        "message": "hello",
        "repeat": 3,
    })
    assert r["project_id"] == pid
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:echo_test"
    assert r["params"]["message"] == "hello"
    assert r["params"]["repeat"] == 3


@pytest.mark.asyncio
async def test_echo_test_default_param(mcp):
    """Optional params get default values."""
    pid = await _setup(mcp, "ep-default")
    r = await call(mcp, "echo_test", {
        "project_id": pid,
        "message": "world",
    })
    assert r["status"] == "completed"
    assert r["params"]["message"] == "world"


@pytest.mark.asyncio
async def test_echo_write_test(mcp):
    """Write-tagged plugin tool works."""
    pid = await _setup(mcp, "ep-write")
    r = await call(mcp, "echo_write_test", {
        "project_id": pid,
        "value": "test_data",
    })
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:echo_write_test"
    assert r["params"]["value"] == "test_data"


@pytest.mark.asyncio
async def test_echo_unsafe_test(mcp):
    """Unsafe-tagged plugin tool works (no params required)."""
    pid = await _setup(mcp, "ep-unsafe")
    r = await call(mcp, "echo_unsafe_test", {"project_id": pid})
    assert r["status"] == "completed"
    assert r["echo"] == "plugin:echo_unsafe_test"


@pytest.mark.asyncio
async def test_plugin_tools_have_descriptions(mcp):
    """Discovered tools carry their metadata descriptions."""
    tools = await mcp.list_tools()
    echo = next(t for t in tools if t.name == "echo_test")
    assert "echoes back" in echo.description.lower()
