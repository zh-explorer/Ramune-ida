"""Tool Registry — the single place that declares every MCP tool.

Open this file to see all available tools at a glance: name,
description, and which module implements it.

Implementation functions live in sibling modules (session.py,
analysis.py, …).  This file only handles **registration**.

Adding a new tool
-----------------
1. ``commands.py``  — define the Command + Result dataclass
2. ``worker/handlers/*.py``  — implement the IDA-side handler
3. ``server/tools/<module>.py``  — write the MCP-side async function
4. **Here** — add a ``register_tool(description=...)(impl)`` entry
"""

from ramune_ida.server.app import register_tool
from ramune_ida.server.tools import session

# ── Project lifecycle ─────────────────────────────────────────────

register_tool(
    description=(
        "Open a binary for analysis. Spawns an IDA worker and begins "
        "auto-analysis immediately — the first open may take minutes "
        "for large binaries.\n\n"
        "Returns the assigned project_id. If analysis is still running "
        "when the call returns, a task_id is included for polling."
    ),
)(session.open_project)

register_tool(
    description=(
        "Destroy a project completely: gracefully close the database "
        "(save + exit), then remove the project from server state and "
        "clean up the work directory.  Use this when you are done "
        "analysing a binary."
    ),
)(session.close_project)

# ── Worker instance management ────────────────────────────────────

register_tool(
    description=(
        "Close the IDA worker instance for a project (save + exit).  "
        "The project stays alive — the next analysis command will "
        "automatically respawn a fresh worker.  Use this to free "
        "resources when you don't need a project actively running."
    ),
)(session.close_database)

register_tool(
    description=(
        "Forcefully kill the IDA worker process.  No saving, no "
        "graceful shutdown.  Use when IDA is stuck or unresponsive.  "
        "The project stays alive and the next command will spawn a "
        "fresh worker."
    ),
)(session.force_close)

# ── Navigation ────────────────────────────────────────────────────

register_tool(
    description="Switch the default project pointer to a different project.",
)(session.switch_default)

# ── Async task polling ────────────────────────────────────────────

register_tool(
    description=(
        "Poll the result of a long-running task that timed out.  "
        "Returns the task status and result/error if completed."
    ),
)(session.get_task_result)
