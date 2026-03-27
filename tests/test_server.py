"""Smoke tests for the MCP server framework.

Tests cover:
  - ServerConfig
  - OutputStore
  - AppState project lifecycle (with mock workers)
  - CLI transport URL parsing
  - Tool / resource / route registration on the FastMCP instance
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ramune_ida.config import ServerConfig
from ramune_ida.server.output import OutputStore

MOCK_WORKER = os.path.join(os.path.dirname(__file__), "mock_worker.py")
PYTHON = sys.executable


# ── ServerConfig ──────────────────────────────────────────────────


class TestServerConfig:
    def test_defaults(self):
        cfg = ServerConfig()
        assert cfg.soft_limit == 4
        assert cfg.hard_limit == 8
        assert cfg.auto_save_interval == 300.0

    def test_resolved_work_base_dir(self):
        cfg = ServerConfig(work_base_dir="~/test-dir")
        resolved = cfg.resolved_work_base_dir
        assert "~" not in resolved
        assert resolved.endswith("test-dir")


# ── OutputStore ───────────────────────────────────────────────────


class TestOutputStore:
    PID = "test-project"

    @pytest.fixture
    def out_dir(self, tmp_path):
        return str(tmp_path / "outputs")

    @pytest.fixture
    def store(self):
        return OutputStore(max_length=10)

    def test_no_truncation(self, store, out_dir):
        text = "short text"
        result, url = store.truncate_if_needed(text, self.PID, out_dir)
        assert result == text
        assert url is None

    def test_truncation(self, store, out_dir):
        text = "a" * 50
        result, url = store.truncate_if_needed(text, self.PID, out_dir)
        assert result.startswith("a" * 10)
        assert "truncated" in result
        assert url is not None
        assert f"/files/{self.PID}/outputs/" in url

    def test_writes_to_disk(self, store, out_dir, tmp_path):
        text = "z" * 50
        _, url = store.truncate_if_needed(text, self.PID, out_dir)
        output_id = url.split("/")[-1].replace(".txt", "")
        path = tmp_path / "outputs" / f"{output_id}.txt"
        assert path.is_file()
        assert path.read_text() == text

    def test_two_level_index(self, store, out_dir):
        store.truncate_if_needed("a" * 50, "proj-a", out_dir)
        store.truncate_if_needed("b" * 50, "proj-b", out_dir)
        assert "proj-a" in store._index
        assert "proj-b" in store._index
        assert len(store._index["proj-a"]) == 1
        assert len(store._index["proj-b"]) == 1

    def test_discard_project(self, store, out_dir):
        store.truncate_if_needed("a" * 50, self.PID, out_dir)
        store.truncate_if_needed("b" * 50, self.PID, out_dir)
        assert len(store._index[self.PID]) == 2
        store.discard_project(self.PID)
        assert self.PID not in store._index

    def test_eviction(self, tmp_path):
        out_dir = str(tmp_path / "outputs")
        store = OutputStore(max_length=10, max_outputs_per_project=3)
        paths = []
        for i in range(5):
            _, url = store.truncate_if_needed(f"{'x' * 50}_{i}", self.PID, out_dir)
            paths.append(url)
        assert len(store._index[self.PID]) == 3
        assert not os.path.isfile(os.path.join(out_dir, os.path.basename(paths[0])))
        assert not os.path.isfile(os.path.join(out_dir, os.path.basename(paths[1])))
        assert os.path.isfile(os.path.join(out_dir, os.path.basename(paths[2])))

    def test_list_outputs(self, store, out_dir):
        store.truncate_if_needed("a" * 50, self.PID, out_dir)
        listing = store.list_outputs(self.PID)
        assert len(listing) == 1
        assert store.list_outputs("nonexistent") == {}

    def test_process_recursive(self, store, out_dir):
        data = {
            "short": "ok",
            "long": "a" * 50,
            "nested": {"deep": "b" * 50},
            "items": ["c" * 50, "tiny"],
            "number": 42,
        }
        result = store.process(data, self.PID, out_dir)
        assert result["short"] == "ok"
        assert "truncated" in result["long"]
        assert "truncated" in result["nested"]["deep"]
        assert "truncated" in result["items"][0]
        assert result["items"][1] == "tiny"
        assert result["number"] == 42


# ── AppState ──────────────────────────────────────────────────────


class TestAppState:
    @pytest.fixture
    def tmp_work_dir(self, tmp_path):
        return str(tmp_path / "projects")

    @pytest.fixture
    def config(self, tmp_work_dir):
        return ServerConfig(
            worker_python=PYTHON,
            soft_limit=2,
            hard_limit=4,
            auto_save_interval=0,
            work_base_dir=tmp_work_dir,
        )

    @pytest.fixture
    def dummy_exe(self, tmp_path):
        p = tmp_path / "sample.bin"
        p.write_bytes(b"\x00" * 16)
        return str(p)

    @pytest.mark.asyncio
    async def test_start_creates_work_dir(self, config):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        assert os.path.isdir(config.resolved_work_base_dir)
        await state.shutdown()

    @pytest.mark.asyncio
    async def test_open_and_resolve(self, config, dummy_exe):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        try:
            project = state.open_project(dummy_exe)
            assert project.project_id in state.projects
            assert state.default_project_id == project.project_id

            resolved = state.resolve_project()
            assert resolved is project
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_open_custom_id(self, config, dummy_exe):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        try:
            project = state.open_project(dummy_exe, project_id="my-proj")
            assert project.project_id == "my-proj"
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_same_exe_multiple_projects(self, config, dummy_exe):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        try:
            p1 = state.open_project(dummy_exe, project_id="a")
            p2 = state.open_project(dummy_exe, project_id="b")
            assert p1.project_id != p2.project_id
            assert p1.exe_path == p2.exe_path
            assert p1.work_dir != p2.work_dir
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_duplicate_id_rejected(self, config, tmp_path):
        from ramune_ida.server.state import AppState

        exe1 = tmp_path / "a.bin"
        exe2 = tmp_path / "b.bin"
        exe1.write_bytes(b"\x00")
        exe2.write_bytes(b"\x01")

        state = AppState(config)
        await state.start()
        try:
            state.open_project(str(exe1), project_id="same")
            with pytest.raises(ValueError, match="already exists"):
                state.open_project(str(exe2), project_id="same")
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_close_project(self, config, dummy_exe):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        try:
            project = state.open_project(dummy_exe, project_id="del-me")
            work_dir = project.work_dir
            assert os.path.isdir(work_dir)

            await state.close_project("del-me")
            assert "del-me" not in state.projects
            assert state.default_project_id is None
            assert not os.path.isdir(work_dir)
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_resolve_unknown_raises(self, config):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        try:
            with pytest.raises(KeyError):
                state.resolve_project("nonexistent")
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_resolve_no_default_raises(self, config):
        from ramune_ida.server.state import AppState

        state = AppState(config)
        await state.start()
        try:
            with pytest.raises(RuntimeError, match="No project"):
                state.resolve_project()
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_default_switches_on_close(self, config, tmp_path):
        from ramune_ida.server.state import AppState

        exe1 = tmp_path / "a.bin"
        exe2 = tmp_path / "b.bin"
        exe1.write_bytes(b"\x00")
        exe2.write_bytes(b"\x01")

        state = AppState(config)
        await state.start()
        try:
            state.open_project(str(exe1), project_id="first")
            state.open_project(str(exe2), project_id="second")
            assert state.default_project_id == "first"

            await state.close_project("first")
            assert state.default_project_id == "second"
        finally:
            await state.shutdown()


# ── CLI ───────────────────────────────────────────────────────────


class TestCli:
    def test_parse_http(self):
        from ramune_ida.cli import parse_transport_url

        t, h, p = parse_transport_url("http://0.0.0.0:9000")
        assert t == "streamable-http"
        assert h == "0.0.0.0"
        assert p == 9000

    def test_parse_sse(self):
        from ramune_ida.cli import parse_transport_url

        t, h, p = parse_transport_url("sse://127.0.0.1:3000")
        assert t == "sse"
        assert h == "127.0.0.1"
        assert p == 3000

    def test_parse_default(self):
        from ramune_ida.cli import parse_transport_url

        t, h, p = parse_transport_url("http://127.0.0.1:8000")
        assert t == "streamable-http"
        assert h == "127.0.0.1"
        assert p == 8000

    def test_unsupported_scheme(self):
        from ramune_ida.cli import parse_transport_url

        with pytest.raises(ValueError, match="Unsupported"):
            parse_transport_url("ftp://host:21")


# ── Tool registration ─────────────────────────────────────────────


class TestToolRegistration:
    """Verify that importing app.py registers the expected tools."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_mcp(self):
        pytest.importorskip("mcp")

    def test_mcp_instance_created(self):
        from ramune_ida.server.app import mcp

        assert mcp is not None
        assert mcp.name == "ramune-ida"

    def test_session_tools_registered(self):
        from ramune_ida.server.app import mcp

        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {
            "open_project",
            "close_project",
            "close_database",
            "force_close",
            "switch_default",
            "get_task_result",
        }
        assert expected.issubset(tool_names), (
            f"Missing tools: {expected - tool_names}"
        )
