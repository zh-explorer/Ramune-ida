"""Web UI ASGI application — combines Web API routes with the MCP app.

Usage from cli.py::

    from ramune_ida.web.app import create_combined_app
    asgi_app = create_combined_app(mcp_app=asgi_app, get_state=get_state)
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.types import ASGIApp

from ramune_ida.server.state import AppState
from ramune_ida.web.activity import ActivityMiddleware, ActivityStore, create_activity_routes
from ramune_ida.web.api import projects, analysis, listing, search, overview

log = logging.getLogger(__name__)


def create_combined_app(
    mcp_app: ASGIApp,
    get_state: Callable[[], AppState],
    dev_mode: bool = False,
) -> ASGIApp:
    """Wrap the MCP ASGI app with Web UI routes and activity middleware."""
    activity_store = ActivityStore()
    mcp_with_activity = ActivityMiddleware(mcp_app, activity_store)

    activity_routes = create_activity_routes(activity_store)

    api_routes = [
        *projects.create_routes(get_state),
        *analysis.create_routes(get_state),
        *listing.create_routes(get_state),
        *search.create_routes(get_state),
        *overview.create_routes(get_state, activity_store),
        activity_routes["api"],
    ]

    if dev_mode:
        frontend_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "web-ui", "dist",
        )
    else:
        frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")

    frontend_dir = os.path.abspath(frontend_dir)
    has_frontend = os.path.isdir(frontend_dir)

    routes = [
        Mount("/api", routes=api_routes),
        activity_routes["ws"],
    ]

    if has_frontend:
        routes.append(
            Mount("/assets", app=StaticFiles(directory=os.path.join(frontend_dir, "assets"))),
        )
        index_path = os.path.join(frontend_dir, "index.html")

        # Serve static files (WASM, etc.) before SPA fallback
        async def static_file(request):
            path = request.path_params.get("path", "")
            full = os.path.join(frontend_dir, path)
            if os.path.isfile(full) and not path.startswith("."):
                return FileResponse(full)
            return FileResponse(index_path)

        routes.append(Route("/{path:path}", static_file))
        routes.append(Route("/", lambda r: FileResponse(index_path)))

    web_app = Starlette(routes=routes)

    return _CombinedApp(web_app=web_app, mcp_app=mcp_with_activity, has_frontend=has_frontend)


class _CombinedApp:
    """ASGI dispatcher: Web UI routes vs MCP app.

    Intercepts the lifespan to initialise AppState at server startup
    (FastMCP only runs our lifespan per-session, not at startup).
    """

    _WEB_PREFIXES_BASE = ("/api/", "/api", "/ws/")

    def __init__(self, web_app: ASGIApp, mcp_app: ASGIApp, has_frontend: bool) -> None:
        self.web_app = web_app
        self.mcp_app = mcp_app
        self.has_frontend = has_frontend

    def _is_web_path(self, path: str) -> bool:
        if any(path.startswith(p) for p in self._WEB_PREFIXES_BASE):
            return True
        if self.has_frontend:
            if path == "/" or path.startswith("/assets/"):
                return True
            if not path.startswith(("/mcp", "/files/")):
                return True
        return False

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if self._is_web_path(path):
                await self.web_app(scope, receive, send)
                return

        await self.mcp_app(scope, receive, send)

    async def _handle_lifespan(self, scope, receive, send):
        """Initialise AppState at startup. Shutdown is handled by cli._serve()."""
        from starlette.types import Message

        startup_complete_sent = False

        async def wrapped_send(message: Message) -> None:
            nonlocal startup_complete_sent
            if message["type"] == "lifespan.startup.complete":
                if not startup_complete_sent:
                    startup_complete_sent = True
                    from ramune_ida.server.app import ensure_state
                    await ensure_state()
                    log.info("Web UI: AppState initialised")
            await send(message)

        await self.mcp_app(scope, receive, wrapped_send)
