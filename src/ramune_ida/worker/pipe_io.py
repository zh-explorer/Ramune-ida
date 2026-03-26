"""JSON line I/O over dedicated file descriptor pairs.

The MCP Server creates two os.pipe() pairs and passes the fd numbers
to the Worker via environment variables. stdin/stdout/stderr are
completely untouched — IDA console messages, print(), and logging
all work normally.

Protocol: one JSON object per line, terminated by '\\n'.
"""

from __future__ import annotations

import os

import orjson

from ramune_ida.protocol import Request, Response

ENV_READ_FD = "RAMUNE_READ_FD"
ENV_WRITE_FD = "RAMUNE_WRITE_FD"


class PipeIO:
    """Blocking JSON line reader/writer for the Worker side.

    Reads/writes on dedicated fds passed via environment variables,
    leaving stdin/stdout/stderr free for normal use.
    """

    def __init__(self, read_fd: int | None = None, write_fd: int | None = None):
        if read_fd is None:
            read_fd = int(os.environ[ENV_READ_FD])
        if write_fd is None:
            write_fd = int(os.environ[ENV_WRITE_FD])

        self._reader = os.fdopen(read_fd, "rb")
        self._writer = os.fdopen(write_fd, "wb")

    def recv(self) -> Request | None:
        """Read one request. Returns None on EOF (parent closed pipe)."""
        line = self._reader.readline()
        if not line:
            return None
        data = orjson.loads(line)
        return Request.from_dict(data)

    def send(self, response: Response) -> None:
        """Write one response and flush."""
        raw = orjson.dumps(response.to_dict())
        self._writer.write(raw)
        self._writer.write(b"\n")
        self._writer.flush()

    def close(self) -> None:
        self._reader.close()
        self._writer.close()
