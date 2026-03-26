"""Async wrapper around a single Worker subprocess.

Thin process manager: spawn, execute one command at a time, force kill.
Each Project owns one WorkerHandle.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import subprocess
from typing import Any

import orjson

from ramune_ida.protocol import Request, Response
from ramune_ida.worker.pipe_io import ENV_READ_FD, ENV_WRITE_FD

log = logging.getLogger(__name__)

_instance_counter = itertools.count(1)


class WorkerDead(Exception):
    """Raised when the worker process is no longer reachable."""


class WorkerHandle:
    """Async handle to one Worker subprocess.

    Owns a dedicated fd pair for IPC.  The owning Project
    must ensure only one ``execute()`` runs at a time per handle.
    """

    def __init__(self, python_path: str = "python") -> None:
        self._python_path = python_path

        self.instance_id: str = ""

        self._proc: subprocess.Popen[bytes] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._write_transport: asyncio.WriteTransport | None = None

        self._read_fd_file: Any = None
        self._write_fd_file: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def spawn(self) -> None:
        """Start a Worker subprocess and wait for its ready message."""
        self.instance_id = f"w-{next(_instance_counter):04d}"

        r_to_child, w_to_child = os.pipe()
        r_from_child, w_from_child = os.pipe()
        try:
            env = os.environ.copy()
            env[ENV_READ_FD] = str(r_to_child)
            env[ENV_WRITE_FD] = str(w_from_child)

            self._proc = subprocess.Popen(
                [self._python_path, "-m", "ramune_ida.worker.main"],
                env=env,
                pass_fds=(r_to_child, w_from_child),
            )
        except Exception:
            for fd in (r_to_child, w_to_child, r_from_child, w_from_child):
                os.close(fd)
            raise

        os.close(r_to_child)
        os.close(w_from_child)

        try:
            loop = asyncio.get_running_loop()

            self._read_fd_file = os.fdopen(r_from_child, "rb")
            self._reader = asyncio.StreamReader()
            await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(self._reader),
                self._read_fd_file,
            )

            self._write_fd_file = os.fdopen(w_to_child, "wb")
            transport, _ = await loop.connect_write_pipe(
                asyncio.BaseProtocol,
                self._write_fd_file,
            )
            self._write_transport = transport  # type: ignore[assignment]

            ready = await self._pipe_recv()
            if ready.error:
                raise WorkerDead(
                    f"Worker {self.instance_id} failed to start: {ready.error.message}"
                )
        except BaseException:
            self.kill()
            raise

        log.info("Worker %s ready (pid=%d)", self.instance_id, self._proc.pid)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def execute(self, request: Request) -> Response:
        """Send one command and wait for the response.

        The project's execution loop guarantees only one execute()
        runs at a time per handle.
        """
        await self._pipe_send(request)
        return await self._pipe_recv()

    def kill(self) -> None:
        """Forcefully terminate the Worker process and clean up."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None

        if self._write_transport:
            self._write_transport.close()
            self._write_transport = None
        self._reader = None
        self._read_fd_file = None
        self._write_fd_file = None

        log.info("Worker %s killed", self.instance_id)

    # ------------------------------------------------------------------
    # Pipe I/O
    # ------------------------------------------------------------------

    async def _pipe_send(self, request: Request) -> None:
        if self._write_transport is None:
            raise WorkerDead("pipe closed")
        data = orjson.dumps(request.to_dict()) + b"\n"
        self._write_transport.write(data)

    async def _pipe_recv(self) -> Response:
        if self._reader is None:
            raise WorkerDead("pipe closed")
        line = await self._reader.readline()
        if not line:
            raise WorkerDead("pipe EOF — worker process died")
        return Response.from_dict(orjson.loads(line))
