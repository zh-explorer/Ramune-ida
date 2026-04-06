"""Benchmark overview_scan + smooth algorithm on test binaries.

Run: pytest tests/bench_overview.py --run-ida -xvs
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
    def __init__(self, cwd):
        parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        child_fd = child_sock.fileno()
        env = os.environ.copy()
        env[ENV_SOCK_FD] = str(child_fd)
        env["IDADIR"] = IDA_DIR
        env["PYTHONPATH"] = IDA_PYTHON_PATH + os.pathsep + env.get("PYTHONPATH", "")
        self.proc = subprocess.Popen(
            [PYTHON, "-m", "ramune_ida.worker.main"],
            env=env, cwd=cwd, pass_fds=(child_fd,),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        child_sock.close()
        self._sock = parent_sock
        self._reader = parent_sock.makefile("rb")
        self._writer = parent_sock.makefile("wb")

    def recv(self):
        return orjson.loads(self._reader.readline())

    def send(self, msg):
        self._writer.write(orjson.dumps(msg) + b"\n")
        self._writer.flush()
        return self.recv()

    def close(self):
        try:
            self.send({"id": "shutdown", "method": "shutdown", "params": {}})
        except Exception:
            pass
        self.proc.wait(timeout=10)
        self._reader.close()
        self._writer.close()
        self._sock.close()


BENCH_CODE = r'''
import time
import ida_bytes, ida_ida, idc, idautils

min_ea = ida_ida.inf_get_min_ea()
max_ea = ida_ida.inf_get_max_ea()

# ── Phase 1: Scan ──
t0 = time.perf_counter()

regions = []
for seg_ea in idautils.Segments():
    seg_end = idc.get_segm_attr(seg_ea, idc.SEGATTR_END)
    ea = seg_ea
    cur_type = None
    cur_start = ea

    while ea < seg_end and ea != idc.BADADDR:
        flags = ida_bytes.get_flags(ea)
        if ida_bytes.is_code(flags):
            rtype = "code"
        elif ida_bytes.is_data(flags):
            rtype = "data"
        else:
            rtype = "unknown"

        if rtype != cur_type:
            if cur_type is not None:
                regions.append({"start": hex(cur_start), "end": hex(ea), "type": cur_type})
            cur_type = rtype
            cur_start = ea

        ea = idc.next_head(ea, seg_end)
        if ea == idc.BADADDR:
            ea = seg_end

    if cur_type is not None:
        regions.append({"start": hex(cur_start), "end": hex(seg_end), "type": cur_type})

scan_ms = round((time.perf_counter() - t0) * 1000, 2)

# Stats
type_counts = {}
for r in regions:
    type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1

# ── Phase 2: Smooth ──
def smooth_regions(regions, min_size):
    if len(regions) <= 1:
        return regions
    merged = [dict(regions[0])]
    for r in regions[1:]:
        size = int(r["end"], 16) - int(r["start"], 16)
        if size < min_size:
            merged[-1]["end"] = r["end"]
        else:
            merged.append(dict(r))
    final = [merged[0]]
    for r in merged[1:]:
        if r["type"] == final[-1]["type"]:
            final[-1]["end"] = r["end"]
        else:
            final.append(r)
    return final

total_range = max_ea - min_ea if max_ea > min_ea else 1
smooth_results = {}
for width in [1920, 3840, 7680]:
    min_sz = max(1, total_range // width)
    t1 = time.perf_counter()
    smoothed = smooth_regions(list(regions), min_sz)
    t2 = time.perf_counter()
    smooth_results[str(width)] = {
        "ms": round((t2 - t1) * 1000, 2),
        "before": len(regions),
        "after": len(smoothed),
        "min_size": min_sz,
    }

_result = {
    "scan_ms": scan_ms,
    "region_count": len(regions),
    "type_counts": type_counts,
    "addr_range": hex(total_range),
    "smooth": smooth_results,
}
'''


BINARIES = ["ch01", "ch05", "client", "server", "speed-re1", "speed-re5"]


@pytest.fixture(params=BINARIES)
def binary_name(request):
    return request.param


def test_overview_perf(binary_name, tmp_path):
    src = os.path.join(BINARY_DIR, binary_name)
    if not os.path.isfile(src):
        pytest.skip(f"Binary {binary_name} not found")

    work_dir = str(tmp_path / "work")
    os.makedirs(work_dir)
    dest = os.path.join(work_dir, binary_name)
    shutil.copy2(src, dest)

    w = WorkerProc(cwd=work_dir)
    init = w.recv()
    assert init["result"]["status"] == "ready"

    r = w.send({"id": "1", "method": "open_database", "params": {"path": dest}})
    assert "error" not in r

    r = w.send({"id": "2", "method": "plugin:execute_python", "params": {"code": BENCH_CODE}})
    assert "error" not in r, r.get("error")

    res = r["result"]["result"]
    print(f"\n{'='*60}")
    print(f"Binary: {binary_name} ({os.path.getsize(src) / 1024:.0f} KB)")
    print(f"Address range: {res['addr_range']}")
    print(f"Scan: {res['scan_ms']} ms → {res['region_count']} regions")
    print(f"Types: {res['type_counts']}")
    for w_str, s in res["smooth"].items():
        print(f"  Smooth @{w_str}px: {s['ms']}ms, "
              f"{s['before']} → {s['after']} regions (min_size={s['min_size']})")
    print(f"{'='*60}")

    w.close()
