"""Worker process entry point.

Two modes of operation:

1. **--list-plugins** (lightweight)
   Output tool metadata JSON to stdout and exit.
   Does NOT import ``idapro`` — safe to call from the Server's Python.

2. **Normal** (default)
   Import ``idapro``, register handlers, enter message loop.

Usage::

    # Server-side discovery
    worker_python -m ramune_ida.worker.main --list-plugins

    # Normal (spawned by WorkerHandle)
    worker_python -m ramune_ida.worker.main
"""

from __future__ import annotations

import sys


def _list_plugins() -> None:
    """Dump tool metadata JSON to stdout (no IDA required)."""
    import json
    from ramune_ida.worker.plugins import discover_all

    tools, _ = discover_all()
    output = []
    for t in tools:
        meta = {k: v for k, v in t.items()
                if not k.startswith("_") and not callable(v)}
        output.append(meta)
    json.dump(output, sys.stdout)


def _run_worker() -> None:
    """Normal worker: IDA environment + message loop."""
    import signal
    import traceback

    # Must be the first import — initialises the IDA kernel.
    import idapro  # noqa: F401

    # Register lifecycle command handlers (decorator side-effect).
    import ramune_ida.worker.handlers.session  # noqa: F401

    # Register plugin-style tool handlers (built-in core + external plugins).
    from ramune_ida.worker.plugins import discover_all
    from ramune_ida.worker.dispatch import register_plugins

    all_tools, handler_map = discover_all()
    meta_map = {t["name"]: t for t in all_tools}
    register_plugins(handler_map, meta_map)

    from ramune_ida.worker import cancel
    from ramune_ida.worker.socket_io import SocketIO
    from ramune_ida.worker.dispatch import dispatch
    from ramune_ida.commands import Ping, Shutdown
    from ramune_ida.protocol import Method, Response

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGUSR1, lambda _sig, _frame: cancel.request())

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
        idapro.close_database(save=True)
    except Exception:
        pass


if __name__ == "__main__":
    if "--list-plugins" in sys.argv:
        _list_plugins()
    else:
        _run_worker()
