"""Worker process entry point.

Lifecycle:
  1. Import idapro (must be the first import)
  2. Import all handlers to register them
  3. Open socket I/O on the fd passed via env var
  4. Enter message loop: recv → dispatch → send
  5. Exit on EOF (parent closed socket) or "shutdown" command

stdin/stdout/stderr are NOT touched — IDA console output and
print() work normally. The IPC uses a UNIX socketpair.
"""

from __future__ import annotations

import sys
import traceback

# Step 1: import idapro — must be first
import idapro

# Step 2: register all handlers
import ramune_ida.worker.handlers.session  # noqa: F401
import ramune_ida.worker.handlers.analysis  # noqa: F401

from ramune_ida.worker.socket_io import SocketIO
from ramune_ida.worker.dispatch import dispatch
from ramune_ida.commands import Ping, Shutdown
from ramune_ida.protocol import Method, Response


def main() -> None:
    io = SocketIO()

    io.send(Response.ok("__init__", {"status": "ready"}))

    while True:
        try:
            request = io.recv()
        except Exception:
            traceback.print_exc()
            break

        if request is None:
            break

        if request.method == Method.SHUTDOWN.value:
            io.send(Response.ok(request.id, Shutdown.Result().to_dict()))
            break

        if request.method == Method.PING.value:
            io.send(Response.ok(request.id, Ping.Result().to_dict()))
            continue

        response = dispatch(request)
        io.send(response)

    io.close()
    try:
        idapro.close_database(save=False)
    except Exception:
        pass


if __name__ == "__main__":
    main()
