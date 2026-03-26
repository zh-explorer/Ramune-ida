"""Worker process entry point.

Lifecycle:
  1. Import idapro (must be the first import)
  2. Import all handlers to register them
  3. Open pipe I/O on dedicated fds (passed via env vars)
  4. Enter message loop: recv → dispatch → send
  5. Exit on EOF (parent closed pipe) or "shutdown" command

stdin/stdout/stderr are NOT touched — IDA console output and
print() work normally. The IPC protocol uses dedicated fd pairs.
"""

from __future__ import annotations

import sys
import traceback

# Step 1: import idapro — must be first
import idapro

# Step 2: register all handlers
import ramune_ida.worker.handlers.session  # noqa: F401
import ramune_ida.worker.handlers.analysis  # noqa: F401

from ramune_ida.worker.pipe_io import PipeIO
from ramune_ida.worker.dispatch import dispatch
from ramune_ida.protocol import Response


def main() -> None:
    pipe = PipeIO()

    # Notify parent that worker is ready
    pipe.send(Response.ok("__init__", {"status": "ready"}))

    while True:
        try:
            request = pipe.recv()
        except Exception:
            traceback.print_exc()
            break

        if request is None:
            break

        if request.method == "shutdown":
            pipe.send(Response.ok(request.id, {"status": "shutdown"}))
            break

        if request.method == "ping":
            pipe.send(Response.ok(request.id, {"status": "pong"}))
            continue

        response = dispatch(request)
        pipe.send(response)

    # Cleanup
    pipe.close()
    try:
        idapro.close_database(save=False)
    except Exception:
        pass


if __name__ == "__main__":
    main()
