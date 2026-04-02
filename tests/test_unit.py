"""Unit tests — direct import, no MCP protocol involved."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ramune_ida.limiter import Limiter
from ramune_ida.project import Project
from ramune_ida.config import ServerConfig
from ramune_ida.server.output import OutputStore


# ── Limiter ───────────────────────────────────────────────────────


class TestLimiter:
    def test_defaults(self):
        lim = Limiter()
        assert lim.instance_count == 0
        assert lim.can_spawn
        assert not lim.over_soft_limit

    def test_hard_limit_blocks(self):
        lim = Limiter(soft_limit=0, hard_limit=2)
        lim.on_spawned("a")
        lim.on_spawned("b")
        assert not lim.can_spawn
        lim.on_destroyed("a")
        assert lim.can_spawn

    def test_soft_limit_advisory(self):
        lim = Limiter(soft_limit=1, hard_limit=4)
        lim.on_spawned("a")
        assert not lim.over_soft_limit
        lim.on_spawned("b")
        assert lim.over_soft_limit
        lim.on_destroyed("b")
        assert not lim.over_soft_limit

    def test_unlimited(self):
        lim = Limiter(soft_limit=0, hard_limit=0)
        for i in range(100):
            lim.on_spawned(f"p{i}")
        assert lim.can_spawn
        assert not lim.over_soft_limit

    def test_soft_equals_hard(self):
        lim = Limiter(soft_limit=2, hard_limit=2)
        lim.on_spawned("a")
        lim.on_spawned("b")
        assert not lim.can_spawn
        assert not lim.over_soft_limit

    def test_soft_greater_than_hard_rejected(self):
        with pytest.raises(ValueError, match="soft_limit"):
            Limiter(soft_limit=5, hard_limit=3)

    def test_active_projects(self):
        lim = Limiter(soft_limit=0, hard_limit=0)
        lim.on_spawned("a")
        lim.on_spawned("b")
        assert lim.active_projects == frozenset({"a", "b"})
        lim.on_destroyed("a")
        assert lim.active_projects == frozenset({"b"})

    def test_destroy_nonexistent_is_safe(self):
        lim = Limiter()
        lim.on_destroyed("nonexistent")
        assert lim.instance_count == 0


# ── Project ───────────────────────────────────────────────────────


class TestProject:
    def _make(self, tmp_path: os.PathLike, pid: str = "test") -> Project:
        work_dir = str(tmp_path / pid)
        os.makedirs(work_dir, exist_ok=True)
        return Project(
            project_id=pid,
            work_dir=work_dir,
            limiter=Limiter(soft_limit=0, hard_limit=0),
        )

    def test_initial_state(self, tmp_path):
        p = self._make(tmp_path)
        assert p.exe_path is None
        assert p.idb_path is None
        assert not p.has_database
        assert p.open_path is None

    def test_set_database_binary(self, tmp_path):
        p = self._make(tmp_path)
        p.set_database("/data/firmware.bin")
        assert p.exe_path == "/data/firmware.bin"
        assert p.idb_path == "/data/firmware.i64"
        assert p.has_database

    def test_set_database_idb(self, tmp_path):
        p = self._make(tmp_path)
        p.set_database("/data/firmware.i64")
        assert p.exe_path is None
        assert p.idb_path == "/data/firmware.i64"
        assert p.has_database

    def test_set_database_idb32(self, tmp_path):
        p = self._make(tmp_path)
        p.set_database("/data/old.idb")
        assert p.exe_path is None
        assert p.idb_path == "/data/old.idb"

    def test_open_path_prefers_existing_idb(self, tmp_path):
        p = self._make(tmp_path)
        idb = tmp_path / "test.i64"
        idb.write_bytes(b"\x00")
        p.set_database(str(tmp_path / "test.bin"))
        assert p.open_path == str(idb)

    def test_open_path_falls_back_to_exe(self, tmp_path):
        p = self._make(tmp_path)
        p.set_database("/data/test.bin")
        assert p.open_path == "/data/test.bin"

    def test_open_path_none_without_database(self, tmp_path):
        p = self._make(tmp_path)
        assert p.open_path is None

    def test_repr(self, tmp_path):
        p = self._make(tmp_path)
        r = repr(p)
        assert "test" in r
        assert "None" in r

    def test_force_close_without_handle(self, tmp_path):
        p = self._make(tmp_path)
        p.force_close()


# ── AppState ──────────────────────────────────────────────────────


class TestAppState:
    @pytest.fixture
    def config(self, tmp_path):
        return ServerConfig(
            soft_limit=2,
            hard_limit=4,
            auto_save_interval=0,
            data_dir=str(tmp_path),
        )

    @pytest.mark.asyncio
    async def test_start_creates_work_dir(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        assert os.path.isdir(config.resolved_work_base_dir)
        await state.shutdown()

    @pytest.mark.asyncio
    async def test_open_project_auto_id(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            p, created = await state.open_project()
            assert created is True
            assert p.project_id in state.projects
            assert len(p.project_id) == 8
            assert os.path.isdir(p.work_dir)
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_open_project_custom_id(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            p, created = await state.open_project("my-proj")
            assert p.project_id == "my-proj"
            assert created is True
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_open_project_invalid_id(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            with pytest.raises(ValueError, match="Invalid"):
                await state.open_project("../../bad")
            with pytest.raises(ValueError, match="Invalid"):
                await state.open_project("has space")
            with pytest.raises(ValueError, match="Invalid"):
                await state.open_project("")
            with pytest.raises(ValueError, match="Invalid"):
                await state.open_project("a" * 65)
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_open_project_idempotent(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            p1, created1 = await state.open_project("dup")
            p2, created2 = await state.open_project("dup")
            assert created1 is True
            assert created2 is False
            assert p1 is p2
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_resolve_project(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            p, _ = await state.open_project("abc")
            assert state.resolve_project("abc") is p
            with pytest.raises(KeyError):
                state.resolve_project("nonexistent")
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_close_project(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            p, _ = await state.open_project("del-me")
            work_dir = p.work_dir
            assert os.path.isdir(work_dir)
            await state.close_project("del-me")
            assert "del-me" not in state.projects
            assert not os.path.isdir(work_dir)
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_close_unknown_project(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        try:
            with pytest.raises(KeyError):
                await state.close_project("nope")
        finally:
            await state.shutdown()

    @pytest.mark.asyncio
    async def test_recover_projects(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        await state.open_project("proj-a")
        await state.open_project("proj-b")
        await state.shutdown()

        state2 = AppState(config)
        await state2.start()
        try:
            assert "proj-a" in state2.projects
            assert "proj-b" in state2.projects
            assert not state2.projects["proj-a"].has_database
        finally:
            await state2.shutdown()

    @pytest.mark.asyncio
    async def test_recover_skips_dotfiles(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        os.makedirs(os.path.join(config.resolved_work_base_dir, ".hidden"))
        await state.shutdown()

        state2 = AppState(config)
        await state2.start()
        try:
            assert ".hidden" not in state2.projects
        finally:
            await state2.shutdown()

    @pytest.mark.asyncio
    async def test_recover_skips_invalid_names(self, config):
        from ramune_ida.server.state import AppState
        state = AppState(config)
        await state.start()
        os.makedirs(os.path.join(config.resolved_work_base_dir, "has space"))
        await state.shutdown()

        state2 = AppState(config)
        await state2.start()
        try:
            assert "has space" not in state2.projects
        finally:
            await state2.shutdown()


# ── OutputStore ───────────────────────────────────────────────────


class TestOutputStore:
    def test_no_truncation(self, tmp_path):
        store = OutputStore(max_length=100)
        text = "short"
        result, url = store.truncate_if_needed(text, "p", str(tmp_path))
        assert result == text
        assert url is None

    def test_truncation(self, tmp_path):
        store = OutputStore(max_length=10)
        text = "a" * 50
        result, url = store.truncate_if_needed(text, "p", str(tmp_path))
        assert "truncated" in result
        assert result.startswith("a" * 10)
        assert url is not None

    def test_process_truncates_large_string(self, tmp_path):
        store = OutputStore(max_length=500, preview_length=20)
        data = {"short": "ok", "long": "x" * 1000, "num": 42}
        result = store.process(data, "p", str(tmp_path))
        assert result["short"] == "ok"
        assert result["num"] == 42
        assert "truncated" in result["long"]
        assert result["long"].startswith("x" * 20)
        assert "/files/p/outputs/" in result["long"]

    def test_process_truncates_long_list(self, tmp_path):
        store = OutputStore(max_length=500)
        data = {"project_id": "p", "items": [{"i": n} for n in range(200)]}
        result = store.process(data, "p", str(tmp_path))
        assert len(result["items"]) <= 30
        assert "_truncated" in result
        assert "200" in result["_truncated"]

    def test_process_fallback(self, tmp_path):
        store = OutputStore(max_length=50, preview_length=10)
        data = {"project_id": "p", "items": [{"v": "x" * 100}] * 100}
        result = store.process(data, "p", str(tmp_path))
        assert result["project_id"] == "p"
        assert "_truncated" in result


# ── ServerConfig ──────────────────────────────────────────────────


class TestServerConfig:
    def test_defaults(self):
        cfg = ServerConfig()
        assert cfg.soft_limit == 4
        assert cfg.hard_limit == 8

    def test_resolved_work_base_dir(self):
        cfg = ServerConfig(data_dir="~/test-dir")
        assert "~" not in cfg.resolved_work_base_dir


# ── CLI ───────────────────────────────────────────────────────────


class TestCli:
    def test_parse_http(self):
        from ramune_ida.cli import parse_transport_url
        t, h, p = parse_transport_url("http://0.0.0.0:9000")
        assert t == "streamable-http"

    def test_parse_sse(self):
        from ramune_ida.cli import parse_transport_url
        t, h, p = parse_transport_url("sse://127.0.0.1:3000")
        assert t == "sse"

    def test_unsupported_scheme(self):
        from ramune_ida.cli import parse_transport_url
        with pytest.raises(ValueError):
            parse_transport_url("ftp://host:21")
