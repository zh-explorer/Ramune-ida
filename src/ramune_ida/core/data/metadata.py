"""Metadata for data reading tools (examine, get_bytes)."""

from __future__ import annotations

from ramune_ida.worker.tags import TAG_KIND_READ

TOOLS: list[dict] = [
    {
        "name": "examine",
        "description": "Examine an address. Auto-detects type (code, string, data, struct, unknown) and returns value.",
        "tags": ["data", TAG_KIND_READ],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Address or name",
            },
            "count": {
                "type": "integer",
                "required": False,
                "description": "Limit number of elements for arrays, or bytes to read for unknown regions. 0 or omit for no limit.",
            },
        },
    },
    {
        "name": "get_bytes",
        "description": "Read raw bytes. Returns hex string.",
        "tags": ["data", TAG_KIND_READ],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
            },
            "size": {
                "type": "integer",
                "required": True,
            },
        },
    },
]
