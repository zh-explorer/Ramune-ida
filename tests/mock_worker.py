"""Fake Worker that responds to commands without IDA.

Used for unit tests.  Supports the same IPC protocol as the real
Worker (UNIX socketpair, JSON line) but returns canned responses
for lifecycle commands and echoes everything else.

Run with:
    RAMUNE_SOCK_FD=... python tests/mock_worker.py
"""

from __future__ import annotations

import os
import socket
import time

import orjson

ENV_SOCK_FD = "RAMUNE_SOCK_FD"


def main() -> None:
    sock_fd = int(os.environ[ENV_SOCK_FD])
    sock = socket.socket(fileno=sock_fd)
    sock.setblocking(True)
    reader = sock.makefile("rb")
    writer = sock.makefile("wb")

    current_db: str | None = None

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
            current_db = path
            send({"id": rid, "result": {"path": path}})

        elif method == "close_database":
            current_db = None
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
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()


if __name__ == "__main__":
    main()
