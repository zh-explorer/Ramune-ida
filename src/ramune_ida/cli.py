"""CLI entry point for ramune-ida.

Usage::

    ramune-ida                          # default http://127.0.0.1:8000
    ramune-ida http://0.0.0.0:8000     # Streamable HTTP
    ramune-ida sse://127.0.0.1:9000    # SSE (legacy)
"""

from __future__ import annotations

import argparse
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
        "--work-dir", default="~/.ramune-ida/projects",
        help="Base directory for project work dirs (default: ~/.ramune-ida/projects)",
    )
    parser.add_argument(
        "--auto-save-interval", type=float, default=300.0,
        help="Seconds between auto-saves; 0 = disabled (default: 300)",
    )
    parser.add_argument(
        "--output-max-length", type=int, default=50_000,
        help="Truncate tool output beyond this many chars (default: 50000)",
    )

    args = parser.parse_args()

    from ramune_ida.config import ServerConfig
    from ramune_ida.server.app import configure, mcp

    config = ServerConfig(
        worker_python=args.worker_python,
        soft_limit=args.soft_limit,
        hard_limit=args.hard_limit,
        auto_save_interval=args.auto_save_interval,
        work_base_dir=args.work_dir,
        output_max_length=args.output_max_length,
    )
    configure(config)

    transport, host, port = parse_transport_url(args.url)
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
