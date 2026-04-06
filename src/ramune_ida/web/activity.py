"""AI activity stream: ASGI middleware + WebSocket broadcast + history store."""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any

import orjson
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect


class ActivityEvent:
    """A single AI tool-call event."""

    __slots__ = (
        "id", "timestamp", "project_id", "tool_name",
        "params_summary", "params_full", "result_summary",
        "status", "duration_ms", "kind",
    )

    def __init__(
        self,
        tool_name: str,
        params_summary: str,
        project_id: str | None = None,
        kind: str = "read",
        params_full: dict | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.timestamp = time.time()
        self.project_id = project_id
        self.tool_name = tool_name
        self.params_summary = params_summary
        self.params_full = params_full
        self.result_summary: str | None = None
        self.status: str = "pending"
        self.duration_ms: float | None = None
        self.kind = kind

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "params_summary": self.params_summary,
            "status": self.status,
            "kind": self.kind,
        }
        if self.project_id:
            d["project_id"] = self.project_id
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.params_full:
            d["params"] = self.params_full
        if self.result_summary:
            d["result_summary"] = self.result_summary
        return d


def _extract_result_summary(body: bytes, rpc_id: str) -> str | None:
    """Try to extract a human-readable result summary from the SSE/JSON response."""
    try:
        # SSE format: "event: message\ndata: {json}\n\n"
        text = body.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            if line.startswith("data: "):
                data = orjson.loads(line[6:])
                result = data.get("result", {})
                content = result.get("content", [])
                if content and isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("text"):
                            # Parse the tool result text (JSON)
                            try:
                                parsed = orjson.loads(item["text"])
                                # Extract key fields for summary
                                parts = []
                                for key in ("result", "output", "error", "old_name", "new_name",
                                             "new_type", "old_type", "total", "status"):
                                    if key in parsed:
                                        val = str(parsed[key])
                                        if len(val) > 150:
                                            val = val[:147] + "..."
                                        parts.append(f"{key}={val}")
                                return ", ".join(parts[:4]) if parts else None
                            except Exception:
                                val = item["text"]
                                return val[:200] if len(val) > 200 else val
    except Exception:
        pass
    return None


def _summarize_params(tool_name: str, params: dict[str, Any]) -> str:
    """Extract the most informative fields from tool call params."""
    key_fields = ("func", "addr", "pattern", "new_name", "code", "path", "type")
    parts = []
    for field in key_fields:
        if field in params:
            val = str(params[field])
            if len(val) > 40:
                val = val[:37] + "..."
            parts.append(f"{field}={val}")
    return ", ".join(parts[:3])


class ActivityStore:
    """In-memory ring buffer of activity events + WebSocket fan-out."""

    def __init__(self, max_events: int = 1000) -> None:
        self._events: deque[ActivityEvent] = deque(maxlen=max_events)
        self._pending: dict[str, tuple[ActivityEvent, float]] = {}
        self._connections: set[WebSocket] = set()

    def record_start(self, rpc_id: str, event: ActivityEvent) -> None:
        self._events.append(event)
        self._pending[rpc_id] = (event, time.monotonic())
        self._broadcast(event)

    def record_complete(
        self, rpc_id: str, failed: bool = False,
        result_summary: str | None = None,
    ) -> None:
        entry = self._pending.pop(rpc_id, None)
        if entry is None:
            return
        event, start_time = entry
        event.status = "failed" if failed else "completed"
        event.duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        if result_summary:
            event.result_summary = result_summary
        self._broadcast(event)

    def get_history(
        self, limit: int = 50, project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events = list(self._events)
        if project_id:
            events = [e for e in events if e.project_id == project_id]
        return [e.to_dict() for e in events[-limit:]]

    def add_connection(self, ws: WebSocket) -> None:
        self._connections.add(ws)

    def remove_connection(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    def _broadcast(self, event: ActivityEvent) -> None:
        text = orjson.dumps(event.to_dict()).decode()
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                import asyncio
                asyncio.ensure_future(ws.send_text(text))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


class ActivityMiddleware:
    """ASGI middleware that intercepts MCP tool calls for the activity stream.

    Wraps the MCP ASGI app.  Only inspects POST requests whose body
    contains a ``tools/call`` JSON-RPC method.  Everything else is
    passed through untouched.
    """

    def __init__(self, app: ASGIApp, store: ActivityStore) -> None:
        self.app = app
        self.store = store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() != "POST":
            return await self.app(scope, receive, send)

        body_chunks: list[bytes] = []
        body_complete = False
        rpc_id: str | None = None

        async def buffered_receive() -> Message:
            nonlocal body_complete
            msg = await receive()
            if not body_complete:
                body_chunks.append(msg.get("body", b""))
                if not msg.get("more_body", False):
                    body_complete = True
                    self._on_request(b"".join(body_chunks))
            return msg

        def capture_rpc_id(rid: str | None) -> None:
            nonlocal rpc_id
            rpc_id = rid

        self._current_capture = capture_rpc_id

        response_status = 200
        response_chunks: list[bytes] = []

        async def capture_send(msg: Message) -> None:
            nonlocal response_status
            if msg["type"] == "http.response.start":
                response_status = msg.get("status", 200)
            elif msg["type"] == "http.response.body":
                if rpc_id is not None:
                    response_chunks.append(msg.get("body", b""))
                    if not msg.get("more_body", False):
                        summary = _extract_result_summary(
                            b"".join(response_chunks), rpc_id,
                        )
                        self.store.record_complete(
                            rpc_id,
                            failed=(response_status >= 400),
                            result_summary=summary,
                        )
            await send(msg)

        await self.app(scope, buffered_receive, capture_send)

    def _on_request(self, body: bytes) -> None:
        try:
            data = orjson.loads(body)
        except Exception:
            return

        # Handle both single and batched JSON-RPC
        messages = data if isinstance(data, list) else [data]
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("method") != "tools/call":
                continue
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            rpc_id = msg.get("id")

            project_id = arguments.get("project_id")
            summary = _summarize_params(tool_name, arguments)

            # Store full params (excluding project_id and overly long values)
            detail = {k: v for k, v in arguments.items() if k != "project_id"}
            for k, v in detail.items():
                if isinstance(v, str) and len(v) > 200:
                    detail[k] = v[:200] + "..."

            event = ActivityEvent(
                tool_name=tool_name,
                params_summary=summary,
                project_id=project_id,
                params_full=detail if detail else None,
            )

            if rpc_id is not None:
                rpc_id_str = str(rpc_id)
                self.store.record_start(rpc_id_str, event)
                if hasattr(self, "_current_capture"):
                    self._current_capture(rpc_id_str)


# ── WebSocket + HTTP endpoints ─────────────────────────────────────


def create_activity_routes(store: ActivityStore) -> list:
    from starlette.routing import Route, WebSocketRoute

    async def activity_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        store.add_connection(websocket)
        try:
            # Send recent history
            history = store.get_history(50)
            for event in history:
                await websocket.send_text(orjson.dumps(event).decode())
            # Keep alive — wait for client messages (pings)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            store.remove_connection(websocket)

    async def activity_history(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "50"))
        project_id = request.query_params.get("project_id")
        events = store.get_history(limit=limit, project_id=project_id)
        return JSONResponse({"events": events})

    return {
        "ws": WebSocketRoute("/ws/activity", activity_ws),
        "api": Route("/activity", activity_history),
    }
