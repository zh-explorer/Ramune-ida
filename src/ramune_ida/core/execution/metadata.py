"""Metadata for built-in execution tools (execute_python, …)."""

from __future__ import annotations

from ramune_ida.worker.tags import TAG_KIND_UNSAFE

TOOLS: list[dict] = [
    {
        "name": "execute_python",
        "description": "Execute IDAPython code.",
        "tags": ["execution", TAG_KIND_UNSAFE],
        "params": {
            "code": {
                "type": "string",
                "required": True,
                "description": "Assign _result for structured return",
            },
        },
    },
]
