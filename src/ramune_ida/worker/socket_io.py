"""JSON line I/O over a UNIX socketpair.

The MCP Server creates a ``socket.socketpair()`` and passes one end
to the Worker subprocess via ``pass_fds``.  The fd number is
communicated through the ``RAMUNE_SOCK_FD`` environment variable.

Each socket is full-duplex, so a single fd replaces the previous
two-pipe (4 fd) design.  ``shutdown(SHUT_WR)`` provides a clean
EOF signal that the peer can detect reliably.

Protocol: one JSON object per line, terminated by ``\\n``.
"""

from __future__ import annotations

import os
import socket

import orjson

from ramune_ida.protocol import Request, Response

ENV_SOCK_FD = "RAMUNE_SOCK_FD"


class SocketIO:
    """Blocking JSON line reader/writer for the Worker side.

    Wraps a connected UNIX socket (passed via env var) into a
    file-like pair for line-oriented I/O, leaving stdin/stdout/stderr
    free for normal use.
    """

    def __init__(self, sock_fd: int | None = None) -> None:
        if sock_fd is None:
            sock_fd = int(os.environ[ENV_SOCK_FD])
        sock = socket.socket(fileno=sock_fd)
        sock.setblocking(True)
        self._sock = sock
        self._reader = sock.makefile("rb")
        self._writer = sock.makefile("wb")

    def recv(self) -> Request | None:
        """Read one request. Returns None on EOF (parent closed socket)."""
        line = self._reader.readline()
        if not line:
            return None
        return Request.from_dict(orjson.loads(line))

    def send(self, response: Response) -> None:
        """Write one response and flush."""
        self._writer.write(orjson.dumps(response.to_dict()))
        self._writer.write(b"\n")
        self._writer.flush()

    def close(self) -> None:
        """Graceful shutdown: signal EOF to peer, then close."""
        try:
            self._writer.flush()
            self._sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self._reader.close()
        self._writer.close()
        self._sock.close()
