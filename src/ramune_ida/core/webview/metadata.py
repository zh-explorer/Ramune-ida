"""Metadata for Web UI internal tools (not exposed to MCP)."""

from __future__ import annotations

from ramune_ida.worker.tags import TAG_KIND_READ, TAG_MCP_FALSE

TOOLS: list[dict] = [
    {
        "name": "func_view",
        "description": "Structured function view: decompile + disassembly + line mapping.",
        "tags": ["webview", TAG_KIND_READ, TAG_MCP_FALSE],
        "params": {
            "func": {
                "type": "string",
                "required": True,
                "description": "Name or hex address",
            },
        },
    },
    {
        "name": "linear_view",
        "description": "Linear disassembly view: returns formatted lines for an address range.",
        "tags": ["webview", TAG_KIND_READ, TAG_MCP_FALSE],
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
            "direction": {
                "type": "string",
                "required": False,
                "description": "forward (default) or backward",
            },
        },
    },
    {
        "name": "resolve",
        "description": "Resolve a name or address to its type and location.",
        "tags": ["webview", TAG_KIND_READ, TAG_MCP_FALSE],
        "params": {
            "target": {
                "type": "string",
                "required": True,
                "description": "Name, hex address, or symbol to resolve",
            },
        },
    },
    {
        "name": "hex_view",
        "description": "Hex dump view: returns rows of 16 bytes, skipping gaps.",
        "tags": ["webview", TAG_KIND_READ, TAG_MCP_FALSE],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Start address or name",
            },
            "count": {
                "type": "integer",
                "required": False,
                "description": "Number of rows to return (default 32)",
            },
            "direction": {
                "type": "string",
                "required": False,
                "description": "forward (default) or backward",
            },
        },
    },
    {
        "name": "overview_scan",
        "description": "Scan address space and return type regions (code/data/unknown).",
        "tags": ["webview", TAG_KIND_READ, TAG_MCP_FALSE],
        "params": {
            "start_ea": {
                "type": "string",
                "required": False,
                "description": "Start address (hex). Defaults to min_ea.",
            },
            "end_ea": {
                "type": "string",
                "required": False,
                "description": "End address (hex). Defaults to max_ea.",
            },
        },
        "timeout": 120,
    },
]
