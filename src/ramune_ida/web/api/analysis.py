"""Analysis view API endpoints (decompile, disasm, xrefs, etc.)."""

from __future__ import annotations

from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ramune_ida.commands import PluginInvocation
from ramune_ida.server.state import AppState

# Map IPC error codes → HTTP status.
# Business errors (not found, decompile failed) are not 500.
_ERROR_HTTP: dict[int, int] = {
    -2: 400,   # INVALID_REQUEST
    -3: 404,   # METHOD_NOT_FOUND
    -4: 400,   # INVALID_PARAMS
    -5: 500,   # INTERNAL_ERROR
    -10: 409,  # DATABASE_NOT_OPEN
    -11: 409,  # DATABASE_OPEN_FAILED
    -12: 404,  # FUNCTION_NOT_FOUND
    -13: 422,  # DECOMPILE_FAILED
    -14: 504,  # TIMEOUT
    -15: 422,  # PYTHON_EXEC_ERROR
    -16: 499,  # CANCELLED
}


async def _execute_tool(
    get_state: Callable[[], AppState],
    project_id: str,
    tool_name: str,
    params: dict[str, Any],
    timeout: float = 30.0,
) -> JSONResponse:
    try:
        state = get_state()
    except RuntimeError:
        return JSONResponse({"error": "Server not ready"}, status_code=503)
    project = state.projects.get(project_id)
    if project is None:
        return JSONResponse(
            {"error": f"Unknown project: {project_id}"}, status_code=404,
        )
    invocation = PluginInvocation(tool_name, params)
    try:
        task = await project.execute(invocation, timeout=timeout)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    if task.error:
        http_status = _ERROR_HTTP.get(task.error.code, 500)
        return JSONResponse(
            {"error": task.error.message, "code": task.error.code},
            status_code=http_status,
        )
    if not task.is_done:
        return JSONResponse(
            {"status": "pending", "task_id": task.task_id}, status_code=202,
        )
    return JSONResponse(task.result or {})


def create_routes(get_state: Callable[[], AppState]) -> list[Route]:
    """Return Starlette Route objects for analysis endpoints."""

    async def decompile(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        func = request.query_params.get("func")
        if not func:
            return JSONResponse({"error": "Missing 'func' param"}, status_code=400)
        return await _execute_tool(get_state, pid, "decompile", {"func": func})

    async def disasm(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        addr = request.query_params.get("addr")
        if not addr:
            return JSONResponse({"error": "Missing 'addr' param"}, status_code=400)
        params: dict[str, Any] = {"addr": addr}
        count = request.query_params.get("count")
        if count:
            params["count"] = int(count)
        return await _execute_tool(get_state, pid, "disasm", params)

    async def xrefs(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        addr = request.query_params.get("addr")
        if not addr:
            return JSONResponse({"error": "Missing 'addr' param"}, status_code=400)
        return await _execute_tool(get_state, pid, "xrefs", {"addr": addr})

    async def examine(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        addr = request.query_params.get("addr")
        if not addr:
            return JSONResponse({"error": "Missing 'addr' param"}, status_code=400)
        return await _execute_tool(get_state, pid, "examine", {"addr": addr})

    async def get_bytes(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        addr = request.query_params.get("addr")
        if not addr:
            return JSONResponse({"error": "Missing 'addr' param"}, status_code=400)
        params: dict[str, Any] = {"addr": addr}
        size = request.query_params.get("size")
        if size:
            params["size"] = int(size)
        return await _execute_tool(get_state, pid, "get_bytes", params)

    async def survey(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        return await _execute_tool(get_state, pid, "survey", {})

    async def func_view(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        func = request.query_params.get("func")
        if not func:
            return JSONResponse({"error": "Missing 'func' param"}, status_code=400)
        return await _execute_tool(get_state, pid, "func_view", {"func": func})

    async def linear_view(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        addr = request.query_params.get("addr")
        if not addr:
            return JSONResponse({"error": "Missing 'addr' param"}, status_code=400)
        params: dict[str, Any] = {"addr": addr}
        count = request.query_params.get("count")
        if count:
            params["count"] = int(count)
        direction = request.query_params.get("direction")
        if direction:
            params["direction"] = direction
        return await _execute_tool(get_state, pid, "linear_view", params)

    async def local_types(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        return await _execute_tool(get_state, pid, "list_local_types", {})

    async def resolve(request: Request) -> JSONResponse:
        pid = request.path_params["pid"]
        target = request.query_params.get("target")
        if not target:
            return JSONResponse({"error": "Missing 'target' param"}, status_code=400)
        return await _execute_tool(get_state, pid, "resolve", {"target": target})

    return [
        Route("/projects/{pid}/decompile", decompile),
        Route("/projects/{pid}/disasm", disasm),
        Route("/projects/{pid}/xrefs", xrefs),
        Route("/projects/{pid}/examine", examine),
        Route("/projects/{pid}/bytes", get_bytes),
        Route("/projects/{pid}/survey", survey),
        Route("/projects/{pid}/func_view", func_view),
        Route("/projects/{pid}/linear_view", linear_view),
        Route("/projects/{pid}/resolve", resolve),
        Route("/projects/{pid}/local_types", local_types),
    ]
