"""Direct Worker process tests with real IDA.

Spawns a real Worker subprocess, talks to it over socketpair,
and tests every handler without MCP framework overhead.

Run with: pytest tests/test_worker_real.py --run-ida
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys

import orjson
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytestmark = pytest.mark.ida

IDA_DIR = os.environ.get("IDADIR", "/home/explorer/ida-pro-9.3")
IDA_PYTHON_PATH = os.path.join(IDA_DIR, "idalib", "python")
PYTHON = sys.executable
BINARY_DIR = os.path.join(os.path.dirname(__file__), "binary")

from ramune_ida.worker.socket_io import ENV_SOCK_FD


# ── Worker subprocess helper ──────────────────────────────────────


class WorkerProc:
    """Manage a real Worker subprocess with socketpair IPC."""

    def __init__(self, cwd: str | None = None):
        parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        child_fd = child_sock.fileno()

        env = os.environ.copy()
        env[ENV_SOCK_FD] = str(child_fd)
        env["IDADIR"] = IDA_DIR
        env["PYTHONPATH"] = IDA_PYTHON_PATH + os.pathsep + env.get("PYTHONPATH", "")

        self.proc = subprocess.Popen(
            [PYTHON, "-m", "ramune_ida.worker.main"],
            env=env,
            cwd=cwd,
            pass_fds=(child_fd,),
        )
        child_sock.close()

        self._sock = parent_sock
        self._reader = parent_sock.makefile("rb")
        self._writer = parent_sock.makefile("wb")

    def send(self, msg: dict) -> dict:
        self._writer.write(orjson.dumps(msg) + b"\n")
        self._writer.flush()
        return self.recv()

    def recv(self) -> dict:
        line = self._reader.readline()
        if not line:
            raise RuntimeError("Worker closed (EOF)")
        return orjson.loads(line)

    def close(self):
        self._reader.close()
        self._writer.close()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        self.proc.wait(timeout=10)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def work_dir(tmp_path):
    d = str(tmp_path / "work")
    os.makedirs(d)
    return d


@pytest.fixture
def binary(work_dir):
    """Copy ch01 test binary to work_dir."""
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    dest = os.path.join(work_dir, "ch01")
    shutil.copy2(src, dest)
    return dest


@pytest.fixture
def worker(work_dir):
    w = WorkerProc(cwd=work_dir)
    init = w.recv()
    assert init["result"]["status"] == "ready"
    yield w
    try:
        w.send({"id": "shutdown", "method": "shutdown", "params": {}})
    except Exception:
        pass
    w.close()


# ── Lifecycle ─────────────────────────────────────────────────────


def test_ping(worker):
    r = worker.send({"id": "1", "method": "ping", "params": {}})
    assert r["result"]["status"] == "pong"


def test_unknown_method(worker):
    r = worker.send({"id": "1", "method": "no_such_method", "params": {}})
    assert "error" in r


def test_open_close_database(worker, binary):
    r = worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})
    assert "error" not in r
    assert r["result"]["path"] == binary

    r = worker.send({"id": "2", "method": "close_database", "params": {}})
    assert "error" not in r


def test_open_database_missing_path(worker):
    r = worker.send({"id": "1", "method": "open_database", "params": {"path": ""}})
    assert "error" in r


def test_open_database_nonexistent_file(worker):
    r = worker.send({"id": "1", "method": "open_database", "params": {"path": "/nonexistent/file.bin"}})
    assert "error" in r


def test_save_database(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})
    r = worker.send({"id": "2", "method": "save_database", "params": {}})
    assert "error" not in r
    worker.send({"id": "3", "method": "close_database", "params": {}})


# ── Decompile (plugin:decompile) ──────────────────────────────────


def test_decompile_by_name(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "error" not in r
    assert "code" in r["result"]
    assert "addr" in r["result"]
    assert len(r["result"]["code"]) > 0

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_decompile_by_address(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    addr = r["result"]["addr"]

    r = worker.send({"id": "3", "method": "plugin:decompile", "params": {"func": addr}})
    assert "error" not in r
    assert r["result"]["addr"] == addr

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_decompile_missing_func(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": ""}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_decompile_unknown_func(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "nonexistent_func_xyz"}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Disasm (plugin:disasm) ────────────────────────────────────────


def test_disasm_by_name(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:disasm", "params": {"addr": "main", "count": 5}})
    assert "error" not in r
    result = r["result"]
    assert "start_addr" in result
    assert "disasm" in result
    lines = result["disasm"].split("\n")
    assert len(lines) > 0
    assert len(lines) <= 5

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_disasm_by_address(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:disasm", "params": {"addr": "main"}})
    addr = r["result"]["start_addr"]

    r = worker.send({"id": "3", "method": "plugin:disasm", "params": {"addr": addr, "count": 3}})
    assert "error" not in r
    lines = r["result"]["disasm"].split("\n")
    assert len(lines) <= 3

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_disasm_missing_addr(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:disasm", "params": {"addr": ""}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_disasm_unknown_addr(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:disasm", "params": {"addr": "nonexistent_xyz"}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Xrefs (plugin:xrefs) ─────────────────────────────────────────


def test_xrefs_to_function(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:xrefs", "params": {"addr": "main"}})
    assert "error" not in r
    result = r["result"]
    assert "addr" in result
    assert "xrefs" in result
    assert len(result["xrefs"]) > 0

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_xrefs_by_address(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    addr = r["result"]["addr"]

    r = worker.send({"id": "3", "method": "plugin:xrefs", "params": {"addr": addr}})
    assert "error" not in r
    assert r["result"]["addr"] == addr

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_xrefs_unknown_name(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:xrefs", "params": {"addr": "nonexistent_xyz"}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_xrefs_missing_addr(worker, binary):
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:xrefs", "params": {"addr": ""}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Survey (plugin:survey) ────────────────────────────────────────


def test_survey_basic(worker, binary):
    """survey returns a complete overview structure."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:survey", "params": {}})
    assert "error" not in r
    result = r["result"]

    assert result["file"] == "ch01"
    assert "ELF" in result["type"]
    assert result["arch"] == "x86_64"
    assert result["base"] == "0x0"
    assert int(result["size"], 16) > 0

    assert isinstance(result["segments"], list)
    assert len(result["segments"]) > 0
    seg = result["segments"][0]
    assert "name" in seg and "start" in seg and "end" in seg and "perm" in seg

    assert result["entry"].startswith("0x")

    # ch01 has a main function
    assert "main" in result
    assert result["main"].startswith("0x")

    assert isinstance(result["exports"], list)

    funcs = result["functions"]
    assert funcs["total"] > 0
    assert funcs["total"] == funcs["named"] + funcs["unnamed"] + funcs["library"]

    imports = result["imports"]
    assert isinstance(imports["total"], int)
    assert isinstance(imports["modules"], list)

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Rename (plugin:rename) ────────────────────────────────────────


