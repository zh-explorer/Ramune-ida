"""Async wrapper around a single Worker subprocess.

Thin process manager: spawn, execute one command at a time, force kill.
Each Project owns one WorkerHandle.

IPC uses a UNIX socketpair — one socket per side, full duplex.
``asyncio.open_connection(sock=)`` gives us a standard
``(StreamReader, StreamWriter)`` pair on the server side.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import socket
import subprocess

import orjson

from ramune_ida.protocol import Request, Response
from ramune_ida.worker.socket_io import ENV_SOCK_FD

log = logging.getLogger(__name__)

_instance_counter = itertools.count(1)


class WorkerDead(Exception):
    """Raised when the worker process is no longer reachable."""


class WorkerHandle:
    """Async handle to one Worker subprocess.

    Owns one end of a UNIX socketpair for IPC.  The owning Project
    must ensure only one ``execute()`` runs at a time per handle.
    """

    def __init__(self, python_path: str = "python") -> None:
        self._python_path = python_path

        self.instance_id: str = ""

        self._proc: subprocess.Popen[bytes] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def spawn(self) -> None:
        """Start a Worker subprocess and wait for its ready message."""
        self.instance_id = f"w-{next(_instance_counter):04d}"

        parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        child_fd = child_sock.fileno()

        try:
            env = dict(__import__("os").environ)
            env[ENV_SOCK_FD] = str(child_fd)

            self._proc = subprocess.Popen(
                [self._python_path, "-m", "ramune_ida.worker.main"],
                env=env,
                pass_fds=(child_fd,),
            )
        except Exception:
            parent_sock.close()
            child_sock.close()
            raise
        finally:
            child_sock.close()

        try:
            parent_sock.setblocking(False)
            self._reader, self._writer = await asyncio.open_connection(
                sock=parent_sock,
            )

            ready = await self._recv()
            if ready.error:
                raise WorkerDead(
                    f"Worker {self.instance_id} failed to start: "
                    f"{ready.error.message}"
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
        await self._send(request)
        return await self._recv()

    def kill(self) -> None:
        """Forcefully terminate the Worker process and clean up."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None

        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        self._reader = None

        log.info("Worker %s killed", self.instance_id)

    # ------------------------------------------------------------------
    # Socket I/O
    # ------------------------------------------------------------------

    async def _send(self, request: Request) -> None:
        if self._writer is None:
            raise WorkerDead("socket closed")
        data = orjson.dumps(request.to_dict()) + b"\n"
        self._writer.write(data)
        await self._writer.drain()

    async def _recv(self) -> Response:
        if self._reader is None:
            raise WorkerDead("socket closed")
        line = await self._reader.readline()
        if not line:
            raise WorkerDead("socket EOF — worker process died")
        return Response.from_dict(orjson.loads(line))
