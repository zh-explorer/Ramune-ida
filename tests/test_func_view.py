"""Test func_view handler mapping — requires real IDA.

Run: pytest tests/test_func_view.py --run-ida -s
"""

from __future__ import annotations

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


class WorkerProc:
    def __init__(self, cwd=None):
        parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        child_fd = child_sock.fileno()
        env = os.environ.copy()
        env[ENV_SOCK_FD] = str(child_fd)
        env["IDADIR"] = IDA_DIR
        env["PYTHONPATH"] = IDA_PYTHON_PATH + os.pathsep + env.get("PYTHONPATH", "")
        self.proc = subprocess.Popen(
            [PYTHON, "-m", "ramune_ida.worker.main"],
            env=env, cwd=cwd, pass_fds=(child_fd,),
        )
        child_sock.close()
        self._sock = parent_sock
        self._reader = parent_sock.makefile("rb")
        self._writer = parent_sock.makefile("wb")

    def send(self, msg):
        self._writer.write(orjson.dumps(msg) + b"\n")
        self._writer.flush()

    def recv(self):
        line = self._reader.readline()
        if not line:
            raise RuntimeError("Worker EOF")
        return orjson.loads(line)

    def call(self, msg):
        self.send(msg)
        resp = self.recv()
        while resp.get("id") != msg.get("id"):
            resp = self.recv()
        return resp

    def close(self):
        self._reader.close()
        self._writer.close()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        self.proc.wait(timeout=10)


@pytest.fixture
def work_dir(tmp_path):
    d = str(tmp_path / "work")
    os.makedirs(d)
    return d


@pytest.fixture
def worker_with_db(work_dir):
    src = os.path.join(BINARY_DIR, "ch01")
    if not os.path.isfile(src):
        pytest.skip("ch01 not found")
    shutil.copy2(src, os.path.join(work_dir, "ch01"))

    w = WorkerProc(cwd=work_dir)
    resp = w.call({"id": "open", "method": "open_database", "params": {"path": "ch01"}})
    assert resp.get("error") is None, f"open_database failed: {resp}"
    yield w
    w.close()


def test_ctree_explore(worker_with_db):
    """Explore ctree item attributes via execute_python."""
    w = worker_with_db

    code = '''
import ida_hexrays
import ida_funcs
import ida_name
import idaapi
import ida_lines

main_ea = ida_name.get_name_ea(0, "main")
func = ida_funcs.get_func(main_ea)
start_ea = func.start_ea
end_ea = func.end_ea
cfunc = ida_hexrays.decompile(start_ea)
ps = cfunc.get_pseudocode()

R = []
R.append(f"func: {start_ea:#x}-{end_ea:#x}")
R.append(f"pseudocode lines: {ps.size()}")

# Explore simpleline_t attributes
sl0 = ps.at(0)
R.append(f"simpleline_t type: {type(sl0).__name__}")
sl_attrs = [a for a in dir(sl0) if not a.startswith("_")]
R.append(f"simpleline_t attrs: {sl_attrs}")

# Check cfunc.boundaries
if hasattr(cfunc, "boundaries"):
    b = cfunc.boundaries
    R.append(f"boundaries type: {type(b).__name__}")
    R.append(f"boundaries len: {len(b)}")
    count = 0
    for key in b:
        val = b[key]
        R.append(f"  boundary key={key} type={type(key).__name__}")
        R.append(f"  boundary val type={type(val).__name__}")
        if hasattr(val, "__iter__"):
            for v in val:
                R.append(f"    sub-item: type={type(v).__name__}")
                for attr in ["start_ea", "end_ea", "startEA", "endEA"]:
                    if hasattr(v, attr):
                        R.append(f"      {attr}={getattr(v, attr):#x}")
                break
        count += 1
        if count >= 3:
            break
else:
    R.append("no boundaries attr")

# Check cfunc for pseudocode address methods
for method_name in ["find_closest_addr", "find_label", "calc_cmt_line_idx"]:
    R.append(f"has {method_name}: {hasattr(cfunc, method_name)}")

# Try using eamap to build a reverse mapping
# eamap: ea_t -> cinsnptrvec_t
# We need: for each cinsn_t, find its line in pseudocode
# The cinsn_t is part of the ctree. The treeitems vector has all items in order.
# Pseudocode is rendered from the ctree in order.
# So treeitems index correlates with pseudocode line (loosely).

R.append(f"eamap entries: {len(cfunc.eamap)}")
R.append(f"treeitems: {cfunc.treeitems.size()}")

# Try: map ea → cinsn index in treeitems, then correlate with line
# Build treeitem ea → index
ti_map = {}
for i in range(cfunc.treeitems.size()):
    ti = cfunc.treeitems[i]
    ea = int(ti.ea)
    if ea != idaapi.BADADDR and start_ea <= ea < end_ea:
        ti_map.setdefault(ea, []).append(i)

R.append(f"treeitems with valid ea: {len(ti_map)}")

# Now try: for each pseudocode line, examine the tagged line for COLOR_ADDR
# IDA uses SCOLOR_ADDR (0x05) followed by address bytes
for line_num in list(range(min(ps.size(), 5))) + list(range(90, min(ps.size(), 105))):
    sl = ps.at(line_num)
    raw = sl.line
    text = ida_lines.tag_remove(raw)
    # Show hex dump of first bytes to understand format
    hex_bytes = ' '.join(f"{ord(c):02x}" for c in raw[:40])
    R.append(f"line {line_num}: raw[0:40]={hex_bytes}")
    R.append(f"  text: {text[:60]}")

_result = "\\n".join(R)
'''

    resp = w.call({
        "id": "probe",
        "method": "plugin:execute_python",
        "params": {"code": code},
    })

    if resp.get("error"):
        print(f"\nERROR: {resp['error']}")
    else:
        r = resp["result"]
        print(f"\n=== result ===")
        stdout = r.get("stdout", "")
        output = r.get("output", "")
        print(f"stdout: {stdout}")
        print(f"output: {output}")
        # The execute_python handler returns the last expression as 'result'
        if "result" in r:
            print(f"result: {r['result']}")
        # Dump all keys
        print(f"keys: {list(r.keys())}")
        print(f"raw: {orjson.dumps(r).decode()[:2000]}")


def test_func_view_mapping(worker_with_db):
    """func_view should return non-empty line mappings."""
    w = worker_with_db

    resp = w.call({
        "id": "fv1",
        "method": "plugin:func_view",
        "params": {"func": "main"},
    })

    assert resp.get("error") is None, f"func_view error: {resp.get('error')}"
    result = resp["result"]

    decompile = result["decompile"]
    disasm = result["disasm"]

    dc_with_addrs = sum(1 for l in decompile if l["addrs"])
    da_with_lines = sum(1 for l in disasm if l["decompile_lines"])

    print(f"\nDecompile lines: {len(decompile)}, with addrs: {dc_with_addrs}")
    print(f"Disasm lines: {len(disasm)}, with decompile_lines: {da_with_lines}")

    for l in decompile:
        if l["addrs"]:
            print(f"  dc line {l['line']}: {l['addrs'][:3]}  {l['text'][:60]}")
            if l["line"] > 20:
                break

    count = 0
    for l in disasm:
        if l["decompile_lines"]:
            print(f"  asm {l['addr']}: lines={l['decompile_lines']}  {l['mnemonic']} {l['operands'][:40]}")
            count += 1
            if count > 10:
                break

    assert dc_with_addrs > 0, "No decompile lines have address mappings!"
    assert da_with_lines > 0, "No disasm lines have decompile line mappings!"