def test_rename_function_by_name(worker, binary):
    """Rename a function using its current name."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename", "params": {
        "addr": "main", "new_name": "my_entry",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["old_name"] == "main"
    assert result["new_name"] == "my_entry"
    assert result["type"] == "function"

    # Verify: decompile should use the new name
    r = worker.send({"id": "3", "method": "plugin:decompile", "params": {"func": "my_entry"}})
    assert "error" not in r
    assert r["result"]["name"] == "my_entry"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_function_by_address(worker, binary):
    """Rename a function using its hex address."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    # Get the address of main first
    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    addr = r["result"]["addr"]

    r = worker.send({"id": "3", "method": "plugin:rename", "params": {
        "addr": addr, "new_name": "renamed_main",
    }})
    assert "error" not in r
    assert r["result"]["new_name"] == "renamed_main"
    assert r["result"]["type"] == "function"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_local_variable(worker, binary):
    """Rename a local variable inside a function."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    # First decompile to see variable names
    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "error" not in r
    code_before = r["result"]["code"]

    r = worker.send({"id": "3", "method": "plugin:rename", "params": {
        "func": "main", "var": "v3", "new_name": "counter",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["old_name"] == "v3"
    assert result["new_name"] == "counter"
    assert result["type"] == "local"

    # Verify: decompile should reflect the rename
    r = worker.send({"id": "4", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "counter" in r["result"]["code"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_function_argument(worker, binary):
    """Rename a function argument (also via rename_lvar)."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename", "params": {
        "func": "main", "var": "a1", "new_name": "argc",
    }})
    assert "error" not in r
    assert r["result"]["type"] == "local"
    assert r["result"]["new_name"] == "argc"

    r = worker.send({"id": "3", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "argc" in r["result"]["code"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_missing_new_name(worker, binary):
    """Omitting new_name should return an error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename", "params": {
        "addr": "main",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_missing_addr_and_func(worker, binary):
    """Providing only new_name without addr or func+var should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename", "params": {
        "new_name": "orphan",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_nonexistent_variable(worker, binary):
    """Renaming a non-existent local variable should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename", "params": {
        "func": "main", "var": "no_such_var_xyz", "new_name": "whatever",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_rename_unknown_address(worker, binary):
    """Renaming an unresolvable name should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename", "params": {
        "addr": "nonexistent_func_xyz", "new_name": "whatever",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Execute Python (plugin:execute_python) ───────────────────────


def test_execute_python_basic(worker, binary):
    """Execute simple code with IDA API access."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:execute_python", "params": {
        "code": "import idautils\n_result = len(list(idautils.Functions()))"
    }})
    assert "error" not in r
    result = r["result"]
    assert result["error"] == ""
    assert isinstance(result["result"], int)
    assert result["result"] > 0

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_execute_python_no_timeout(worker, binary):
    """execute_python runs without hard timeout; cancel handles long tasks."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:execute_python", "params": {
        "code": "_result = 42",
    }})
    assert "error" not in r
    assert r["result"]["result"] == 42

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Multiple commands in sequence ─────────────────────────────────


def test_sequential_commands(worker, binary):
    """Verify the worker handles a realistic sequence correctly."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "code" in r["result"]

    r = worker.send({"id": "3", "method": "plugin:disasm", "params": {"addr": "main", "count": 10}})
    assert len(r["result"]["disasm"]) > 0

    r = worker.send({"id": "4", "method": "save_database", "params": {}})
    assert "error" not in r

    r = worker.send({"id": "5", "method": "close_database", "params": {}})
    assert "error" not in r


def test_reopen_after_close(worker, binary):
    """Close and reopen the same database in one worker session."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})
    worker.send({"id": "2", "method": "close_database", "params": {}})

    worker.send({"id": "3", "method": "open_database", "params": {"path": binary}})
    r = worker.send({"id": "4", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "code" in r["result"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── list_funcs (plugin:list_funcs) ────────────────────────────────


def test_list_funcs_basic(worker, binary):
    """list_funcs returns functions with addr, name, size."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_funcs", "params": {}})
    assert "error" not in r
    result = r["result"]

    assert result["total"] > 0
    assert isinstance(result["items"], list)
    assert len(result["items"]) > 0

    item = result["items"][0]
    assert "addr" in item and "name" in item and "size" in item
    assert item["addr"].startswith("0x")
    assert isinstance(item["size"], int)

    names = [i["name"] for i in result["items"]]
    assert "main" in names

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_list_funcs_filter(worker, binary):
    """list_funcs filter narrows results."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_funcs",
                      "params": {"filter": "main"}})
    assert "error" not in r
    result = r["result"]
    for item in result["items"]:
        assert "main" in item["name"].lower()

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_list_funcs_exclude(worker, binary):
    """list_funcs exclude filters out matching items."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_funcs",
                      "params": {"exclude": "main"}})
    assert "error" not in r
    for item in r["result"]["items"]:
        assert "main" not in item["name"].lower()

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── list_strings (plugin:list_strings) ────────────────────────────


def test_list_strings_basic(worker, binary):
    """list_strings returns strings with addr, value, length."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_strings", "params": {}})
    assert "error" not in r
    result = r["result"]

    assert isinstance(result["total"], int)
    assert isinstance(result["items"], list)
    if result["total"] > 0:
        item = result["items"][0]
        assert "addr" in item and "value" in item and "length" in item

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── list_imports (plugin:list_imports) ────────────────────────────


