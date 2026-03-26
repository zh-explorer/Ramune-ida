"""End-to-end test: spawn a Worker subprocess and talk to it via dedicated fd pipes."""

import subprocess
import sys
import os

import orjson

WORKER_MODULE = "ramune_ida.worker.main"
TEST_BINARY = os.path.join(os.path.dirname(__file__), "ch01")


class WorkerProc:
    """Helper to manage a Worker subprocess with dedicated pipe fds."""

    def __init__(self):
        # parent → child
        r_to_child, self._w_to_child = os.pipe()
        # child → parent
        self._r_from_child, w_from_child = os.pipe()

        env = os.environ.copy()
        env["RAMUNE_READ_FD"] = str(r_to_child)
        env["RAMUNE_WRITE_FD"] = str(w_from_child)

        self.proc = subprocess.Popen(
            [sys.executable, "-m", WORKER_MODULE],
            env=env,
            pass_fds=(r_to_child, w_from_child),
        )

        # Close child-side fds in parent
        os.close(r_to_child)
        os.close(w_from_child)

        # Wrap parent-side fds as file objects
        self._reader = os.fdopen(self._r_from_child, "rb")
        self._writer = os.fdopen(self._w_to_child, "wb")

    def send(self, msg: dict) -> dict:
        raw = orjson.dumps(msg) + b"\n"
        self._writer.write(raw)
        self._writer.flush()
        return self.recv_one()

    def recv_one(self) -> dict:
        line = self._reader.readline()
        if not line:
            raise RuntimeError("Worker closed pipe (EOF)")
        return orjson.loads(line)

    def close(self):
        self._reader.close()
        self._writer.close()
        self.proc.wait(timeout=10)


def main():
    print(f"[*] Spawning worker: {sys.executable} -m {WORKER_MODULE}")
    w = WorkerProc()

    try:
        # 1. Init handshake
        init = w.recv_one()
        print(f"[+] Worker init: {init}")
        assert init["result"]["status"] == "ready"

        # 2. Ping
        resp = w.send({"id": "1", "method": "ping", "params": {}})
        print(f"[+] Ping: {resp}")
        assert resp["result"]["status"] == "pong"

        # 3. Unknown method
        resp = w.send({"id": "2", "method": "no_such_method", "params": {}})
        print(f"[+] Unknown method: {resp}")
        assert "error" in resp

        # 4. Open database
        print(f"[*] Opening database: {TEST_BINARY}")
        resp = w.send({"id": "3", "method": "open_database", "params": {"path": TEST_BINARY}})
        print(f"[+] Open: {resp}")
        if "error" in resp:
            print(f"[!] Open failed: {resp['error']}")
            return

        # 5. Decompile main
        resp = w.send({"id": "4", "method": "decompile", "params": {"func": "main"}})
        print(f"[+] Decompile main:")
        if "error" in resp:
            print(f"    Error: {resp['error']}")
        else:
            code = resp["result"]["code"]
            for line in code.split("\n")[:20]:
                print(f"    {line}")
            if code.count("\n") > 20:
                print(f"    ... ({code.count(chr(10))} lines total)")

        # 6. Disasm
        resp = w.send({"id": "5", "method": "disasm", "params": {"addr": "main", "count": 5}})
        print(f"[+] Disasm main (first 5):")
        if "error" in resp:
            print(f"    Error: {resp['error']}")
        else:
            for line in resp["result"]["lines"]:
                print(f"    {line['addr']}: {line['disasm']}")

        # 7. Close database
        resp = w.send({"id": "6", "method": "close_database", "params": {}})
        print(f"[+] Close: {resp}")

        # 8. Shutdown
        resp = w.send({"id": "99", "method": "shutdown", "params": {}})
        print(f"[+] Shutdown: {resp}")

    finally:
        w.close()
        print(f"[*] Worker exited with code {w.proc.returncode}")


if __name__ == "__main__":
    main()
