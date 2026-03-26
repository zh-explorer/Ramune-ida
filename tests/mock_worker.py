"""Fake Worker that responds to commands without IDA.

Used for Pool unit tests.  Supports the same IPC protocol as the
real Worker (dedicated fd pair, JSON line) but returns canned
responses for lifecycle commands and echoes everything else.

Run with:
    RAMUNE_READ_FD=... RAMUNE_WRITE_FD=... python tests/mock_worker.py
"""

from __future__ import annotations

import os
import sys
import time

import orjson

ENV_READ_FD = "RAMUNE_READ_FD"
ENV_WRITE_FD = "RAMUNE_WRITE_FD"

_current_db: str | None = None


def main() -> None:
    global _current_db

    read_fd = int(os.environ[ENV_READ_FD])
    write_fd = int(os.environ[ENV_WRITE_FD])
    reader = os.fdopen(read_fd, "rb")
    writer = os.fdopen(write_fd, "wb")

    def send(msg: dict) -> None:
        writer.write(orjson.dumps(msg) + b"\n")
        writer.flush()

    send({"id": "__init__", "result": {"status": "ready"}})

    while True:
        line = reader.readline()
        if not line:
            break

        req = orjson.loads(line)
        rid = req["id"]
        method = req.get("method", "")
        params = req.get("params", {})

        if method == "shutdown":
            send({"id": rid, "result": {"status": "shutdown"}})
            break

        elif method == "ping":
            send({"id": rid, "result": {"status": "pong"}})

        elif method == "open_database":
            path = params.get("path", "")
            _current_db = path
            send({"id": rid, "result": {"path": path}})

        elif method == "close_database":
            _current_db = None
            send({"id": rid, "result": {"status": "closed"}})

        elif method == "save_database":
            send({"id": rid, "result": {"status": "saved"}})

        elif method == "slow_command":
            delay = params.get("delay", 5)
            time.sleep(delay)
            send({"id": rid, "result": {"delayed": delay}})

        else:
            send({"id": rid, "result": {"echo": method, "params": params}})

    reader.close()
    writer.close()


if __name__ == "__main__":
    main()
