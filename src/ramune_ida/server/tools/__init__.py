"""Static tool registration — session, execution, and async-task tools.

Worker-forwarded analysis tools (decompile, disasm, …) are now
registered dynamically from ``core/`` metadata by
:mod:`~ramune_ida.server.plugins` during lifespan.

Only tools that need custom Server-side logic stay here.
"""

from ramune_ida.server.app import register_tool
from ramune_ida.server.tools import session

# ── Project lifecycle ─────────────────────────────────────────────

register_tool(
    description="Create a new project workspace. Returns project_id.",
)(session.open_project)

register_tool(
    description="Destroy a project and clean up its work directory.",
)(session.close_project)

register_tool(
    description="List all open projects and their status.",
)(session.projects)

# ── Database lifecycle ────────────────────────────────────────────

register_tool(
    description=(
        "Open a binary or IDB in the project. "
        "Returns a survey of the binary (arch, segments, function stats, imports) "
        "so you can start analysis immediately without a separate survey call."
    ),
)(session.open_database)

register_tool(
    description=(
        "Close the database and terminate the IDA process. "
        "The project stays alive. Set force=true to kill without saving."
    ),
)(session.close_database)

# ── Async tasks ───────────────────────────────────────────────────

register_tool(
    description="Poll the result of a long-running task.",
)(session.get_task_result)

register_tool(
    description="Cancel a task; kills the worker if graceful stop fails.",
)(session.cancel_task)
