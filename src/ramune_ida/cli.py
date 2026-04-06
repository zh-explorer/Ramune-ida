"""CLI entry point for ramune-ida.

Usage::

    ramune-ida                          # default http://127.0.0.1:8000
    ramune-ida http://0.0.0.0:8000     # Streamable HTTP
    ramune-ida sse://127.0.0.1:9000    # SSE (legacy)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
from urllib.parse import urlparse


def parse_transport_url(url: str) -> tuple[str, str, int]:
    """Parse a transport URL into *(transport, host, port)*.

    Supported schemes: ``http`` (→ streamable-http) and ``sse``.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000

    if scheme in ("http", "https"):
        transport = "streamable-http"
    elif scheme == "sse":
        transport = "sse"
    else:
        raise ValueError(f"Unsupported transport scheme: {scheme!r}")

    return transport, host, port


def main() -> None:
    from ramune_ida.config import DEFAULT_DATA_DIR, ENV_DATA_DIR

    env_data_dir = os.environ.get(ENV_DATA_DIR)

    parser = argparse.ArgumentParser(
        prog="ramune-ida",
        description="Headless IDA MCP Server",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8000",
        help="Transport URL: http://host:port, sse://host:port",
    )
    parser.add_argument(
        "--soft-limit", type=int, default=4,
        help="Advisory threshold for open worker instances (default: 4)",
    )
    parser.add_argument(
        "--hard-limit", type=int, default=8,
        help="Maximum worker instances; 0 = unlimited (default: 8)",
    )
    parser.add_argument(
        "--worker-python", default="python",
        help="Python interpreter for Worker subprocesses (default: python)",
    )
    parser.add_argument(
        "--data-dir", default=env_data_dir or DEFAULT_DATA_DIR,
        help=(
            "Base directory for projects and plugins "
            f"(env: {ENV_DATA_DIR}, default: {DEFAULT_DATA_DIR})"
        ),
    )
    parser.add_argument(
        "--auto-save-interval", type=float, default=300.0,
        help="Seconds between auto-saves; 0 = disabled (default: 300)",
    )
    parser.add_argument(
        "--output-max-length", type=int, default=20_000,
        help="Truncate tool output beyond this many chars (default: 20000)",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="Enable Web UI (served on the same port)",
    )

    args = parser.parse_args()

    from ramune_ida.config import ServerConfig
    from ramune_ida.server.app import configure, get_state, mcp

    config = ServerConfig(
        worker_python=args.worker_python,
        soft_limit=args.soft_limit,
        hard_limit=args.hard_limit,
        auto_save_interval=args.auto_save_interval,
        data_dir=args.data_dir,
        output_max_length=args.output_max_length,
    )
    configure(config)

    from mcp.server.transport_security import TransportSecuritySettings

    transport, host, port = parse_transport_url(args.url)
    mcp.settings.host = host
    mcp.settings.port = port

    if host in ("127.0.0.1", "localhost", "::1"):
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )
    else:
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    from starlette.types import ASGIApp, Receive, Scope, Send

    from ramune_ida.server.app import request_base_url

    class _HostCapture:
        """ASGI middleware that captures Host header into a ContextVar."""

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                for k, v in scope.get("headers", []):
                    if k == b"host":
                        tok = request_base_url.set(f"http://{v.decode()}")
                        try:
                            return await self.app(scope, receive, send)
                        finally:
                            request_base_url.reset(tok)
            await self.app(scope, receive, send)

    if transport == "streamable-http":
        asgi_app = mcp.streamable_http_app()
    else:
        asgi_app = mcp.sse_app()

    if args.web:
        from ramune_ida.web.app import create_combined_app
        asgi_app = create_combined_app(
            mcp_app=asgi_app,
            get_state=get_state,
            dev_mode=bool(os.environ.get("RAMUNE_WEB_DEV")),
        )

    asyncio.run(_serve(
        _HostCapture(asgi_app), host, port, mcp.settings.log_level.lower(),
    ))


async def _serve(app: object, host: str, port: int, log_level: str) -> None:
    """Run uvicorn with top-level signal handling for graceful shutdown."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # we handle signals

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    serve_task = asyncio.create_task(server.serve())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    await asyncio.wait(
        [serve_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if shutdown_event.is_set():
        from ramune_ida.server import app as _app

        if _app._state is not None:
            await _app._state.shutdown()
            _app._state = None

        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5.0)
        except asyncio.TimeoutError:
            serve_task.cancel()


if __name__ == "__main__":
    main()
