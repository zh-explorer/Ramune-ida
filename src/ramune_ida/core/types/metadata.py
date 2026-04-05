"""Metadata for type system tools (set_type, define_type, get_type)."""

from __future__ import annotations

from ramune_ida.worker.tags import TAG_KIND_READ, TAG_KIND_WRITE

TOOLS: list[dict] = [
    {
        "name": "set_type",
        "description": (
            "Set type. "
            "Use addr for function signatures or global data types, "
            "or func+var for local variable types. "
            "Accepts any C type syntax."
        ),
        "tags": ["types", TAG_KIND_WRITE],
        "params": {
            "addr": {
                "type": "string",
                "required": False,
                "description": "Target address or name (function/global)",
            },
            "func": {
                "type": "string",
                "required": False,
                "description": "Containing function (for local variable)",
            },
            "var": {
                "type": "string",
                "required": False,
                "description": "Variable name (for local variable)",
            },
            "type": {
                "type": "string",
                "required": True,
                "description": "C type expression",
            },
        },
    },
    {
        "name": "define_type",
        "description": (
            "Declare C types in the local type library. "
            "Accepts struct, enum, typedef, union declarations. "
            "Re-declaring an existing type updates it."
        ),
        "tags": ["types", TAG_KIND_WRITE],
        "params": {
            "declare": {
                "type": "string",
                "required": True,
                "description": "C type declaration(s)",
            },
        },
    },
    {
        "name": "get_type",
        "description": (
            "Get the full C definition of a type. "
            "Call again for nested types."
        ),
        "tags": ["types", TAG_KIND_READ],
        "params": {
            "name": {
                "type": "string",
                "required": True,
                "description": "Type name to look up",
            },
        },
    },
]
