"""HTTP file endpoints registered via ``@mcp.custom_route``.

All binary/large-text transfers bypass the MCP protocol to avoid
wasting token budget.  Every endpoint lives under ``/files/``.

Routing principle:

- **No project_id** → staging area (upload/download awaiting ``open_project``)
- **With project_id** → that project's ``work_dir``

Routes::

    POST /files                             upload to staging
    POST /files/{project_id}                upload to project work_dir
    GET  /files/{filename}                  download from staging
    GET  /files/{project_id}/{path:path}    download from project work_dir
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from ramune_ida.server.app import mcp, get_state


def _file_response(path: str) -> Response:
    return FileResponse(
        path,
        filename=os.path.basename(path),
        media_type="application/octet-stream",
    )


def _staging_dir() -> str:
    state = get_state()
    return os.path.join(state.config.resolved_work_base_dir, "_staging")


# ── Upload ────────────────────────────────────────────────────────


@mcp.custom_route("/files", methods=["POST"])
async def upload_to_staging(request: Request) -> Response:
    """Upload a binary to the staging area.

    Accepts ``multipart/form-data`` with a ``file`` field.
    Returns the server-side path for use with ``open_project``.
    """
    staging = _staging_dir()
    os.makedirs(staging, exist_ok=True)

    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "Missing 'file' field"}, status_code=400)

    content = await upload.read()  # type: ignore[union-attr]
    filename = getattr(upload, "filename", None) or "upload"
    dest = os.path.join(staging, filename)
    with open(dest, "wb") as f:
        f.write(content)
    return JSONResponse({"path": dest, "filename": filename, "size": len(content)})


@mcp.custom_route("/files/{project_id}", methods=["POST"])
async def upload_to_project(request: Request) -> Response:
    """Upload a file into a project's work directory."""
    state = get_state()
    project_id = request.path_params["project_id"]
    project = state.projects.get(project_id)
    if project is None:
        return JSONResponse(
            {"error": f"Unknown project: {project_id}"}, status_code=404
        )

    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "Missing 'file' field"}, status_code=400)

    content = await upload.read()  # type: ignore[union-attr]
    filename = getattr(upload, "filename", None) or "upload"
    dest = os.path.join(project.work_dir, filename)
    with open(dest, "wb") as f:
        f.write(content)
    return JSONResponse({
        "project_id": project_id,
        "path": dest,
        "filename": filename,
        "size": len(content),
    })


# ── Download ──────────────────────────────────────────────────────


@mcp.custom_route("/files/{filename}", methods=["GET"])
async def download_from_staging(request: Request) -> Response:
    """Download a file from the staging area."""
    filename = request.path_params["filename"]
    staging = _staging_dir()
    full_path = os.path.realpath(os.path.join(staging, filename))

    if not full_path.startswith(os.path.realpath(staging) + os.sep):
        return JSONResponse({"error": "Path traversal denied"}, status_code=403)
    if not os.path.isfile(full_path):
        return JSONResponse({"error": "File not found"}, status_code=404)

    return _file_response(full_path)


@mcp.custom_route("/files/{project_id}/{path:path}", methods=["GET"])
async def download_from_project(request: Request) -> Response:
    """Download any file from a project's work directory.

    Covers IDB, exe (when copied/linked into work_dir), outputs,
    and any other artefact the AI or worker placed there.
    """
    state = get_state()
    project_id = request.path_params["project_id"]
    rel_path = request.path_params["path"]

    project = state.projects.get(project_id)
    if project is None:
        return JSONResponse(
            {"error": f"Unknown project: {project_id}"}, status_code=404
        )

    full_path = os.path.realpath(os.path.join(project.work_dir, rel_path))
    work_dir_real = os.path.realpath(project.work_dir)

    if not full_path.startswith(work_dir_real + os.sep):
        return JSONResponse({"error": "Path traversal denied"}, status_code=403)
    if not os.path.isfile(full_path):
        return JSONResponse(
            {"error": f"File not found: {rel_path}"}, status_code=404
        )

    return _file_response(full_path)
