"""Overview bar API endpoint with caching and rate-limited rescan."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ramune_ida.server.state import AppState
from ramune_ida.web.activity import ActivityStore
from ramune_ida.web.api.analysis import _execute_tool

log = logging.getLogger(__name__)

_RESCAN_COOLDOWN = 60.0


def _has_writes_since(
    activity_store: ActivityStore, project_id: str, since: float,
) -> bool:
    for event in reversed(list(activity_store._events)):
        if event.timestamp < since:
            break
        if (
            event.project_id == project_id
            and event.kind in ("write", "unsafe")
            and event.status == "completed"
        ):
            return True
    return False


class _OverviewCache:
    __slots__ = ("data", "cached_at", "last_rescan_at")

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.cached_at = time.time()
        self.last_rescan_at = time.time()


def create_routes(
    get_state: Callable[[], AppState],
    activity_store: ActivityStore,
) -> list[Route]:

    cache: dict[str, _OverviewCache] = {}
    rescan_locks: dict[str, bool] = {}

    async def _do_scan(pid: str) -> dict[str, Any] | None:
        try:
            state = get_state()
            project = state.projects.get(pid)
            if project is None:
                return None
            from ramune_ida.commands import PluginInvocation
            task = await project.execute(
                PluginInvocation("overview_scan", {}), timeout=120.0,
            )
            if task.error:
                log.warning("overview_scan failed for %s: %s", pid, task.error.message)
                return None
            return task.result
        except Exception as exc:
            log.warning("overview_scan error for %s: %s", pid, exc)
            return None

    async def _background_rescan(pid: str) -> None:
        if rescan_locks.get(pid):
            return
        rescan_locks[pid] = True
        try:
            result = await _do_scan(pid)
            if result:
                cache[pid] = _OverviewCache(result)
                log.info("Overview cache refreshed for %s", pid)
        finally:
            rescan_locks.pop(pid, None)

    async def overview(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]

        cached = cache.get(pid)

        if cached is None:
            result = await _do_scan(pid)
            if result is None:
                return JSONResponse({"error": "scan failed"}, status_code=500)
            cached = _OverviewCache(result)
            cache[pid] = cached
        else:
            if _has_writes_since(activity_store, pid, cached.cached_at):
                now = time.time()
                if now - cached.last_rescan_at > _RESCAN_COOLDOWN:
                    cached.last_rescan_at = now
                    asyncio.create_task(_background_rescan(pid))

        return JSONResponse(cached.data)

    return [
        Route("/projects/{pid}/overview", overview),
    ]