def test_list_imports_basic(worker, binary):
    """list_imports returns flat import list with module, name, addr."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_imports", "params": {}})
    assert "error" not in r
    result = r["result"]

    assert isinstance(result["total"], int)
    assert isinstance(result["items"], list)
    if result["total"] > 0:
        item = result["items"][0]
        assert "module" in item and "name" in item and "addr" in item

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── list_names (plugin:list_names) ────────────────────────────────


def test_list_names_basic(worker, binary):
    """list_names returns named addresses with addr, name."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_names", "params": {}})
    assert "error" not in r
    result = r["result"]

    assert result["total"] > 0
    assert isinstance(result["items"], list)

    item = result["items"][0]
    assert "addr" in item and "name" in item
    assert item["addr"].startswith("0x")

    names = [i["name"] for i in result["items"]]
    assert "main" in names

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_list_names_filter(worker, binary):
    """list_names filter works on name field."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_names",
                      "params": {"filter": "main"}})
    assert "error" not in r
    for item in r["result"]["items"]:
        assert "main" in item["name"].lower()

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── list_types (plugin:list_types) ───────────────────────────────


def test_list_types_basic(worker, binary):
    """list_types returns types in IDA format strings."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:list_types", "params": {}})
    assert "error" not in r
    result = r["result"]

    assert result["total"] >= 0
    assert isinstance(result["items"], list)

    # All items should be strings
    for item in result["items"]:
        assert isinstance(item, str)

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_list_types_after_define(worker, binary):
    """list_types shows user-defined types."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct ListTestStruct { int x; char *y; };",
    }})
    worker.send({"id": "3", "method": "plugin:define_type", "params": {
        "declare": "enum ListTestEnum { LT_A = 0, LT_B = 1, LT_C = 2 };",
    }})

    r = worker.send({"id": "4", "method": "plugin:list_types", "params": {}})
    assert "error" not in r
    items = r["result"]["items"]

    # Check format: "struct Name // sizeof=0xN"
    struct_items = [i for i in items if "ListTestStruct" in i]
    assert len(struct_items) == 1
    assert struct_items[0].startswith("struct ")
    assert "sizeof=" in struct_items[0]

    enum_items = [i for i in items if "ListTestEnum" in i]
    assert len(enum_items) == 1
    assert enum_items[0].startswith("enum ")

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_list_types_filter_kind(worker, binary):
    """list_types kind filter narrows results."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct KindFilterS { int a; }; enum KindFilterE { KF_X = 0 };",
    }})

    r = worker.send({"id": "3", "method": "plugin:list_types",
                      "params": {"kind": "struct"}})
    assert "error" not in r
    for item in r["result"]["items"]:
        assert item.startswith("struct ")

    r = worker.send({"id": "4", "method": "plugin:list_types",
                      "params": {"kind": "enum"}})
    assert "error" not in r
    for item in r["result"]["items"]:
        assert item.startswith("enum ")

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_list_types_filter_name(worker, binary):
    """list_types filter narrows by name substring."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct NameFilterAlpha { int a; }; struct NameFilterBeta { int b; };",
    }})

    r = worker.send({"id": "3", "method": "plugin:list_types",
                      "params": {"filter": "Alpha"}})
    assert "error" not in r
    items = r["result"]["items"]
    assert any("NameFilterAlpha" in i for i in items)
    assert not any("NameFilterBeta" in i for i in items)

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── search (plugin:search) ────────────────────────────────────────


def test_search_default_all(worker, binary):
    """search without type searches all text sources."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search",
                      "params": {"pattern": "main"}})
    assert "error" not in r
    result = r["result"]
    assert result["total"] > 0
    assert isinstance(result["matches"], list)
    sources = {m["source"] for m in result["matches"]}
    assert "name" in sources

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_search_names_only(worker, binary):
    """search with type=names only returns name matches."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search",
                      "params": {"pattern": "main", "type": "names"}})
    assert "error" not in r
    for m in r["result"]["matches"]:
        assert m["source"] == "name"
        assert "main" in m["value"].lower()

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_search_disasm(worker, binary):
    """search with type=disasm finds instructions."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search",
                      "params": {"pattern": "call", "type": "disasm"}})
    assert "error" not in r
    result = r["result"]
    assert result["total"] > 0
    for m in result["matches"]:
        assert m["source"] == "disasm"
        assert "call" in m["value"].lower()

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_search_types(worker, binary):
    """search with type=types finds local types."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search",
                      "params": {"pattern": "Elf", "type": "types"}})
    assert "error" not in r
    for m in r["result"]["matches"]:
        assert m["source"] == "type"
        assert "elf" in m["value"].lower()

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_search_invalid_regex(worker, binary):
    """search with invalid regex returns error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search",
                      "params": {"pattern": "[invalid"}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_search_count_limit(worker, binary):
    """search respects count limit."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search",
                      "params": {"pattern": ".*", "type": "names", "count": 3}})
    assert "error" not in r
    assert len(r["result"]["matches"]) <= 3

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── search_bytes (plugin:search_bytes) ────────────────────────────


def test_search_bytes_basic(worker, binary):
    """search_bytes finds byte patterns."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search_bytes",
                      "params": {"pattern": "48 89 ?? 48"}})
    assert "error" not in r
    result = r["result"]
    assert result["total"] > 0
    for m in result["matches"]:
        assert m["addr"].startswith("0x")

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_search_bytes_no_match(worker, binary):
    """search_bytes with non-matching pattern returns empty."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:search_bytes",
                      "params": {"pattern": "FF FF FF FF FF FF FF FF"}})
    assert "error" not in r
    assert r["result"]["total"] == 0

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── examine (plugin:examine) ─────────────────────────────────────


def test_examine_code(worker, binary):
    """examine on a code address returns type=code."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:examine",
                      "params": {"addr": "main"}})
    assert "error" not in r
    result = r["result"]
    assert result["type"] == "code"
    assert isinstance(result["value"], str)
    assert result["addr"].startswith("0x")

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_examine_string(worker, binary):
    """examine on a string address returns type=string."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    # First find a string address
    r = worker.send({"id": "2", "method": "plugin:list_strings",
                      "params": {}})
    items = r["result"]["items"]
    if not items:
        worker.send({"id": "99", "method": "close_database", "params": {}})
        return

    str_addr = items[0]["addr"]
    r = worker.send({"id": "3", "method": "plugin:examine",
                      "params": {"addr": str_addr}})
    assert "error" not in r
    result = r["result"]
    assert result["type"] == "string"
    assert isinstance(result["value"], str)

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_examine_elf_header(worker, binary):
    """examine on ELF header returns detected type and value."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:examine",
                      "params": {"addr": "0x0"}})
    assert "error" not in r
    result = r["result"]
    assert "type" in result
    assert "value" in result
    assert result["addr"] == "0x0"

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── get_bytes (plugin:get_bytes) ──────────────────────────────────


