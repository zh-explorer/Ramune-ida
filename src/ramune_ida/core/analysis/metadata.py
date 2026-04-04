"""Metadata for built-in analysis tools (decompile, disasm, …)."""

from __future__ import annotations

from ramune_ida.worker.tags import TAG_KIND_READ, TAG_MCP_FALSE

TOOLS: list[dict] = [
    {
        "name": "decompile",
        "description": "Decompile a function.",
        "tags": ["analysis", TAG_KIND_READ],
        "params": {
            "func": {
                "type": "string",
                "required": True,
                "description": "Name or hex address",
            },
        },
    },
    {
        "name": "disasm",
        "description": "Disassemble from an address.",
        "tags": ["analysis", TAG_KIND_READ],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Address or name",
            },
            "count": {
                "type": "integer",
                "required": False,
                "description": "Number of instructions. Omit to disassemble the entire function if addr belongs to one.",
            },
        },
    },
    {
        "name": "xrefs",
        "description": "List cross-references to a target.",
        "tags": ["analysis", TAG_KIND_READ],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Address or name",
            },
        },
    },
    {
        "name": "survey",
        "description": "Binary overview: file identity, segments, entry/exports, function stats, import modules.",
        "tags": ["analysis", TAG_KIND_READ],
        "params": {},
    },
    {
        "name": "linear_view",
        "description": "Linear disassembly view: returns formatted lines for an address range.",
        "tags": ["analysis", TAG_KIND_READ, TAG_MCP_FALSE],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Start address or name",
            },
            "count": {
                "type": "integer",
                "required": False,
                "description": "Number of lines to return (default 100)",
            },
        },
    },
    {
        "name": "func_view",
        "description": "Structured function view: decompile + disassembly + line mapping.",
        "tags": ["analysis", TAG_KIND_READ, TAG_MCP_FALSE],
        "params": {
            "func": {
                "type": "string",
                "required": True,
                "description": "Name or hex address",
            },
        },
    },
]
