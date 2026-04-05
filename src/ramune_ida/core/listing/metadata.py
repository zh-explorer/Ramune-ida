"""Metadata for listing tools (list_funcs, list_strings, …)."""

from __future__ import annotations

from ramune_ida.worker.tags import TAG_KIND_READ

_COMMON_PARAMS: dict[str, dict] = {
    "filter": {
        "type": "string",
        "required": False,
        "description": "Substring filter (include match)",
    },
    "exclude": {
        "type": "string",
        "required": False,
        "description": "Substring filter (exclude match)",
    },
}

TOOLS: list[dict] = [
    {
        "name": "list_funcs",
        "description": "List functions.",
        "tags": ["listing", TAG_KIND_READ],
        "params": {**_COMMON_PARAMS},
    },
    {
        "name": "list_strings",
        "description": "List strings found in the binary.",
        "tags": ["listing", TAG_KIND_READ],
        "params": {
            **_COMMON_PARAMS,
            "start_ea": {
                "type": "string",
                "required": False,
                "description": "Start address (hex) to filter strings; inclusive.",
            },
            "end_ea": {
                "type": "string",
                "required": False,
                "description": "End address (hex) to filter strings; exclusive.",
            },
        },
    },
    {
        "name": "list_imports",
        "description": "List imported functions.",
        "tags": ["listing", TAG_KIND_READ],
        "params": {**_COMMON_PARAMS},
    },
    {
        "name": "list_names",
        "description": "List all named addresses (functions, globals, labels).",
        "tags": ["listing", TAG_KIND_READ],
        "params": {**_COMMON_PARAMS},
    },
    {
        "name": "list_types",
        "description": "List types in the local type library (structs, enums, unions, typedefs).",
        "tags": ["listing", TAG_KIND_READ],
        "params": {
            **_COMMON_PARAMS,
            "kind": {
                "type": "string",
                "required": False,
                "description": "Filter by kind: struct, enum, union, typedef",
            },
        },
    },
]