def test_get_bytes_basic(worker, binary):
    """get_bytes returns hex string of raw bytes."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:get_bytes",
                      "params": {"addr": "main", "size": 16}})
    assert "error" not in r
    result = r["result"]
    assert result["size"] == 16
    assert len(result["bytes"]) == 32  # 16 bytes = 32 hex chars
    assert result["addr"].startswith("0x")

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_bytes_by_name(worker, binary):
    """get_bytes resolves names."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r1 = worker.send({"id": "2", "method": "plugin:get_bytes",
                       "params": {"addr": "main", "size": 4}})
    # Also read by hex address
    addr = r1["result"]["addr"]
    r2 = worker.send({"id": "3", "method": "plugin:get_bytes",
                       "params": {"addr": addr, "size": 4}})
    assert r1["result"]["bytes"] == r2["result"]["bytes"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── undo (plugin:undo) ───────────────────────────────────────────


def test_undo_after_rename(worker, binary):
    """rename creates an auto undo point; undo reverts it."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:rename",
                      "params": {"addr": "main", "new_name": "undo_test_xyz"}})
    assert "error" not in r
    assert r["result"]["new_name"] == "undo_test_xyz"
    old_name = r["result"]["old_name"]

    r = worker.send({"id": "3", "method": "plugin:undo", "params": {}})
    assert "error" not in r
    assert r["result"]["undone"] == 1
    assert r["result"]["labels"] == ["rename"]

    r = worker.send({"id": "4", "method": "plugin:execute_python", "params": {
        "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('%s'))" % old_name
    }})
    assert r["result"]["result"] == old_name

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_undo_multiple(worker, binary):
    """Multiple renames produce multiple undo points."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:rename",
                  "params": {"addr": "main", "new_name": "step_one"}})
    worker.send({"id": "3", "method": "plugin:rename",
                  "params": {"addr": "step_one", "new_name": "step_two"}})

    r = worker.send({"id": "4", "method": "plugin:undo", "params": {"count": 2}})
    assert "error" not in r
    assert r["result"]["undone"] == 2

    r = worker.send({"id": "5", "method": "plugin:execute_python", "params": {
        "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('main'))"
    }})
    assert r["result"]["result"] == "main"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_undo_nothing(worker, binary):
    """undo with nothing to undo returns undone=0."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:undo", "params": {}})
    assert "error" not in r
    assert r["result"]["undone"] == 0
    assert r["result"]["labels"] == []

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── set_comment / get_comment ─────────────────────────────────────


def test_set_get_comment_addr(worker, binary):
    """Set and read a disassembly line comment by address."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    # Get main address
    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    addr = r["result"]["addr"]

    # Set comment
    r = worker.send({"id": "3", "method": "plugin:set_comment", "params": {
        "addr": addr, "comment": "entry point of program",
    }})
    assert "error" not in r
    assert r["result"]["addr"] == addr
    assert r["result"]["comment"] == "entry point of program"

    # Read it back
    r = worker.send({"id": "4", "method": "plugin:get_comment", "params": {
        "addr": addr,
    }})
    assert "error" not in r
    assert r["result"]["comment"] == "entry point of program"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_get_comment_func(worker, binary):
    """Set and read a function header comment."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_comment", "params": {
        "func": "main", "comment": "Main entry – verified",
    }})
    assert "error" not in r
    assert "func" in r["result"]
    assert r["result"]["comment"] == "Main entry – verified"

    r = worker.send({"id": "3", "method": "plugin:get_comment", "params": {
        "func": "main",
    }})
    assert "error" not in r
    assert r["result"]["comment"] == "Main entry – verified"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_clear_comment_addr(worker, binary):
    """Empty string clears a disassembly comment."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:decompile", "params": {"func": "main"}})
    addr = r["result"]["addr"]

    # Set then clear
    worker.send({"id": "3", "method": "plugin:set_comment", "params": {
        "addr": addr, "comment": "temp",
    }})
    worker.send({"id": "4", "method": "plugin:set_comment", "params": {
        "addr": addr, "comment": "",
    }})

    r = worker.send({"id": "5", "method": "plugin:get_comment", "params": {
        "addr": addr,
    }})
    assert "error" not in r
    assert r["result"]["comment"] is None

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_clear_comment_func(worker, binary):
    """Empty string clears a function header comment."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:set_comment", "params": {
        "func": "main", "comment": "temp header",
    }})
    worker.send({"id": "3", "method": "plugin:set_comment", "params": {
        "func": "main", "comment": "",
    }})

    r = worker.send({"id": "4", "method": "plugin:get_comment", "params": {
        "func": "main",
    }})
    assert "error" not in r
    assert r["result"]["comment"] is None

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_comment_no_comment(worker, binary):
    """get_comment returns None when no comment exists."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:get_comment", "params": {
        "addr": "main",
    }})
    assert "error" not in r
    assert r["result"]["comment"] is None

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_comment_missing_params(worker, binary):
    """set_comment without addr or func should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_comment", "params": {
        "comment": "orphan",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_comment_missing_params(worker, binary):
    """get_comment without addr or func should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:get_comment", "params": {}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_comment_not_a_function(worker, binary):
    """set_comment with func= pointing to non-function should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_comment", "params": {
        "func": "0x0", "comment": "should fail",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_undo_reverts_set_comment(worker, binary):
    """set_comment creates an undo point; undo reverts the comment."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:set_comment", "params": {
        "func": "main", "comment": "undo me",
    }})

    r = worker.send({"id": "3", "method": "plugin:get_comment", "params": {
        "func": "main",
    }})
    assert r["result"]["comment"] == "undo me"

    r = worker.send({"id": "4", "method": "plugin:undo", "params": {}})
    assert "error" not in r
    assert r["result"]["undone"] == 1
    assert r["result"]["labels"] == ["set_comment"]

    r = worker.send({"id": "5", "method": "plugin:get_comment", "params": {
        "func": "main",
    }})
    assert r["result"]["comment"] is None

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── set_type (plugin:set_type) ────────────────────────────────────


def test_set_type_function_signature(worker, binary):
    """Set a function signature via addr."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "addr": "main",
        "type": "int main(int argc, const char **argv, const char **envp);",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["target"] == "function"
    assert "new_type" in result
    assert "argc" in result["new_type"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_local_var_basic(worker, binary):
    """Set a basic type on a local variable."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "func": "main", "var": "v3", "type": "unsigned int",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["var"] == "v3"
    assert result["new_type"] == "unsigned int"
    assert result["old_type"] == "int"

    # Verify via decompile
    r = worker.send({"id": "3", "method": "plugin:decompile", "params": {"func": "main"}})
    assert "unsigned int" in r["result"]["code"] or "unsigned int v3" in r["result"]["code"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_local_var_pointer(worker, binary):
    """Set a pointer type on a local variable."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "func": "main", "var": "v3", "type": "char *",
    }})
    assert "error" not in r
    assert r["result"]["new_type"] == "char *"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_local_var_struct_pointer(worker, binary):
    """Set a user-defined struct pointer type on a local variable."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    # First define the struct
    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct TestCtx { int fd; char *path; };",
    }})

    r = worker.send({"id": "3", "method": "plugin:set_type", "params": {
        "func": "main", "var": "v3", "type": "TestCtx *",
    }})
    assert "error" not in r
    assert r["result"]["new_type"] == "TestCtx *"

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_argument(worker, binary):
    """Set type on a function argument."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "func": "main", "var": "a2", "type": "const char **",
    }})
    assert "error" not in r
    assert "const char **" in r["result"]["new_type"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_function_pointer(worker, binary):
    """Set a function pointer type on a local variable."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "func": "main", "var": "v3", "type": "int (*)(void *, int)",
    }})
    assert "error" not in r
    assert "(*)" in r["result"]["new_type"]

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_missing_params(worker, binary):
    """set_type without addr or func should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "type": "int",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_var_not_found(worker, binary):
    """set_type with nonexistent variable should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "func": "main", "var": "no_such_var_xyz", "type": "int",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_set_type_invalid_type(worker, binary):
    """set_type with unparseable type should error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:set_type", "params": {
        "func": "main", "var": "v3", "type": "not_a_real_type_xyz",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── define_type (plugin:define_type) ──────────────────────────────


def test_define_type_struct(worker, binary):
    """Define a struct in the local type library."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct RealTestStruct { int field_a; char *field_b; unsigned long long field_c; };",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["errors"] == 0
    assert any(t["name"] == "RealTestStruct" for t in result["types"])
    st = next(t for t in result["types"] if t["name"] == "RealTestStruct")
    assert st["kind"] == "struct"
    assert st["size"] > 0

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_define_type_enum(worker, binary):
    """Define an enum."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "enum TestFlags { FLAG_NONE = 0, FLAG_READ = 1, FLAG_WRITE = 2, FLAG_EXEC = 4 };",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["errors"] == 0
    assert any(t["name"] == "TestFlags" for t in result["types"])

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_define_type_typedef(worker, binary):
    """Define a typedef."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "typedef int (*test_callback_t)(void *ctx, int arg);",
    }})
    assert "error" not in r
    result = r["result"]
    assert result["errors"] == 0
    assert any(t["name"] == "test_callback_t" for t in result["types"])

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_define_type_multiple(worker, binary):
    """Multiple declarations in one call."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    decl = """
    struct MultiA { int x; };
    struct MultiB { MultiA *ptr; int y; };
    typedef MultiB *MultiB_ptr;
    """
    r = worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": decl,
    }})
    assert "error" not in r
    result = r["result"]
    assert result["errors"] == 0
    names = {t["name"] for t in result["types"]}
    assert "MultiA" in names
    assert "MultiB" in names
    assert "MultiB_ptr" in names

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_define_type_update(worker, binary):
    """Re-declaring an existing type updates it."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct Evolve { int x; };",
    }})
    r1 = worker.send({"id": "3", "method": "plugin:define_type", "params": {
        "declare": "struct Evolve { int x; int y; double z; };",
    }})
    assert "error" not in r1
    st = next(t for t in r1["result"]["types"] if t["name"] == "Evolve")
    assert st["size"] == 16  # 4 + 4 + 8

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_define_type_invalid(worker, binary):
    """Invalid declaration should return error."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct { broken syntax",
    }})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── get_type (plugin:get_type) ──────────────────────────────────


def test_get_type_struct(worker, binary):
    """get_type returns C declaration with offset comments for struct."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct GetTypeTest { int field_a; char *field_b; unsigned long long field_c; };",
    }})

    r = worker.send({"id": "3", "method": "plugin:get_type",
                      "params": {"name": "GetTypeTest"}})
    assert "error" not in r
    defn = r["result"]["definition"]
    print(f"\n--- get_type struct ---\n{defn}")

    assert "struct GetTypeTest" in defn
    assert "sizeof=" in defn
    assert "field_a" in defn
    assert "field_b" in defn
    assert "field_c" in defn
    # Offset comments present
    assert "/* 0x00 */" in defn

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_type_enum(worker, binary):
    """get_type returns C declaration for enum."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "enum GetTypeFlags { GT_NONE = 0, GT_READ = 1, GT_WRITE = 2, GT_EXEC = 4 };",
    }})

    r = worker.send({"id": "3", "method": "plugin:get_type",
                      "params": {"name": "GetTypeFlags"}})
    assert "error" not in r
    defn = r["result"]["definition"]
    print(f"\n--- get_type enum ---\n{defn}")

    assert "GetTypeFlags" in defn
    assert "GT_NONE" in defn
    assert "GT_READ" in defn
    assert "GT_WRITE" in defn
    assert "GT_EXEC" in defn

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_type_typedef(worker, binary):
    """get_type returns definition for typedef."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "typedef unsigned long long GT_QWORD;",
    }})

    r = worker.send({"id": "3", "method": "plugin:get_type",
                      "params": {"name": "GT_QWORD"}})
    assert "error" not in r
    defn = r["result"]["definition"]
    print(f"\n--- get_type typedef ---\n{defn}")

    assert "GT_QWORD" in defn

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_type_nested_struct(worker, binary):
    """get_type does not recursively expand nested struct types."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    worker.send({"id": "2", "method": "plugin:define_type", "params": {
        "declare": "struct GTInner { int x; int y; }; struct GTOuter { GTInner inner; int flags; };",
    }})

    r = worker.send({"id": "3", "method": "plugin:get_type",
                      "params": {"name": "GTOuter"}})
    assert "error" not in r
    defn = r["result"]["definition"]
    print(f"\n--- get_type nested ---\n{defn}")

    assert "GTOuter" in defn
    assert "inner" in defn
    assert "flags" in defn
    # Inner struct members should NOT appear (no recursive expansion)
    # The member type should just reference GTInner by name
    assert "GTInner" in defn

    worker.send({"id": "99", "method": "close_database", "params": {}})


def test_get_type_not_found(worker, binary):
    """get_type returns error for non-existent type."""
    worker.send({"id": "1", "method": "open_database", "params": {"path": binary}})

    r = worker.send({"id": "2", "method": "plugin:get_type",
                      "params": {"name": "NonExistentType12345"}})
    assert "error" in r

    worker.send({"id": "99", "method": "close_database", "params": {}})


# ── Crash Recovery ────────────────────────────────────────────────

IDB_COMPONENT_EXTS = (".id0", ".id1", ".id2", ".nam", ".til")


def _find_residual_files(idb_path: str) -> list[str]:
    """Return paths of existing IDA component files."""
    stem = os.path.splitext(idb_path)[0]
    return [stem + ext for ext in IDB_COMPONENT_EXTS
            if os.path.isfile(stem + ext)]


def _remove_residual_files(idb_path: str) -> list[str]:
    """Delete residual component files, return deleted paths."""
    removed = []
    for f in _find_residual_files(idb_path):
        os.remove(f)
        removed.append(f)
    return removed


def test_save_to_i64_without_close(work_dir):
    """Can save_database produce a .i64 without closing?"""
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    binary_path = os.path.join(work_dir, "ch01")
    shutil.copy2(src, binary_path)
    idb_path = os.path.join(work_dir, "ch01.i64")

    w = WorkerProc(cwd=work_dir)
    init = w.recv()
    assert init["result"]["status"] == "ready"

    r = w.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    assert "error" not in r

    w.send({"id": "2", "method": "plugin:rename",
            "params": {"addr": "main", "new_name": "i64_test"}})

    # Test 1: save_database("", 0) — does this create .i64?
    r = w.send({"id": "3", "method": "plugin:execute_python", "params": {
        "code": "import ida_loader; _result = ida_loader.save_database('', 0)"
    }})
    print(f"\nsave_database('', 0) returned: {r.get('result', {}).get('result')}")
    print(f".i64 exists after save('', 0): {os.path.isfile(idb_path)}")

    # Test 2: save_database with explicit .i64 path
    r = w.send({"id": "4", "method": "plugin:execute_python", "params": {
        "code": f"import ida_loader; _result = ida_loader.save_database(r'{idb_path}', 0)"
    }})
    print(f"save_database('{idb_path}', 0) returned: {r.get('result', {}).get('result')}")
    print(f".i64 exists after save(idb_path, 0): {os.path.isfile(idb_path)}")
    if os.path.isfile(idb_path):
        print(f".i64 size: {os.path.getsize(idb_path)} bytes")

    # Test 3: can we still use the database after save_database with outfile?
    if os.path.isfile(idb_path):
        r = w.send({"id": "5", "method": "plugin:execute_python", "params": {
            "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('i64_test'))"
        }})
        still_works = r.get("result", {}).get("result") == "i64_test"
        print(f"Database still usable after save to .i64: {still_works}")

        # Test 4: check residual component files still exist
        residuals = _find_residual_files(idb_path)
        print(f"Component files still exist: {[os.path.basename(f) for f in residuals]}")

    w.send({"id": "99", "method": "close_database", "params": {}})
    try:
        w.send({"id": "shutdown", "method": "shutdown", "params": {}})
    except Exception:
        pass
    w.close()


def test_auto_save_creates_i64(work_dir):
    """save_database with idb_path creates .i64 that survives crash recovery."""
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    binary_path = os.path.join(work_dir, "ch01")
    shutil.copy2(src, binary_path)
    idb_path = os.path.join(work_dir, "ch01.i64")

    w = WorkerProc(cwd=work_dir)
    w.recv()
    w.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})

    w.send({"id": "2", "method": "plugin:rename",
            "params": {"addr": "main", "new_name": "auto_saved_name"}})

    # save_database with idb_path (what auto-save now does)
    r = w.send({"id": "3", "method": "save_database",
                "params": {"idb_path": idb_path}})
    assert "error" not in r
    assert os.path.isfile(idb_path), ".i64 should exist after save_database"

    w.send({"id": "4", "method": "plugin:rename",
            "params": {"addr": "auto_saved_name", "new_name": "lost_after_crash"}})

    # SIGKILL — simulate crash
    import signal
    os.kill(w.proc.pid, signal.SIGKILL)
    w.proc.wait(timeout=5)
    w._reader.close()
    w._writer.close()
    try:
        w._sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    w._sock.close()

    # Now we have both .i64 and residual component files
    assert os.path.isfile(idb_path)
    residuals = _find_residual_files(idb_path)
    assert len(residuals) > 0

    # Scenario 1: normal recovery from component files
    w2 = WorkerProc(cwd=work_dir)
    w2.recv()
    r = w2.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    assert "error" not in r

    r = w2.send({"id": "2", "method": "plugin:execute_python", "params": {
        "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('auto_saved_name'))"
    }})
    assert r["result"]["result"] == "auto_saved_name", \
        "save_database rename should survive crash recovery"

    w2.send({"id": "99", "method": "close_database", "params": {}})
    w2.send({"id": "shutdown", "method": "shutdown", "params": {}})
    w2.close()


def test_crash_residual_files(work_dir):
    """Test A: SIGKILL leaves residual component files behind."""
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    binary_path = os.path.join(work_dir, "ch01")
    shutil.copy2(src, binary_path)
    idb_path = os.path.join(work_dir, "ch01.i64")

    w = WorkerProc(cwd=work_dir)
    init = w.recv()
    assert init["result"]["status"] == "ready"

    r = w.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    assert "error" not in r, f"open_database failed: {r}"

    r = w.send({"id": "2", "method": "plugin:rename",
                "params": {"addr": "main", "new_name": "crash_test_saved"}})
    assert "error" not in r

    r = w.send({"id": "3", "method": "save_database", "params": {}})
    assert "error" not in r

    r = w.send({"id": "4", "method": "plugin:rename",
                "params": {"addr": "crash_test_saved", "new_name": "post_save_name"}})
    assert "error" not in r

    print(f"\n--- Before SIGKILL ---")
    print(f"IDB exists: {os.path.isfile(idb_path)}")
    residuals_before = _find_residual_files(idb_path)
    print(f"Residual files before kill: {residuals_before}")

    import signal
    pid = w.proc.pid
    os.kill(pid, signal.SIGKILL)
    w.proc.wait(timeout=5)

    print(f"\n--- After SIGKILL ---")
    print(f"IDB exists: {os.path.isfile(idb_path)}")
    if os.path.isfile(idb_path):
        print(f"IDB size: {os.path.getsize(idb_path)} bytes")
    residuals = _find_residual_files(idb_path)
    print(f"Residual files after kill: {[os.path.basename(f) for f in residuals]}")
    for f in residuals:
        print(f"  {os.path.basename(f)}: {os.path.getsize(f)} bytes")

    w._reader.close()
    w._writer.close()
    try:
        w._sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    w._sock.close()

    assert len(residuals) > 0, "Expected residual files after SIGKILL"


def test_crash_recovery_auto(work_dir):
    """Test B: open_database with residual files — does idalib auto-recover?"""
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    binary_path = os.path.join(work_dir, "ch01")
    shutil.copy2(src, binary_path)
    idb_path = os.path.join(work_dir, "ch01.i64")

    # Phase 1: open, rename, save, rename again, SIGKILL
    w1 = WorkerProc(cwd=work_dir)
    w1.recv()
    w1.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    w1.send({"id": "2", "method": "plugin:rename",
             "params": {"addr": "main", "new_name": "saved_name"}})
    w1.send({"id": "3", "method": "save_database", "params": {}})
    w1.send({"id": "4", "method": "plugin:rename",
             "params": {"addr": "saved_name", "new_name": "unsaved_name"}})

    import signal
    os.kill(w1.proc.pid, signal.SIGKILL)
    w1.proc.wait(timeout=5)
    w1._reader.close()
    w1._writer.close()
    try:
        w1._sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    w1._sock.close()

    residuals = _find_residual_files(idb_path)
    print(f"\n--- Phase 1 done, residuals: {[os.path.basename(f) for f in residuals]} ---")

    # Phase 2: new worker, try to open same database
    w2 = WorkerProc(cwd=work_dir)
    init = w2.recv()
    assert init["result"]["status"] == "ready"

    print(f"\n--- Phase 2: opening database with residuals ---")
    r = w2.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    print(f"open_database result: {r}")
    open_ok = "error" not in r

    if open_ok:
        print("open_database succeeded (idalib auto-recovered)")

        # Check if saved rename persists
        r = w2.send({"id": "2", "method": "plugin:execute_python", "params": {
            "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('saved_name'))"
        }})
        saved_found = r.get("result", {}).get("result") == "saved_name"
        print(f"Saved name 'saved_name' found: {saved_found}")

        # Check if unsaved rename persists (IDA incremental writes)
        r = w2.send({"id": "3", "method": "plugin:execute_python", "params": {
            "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('unsaved_name'))"
        }})
        unsaved_found = r.get("result", {}).get("result") == "unsaved_name"
        print(f"Unsaved name 'unsaved_name' found: {unsaved_found}")

        # Check if 'main' still exists (original name)
        r = w2.send({"id": "4", "method": "plugin:execute_python", "params": {
            "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('main'))"
        }})
        main_found = r.get("result", {}).get("result") == "main"
        print(f"Original name 'main' found: {main_found}")

        # Check residual files after recovery
        residuals_after = _find_residual_files(idb_path)
        print(f"Residual files after recovery open: {[os.path.basename(f) for f in residuals_after]}")

        w2.send({"id": "99", "method": "close_database", "params": {}})
    else:
        print(f"open_database FAILED: {r.get('error', {})}")

    try:
        w2.send({"id": "shutdown", "method": "shutdown", "params": {}})
    except Exception:
        pass
    w2.close()

    residuals_final = _find_residual_files(idb_path)
    print(f"Residual files after close: {[os.path.basename(f) for f in residuals_final]}")

    assert open_ok, "open_database should succeed with residual files"


def test_crash_recovery_clean_fallback(work_dir):
    """Test C: delete residuals then open — falls back to .i64 from prior close.

    IDA only creates .i64 on close_database (not save_database).
    So we need a close→reopen→crash cycle to have a .i64 to fall back to.
    """
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    binary_path = os.path.join(work_dir, "ch01")
    shutil.copy2(src, binary_path)
    idb_path = os.path.join(work_dir, "ch01.i64")

    # Phase 1: open, rename, close (this creates .i64 with the rename)
    w1 = WorkerProc(cwd=work_dir)
    w1.recv()
    w1.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    w1.send({"id": "2", "method": "plugin:rename",
             "params": {"addr": "main", "new_name": "closed_saved"}})
    w1.send({"id": "3", "method": "close_database", "params": {"save": True}})
    w1.send({"id": "shutdown", "method": "shutdown", "params": {}})
    w1.close()

    assert os.path.isfile(idb_path), ".i64 should exist after close_database"
    idb_size = os.path.getsize(idb_path)
    print(f"\n--- Phase 1: .i64 created ({idb_size} bytes) ---")

    # Phase 2: reopen, rename again, SIGKILL (crash with new unpacked changes)
    w2 = WorkerProc(cwd=work_dir)
    w2.recv()
    w2.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    w2.send({"id": "2", "method": "plugin:rename",
             "params": {"addr": "closed_saved", "new_name": "crash_unsaved"}})
    w2.send({"id": "3", "method": "save_database", "params": {}})

    import signal
    os.kill(w2.proc.pid, signal.SIGKILL)
    w2.proc.wait(timeout=5)
    w2._reader.close()
    w2._writer.close()
    try:
        w2._sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    w2._sock.close()

    residuals = _find_residual_files(idb_path)
    print(f"Residuals after crash: {[os.path.basename(f) for f in residuals]}")
    print(f".i64 still exists: {os.path.isfile(idb_path)}, size: {os.path.getsize(idb_path) if os.path.isfile(idb_path) else 'N/A'}")

    # Phase 3: delete residuals, forcing fallback to .i64
    removed = _remove_residual_files(idb_path)
    print(f"Removed {len(removed)} residual files")

    w3 = WorkerProc(cwd=work_dir)
    w3.recv()

    r = w3.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    print(f"open_database after cleanup: {r}")
    assert "error" not in r

    # Should have the name from Phase 1 close (packed into .i64)
    r = w3.send({"id": "2", "method": "plugin:execute_python", "params": {
        "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('closed_saved'))"
    }})
    closed_found = r.get("result", {}).get("result") == "closed_saved"
    print(f"Name from close_database 'closed_saved' found: {closed_found}")

    # Should NOT have the crash-time name (component files deleted)
    r = w3.send({"id": "3", "method": "plugin:execute_python", "params": {
        "code": "import idc; _result = idc.get_name(idc.get_name_ea_simple('crash_unsaved'))"
    }})
    crash_found = r.get("result", {}).get("result") == "crash_unsaved"
    print(f"Crash-time name 'crash_unsaved' found: {crash_found}")

    w3.send({"id": "99", "method": "close_database", "params": {}})
    try:
        w3.send({"id": "shutdown", "method": "shutdown", "params": {}})
    except Exception:
        pass
    w3.close()

    assert closed_found, "Changes from close_database should survive in .i64"
    assert not crash_found, "Crash-time changes should be lost when residuals deleted"


def test_crash_recovery_corrupted_component(work_dir):
    """Test D: corrupted component file — can open_database handle it?"""
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("Test binary ch01 not found")
    binary_path = os.path.join(work_dir, "ch01")
    shutil.copy2(src, binary_path)
    idb_path = os.path.join(work_dir, "ch01.i64")

    # Phase 1: open, do work, SIGKILL
    w1 = WorkerProc(cwd=work_dir)
    w1.recv()
    w1.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    w1.send({"id": "2", "method": "plugin:rename",
             "params": {"addr": "main", "new_name": "corrupt_test"}})
    w1.send({"id": "3", "method": "save_database", "params": {}})

    import signal
    os.kill(w1.proc.pid, signal.SIGKILL)
    w1.proc.wait(timeout=5)
    w1._reader.close()
    w1._writer.close()
    try:
        w1._sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    w1._sock.close()

    residuals = _find_residual_files(idb_path)
    print(f"\n--- Residuals: {[os.path.basename(f) for f in residuals]} ---")

    if not residuals:
        pytest.skip("No residual files to corrupt")

    # Phase 2: corrupt .id0 (truncate to 0 bytes)
    stem = os.path.splitext(idb_path)[0]
    id0_path = stem + ".id0"
    if os.path.isfile(id0_path):
        original_size = os.path.getsize(id0_path)
        with open(id0_path, "wb") as f:
            f.truncate(0)
        print(f"Corrupted {os.path.basename(id0_path)}: {original_size} → 0 bytes")
    else:
        pytest.skip(".id0 not found in residuals")

    # Phase 3: try to open with corrupted component
    w2 = WorkerProc(cwd=work_dir)
    w2.recv()

    r = w2.send({"id": "1", "method": "open_database", "params": {"path": binary_path}})
    print(f"open_database with corrupted .id0: {r}")

    if "error" not in r:
        print("UNEXPECTED: open_database succeeded despite corruption")
        w2.send({"id": "99", "method": "close_database", "params": {}})
    else:
        print(f"open_database failed (expected): {r['error']}")

        # Phase 4: clean up residuals and retry with just .i64
        removed = _remove_residual_files(idb_path)
        print(f"Removed {len(removed)} corrupted residuals, retrying...")

        r2 = w2.send({"id": "2", "method": "open_database",
                       "params": {"path": binary_path}})
        print(f"open_database after cleanup: {r2}")
        if "error" not in r2:
            print("Recovery from .i64 succeeded after removing corrupted files")
            w2.send({"id": "99", "method": "close_database", "params": {}})
        else:
            print(f"Recovery also failed: {r2['error']}")

    try:
        w2.send({"id": "shutdown", "method": "shutdown", "params": {}})
    except Exception:
        pass
    w2.close()
