# Writing Plugins for Ramune-ida

Ramune-ida supports external plugins that add IDA analysis tools as MCP tools. Plugins are automatically discovered and registered — no source modification needed.

[中文版](writing-plugins_zh.md)

---

## How Plugins Work

Ramune-ida uses a **metadata-driven plugin architecture**. Each tool is defined by two files:

- `metadata.py` — declares the tool's name, description, parameters, tags, and timeout
- `handlers.py` — implements the handler function that runs inside the IDA worker process

At startup, the server spawns a worker subprocess with `--list-plugins`. The worker scans built-in tool packages (`core/`) and the external plugin directory, collects all metadata, and returns it as JSON. The server then dynamically generates MCP tool functions — complete with typed signatures, descriptions, and parameter validation — and registers them with FastMCP.

At runtime, when a client calls a plugin tool, the server wraps the call as a `PluginInvocation` command and sends it to the worker via the IPC pipe. The worker's dispatch layer looks up the handler by name and executes it.

```
Startup:
  Server ──subprocess──▶ Worker --list-plugins
                         │ scan core/ sub-packages
                         │ scan plugin folder
  Server ◀── JSON metadata ──┤
  │
  register_plugin_tools()
  → generate MCP tool functions with __signature__

Runtime:
  MCP Client → Server (plugin tool call)
    → PluginInvocation("plugin:<tool_name>", params)
    → Project.execute() → Worker IPC
    → Worker dispatch → handler function
    → dict result → MCP response
```

## Quick Start

Create a folder in `~/.ramune-ida/plugins/`:

```
~/.ramune-ida/plugins/
└── my_crypto/
    ├── __init__.py
    ├── metadata.py
    └── handlers.py
```

### 1. Define metadata

```python
# metadata.py
TOOLS = [
    {
        "name": "identify_crypto",
        "description": "Identify cryptographic algorithms by constant signatures (S-box, round constants).",
        "tags": ["crypto", "kind:read"],
        "params": {
            "addr": {
                "type": "string",
                "required": False,
                "description": "Limit scan to a specific function address or name",
            },
        },
        "timeout": 120,
    },
]
```

### 2. Implement handler

```python
# handlers.py
from ramune_ida.core import ToolError

def identify_crypto(params):
    import idaapi
    import ida_bytes

    addr = params.get("addr")
    # ... scan for crypto constants ...

    if not results:
        raise ToolError(-12, "No crypto patterns found")

    return {
        "algorithms": ["AES-128", "SHA-256"],
        "details": [
            {"name": "AES S-box", "addr": "0x4050A0", "confidence": 0.98},
        ],
    }
```

### 3. Export from package

```python
# __init__.py
from my_crypto.handlers import identify_crypto

__all__ = ["identify_crypto"]
```

Restart the server. The tool will appear in the MCP tool list automatically.

---

## Metadata Reference

Each entry in the `TOOLS` list:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Tool name, must be globally unique |
| `description` | str | yes | Shown to AI in MCP tool schema |
| `params` | dict | no | Parameter definitions (see below) |
| `tags` | list[str] | no | Framework tags + custom tags |
| `timeout` | int | no | Default timeout in seconds (default: 30) |
| `handler` | str | no | Handler function name if different from `name` |

Each parameter entry:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | str | `"string"` | `"string"`, `"integer"`, `"number"`, `"boolean"` |
| `required` | bool | `True` | Whether the parameter is required |
| `default` | any | — | Default value for optional parameters |
| `description` | str | — | Shown to AI in MCP tool schema |

## Framework Tags

Tags are plain strings in the `tags` list. The framework recognizes tags with the `kind:` prefix and applies automatic behavior:

| Tag | Meaning | Framework behavior |
|-----|---------|--------------------|
| `kind:read` | Read-only operation | No side effects |
| `kind:write` | Modifies the IDA database | Auto-creates an undo point before execution |
| `kind:unsafe` | Destructive or irreversible | Auto-creates an undo point; marked in MCP schema |

Write tools get automatic undo support — if the AI makes a mistake, `undo` reverts the change. No explicit save/snapshot is needed for individual modifications.

Custom tags (e.g. `"crypto"`, `"analysis"`) are passed through untouched and can be used for your own categorization.

### Example

```python
from ramune_ida.worker.tags import TAG_KIND_WRITE

TOOLS = [
    {
        "name": "apply_signature",
        "description": "Apply a FLIRT signature to a function.",
        "tags": ["signatures", TAG_KIND_WRITE],
        "params": { ... },
    },
]
```

You can also use the string literals directly: `"kind:read"`, `"kind:write"`, `"kind:unsafe"`.

## Handler Contract

```python
def tool_name(params: dict[str, Any]) -> dict[str, Any]:
```

- **Input**: `params` dict with fields as defined in metadata
- **Output**: `dict` — merged into the MCP tool response
- **Errors**: raise `ToolError(code, message)` for structured error responses
- **IDA imports**: import inside the function body (the module is loaded during `--list-plugins` without idalib)
- **Cancellation**: handled automatically by the dispatch layer via `sys.setprofile`; no action needed in handler code
- **Python version**: must be compatible with the Worker's Python (>= 3.10)

### Address resolution

Use `resolve_addr()` from `ramune_ida.core` to convert name-or-hex strings to integer addresses:

```python
from ramune_ida.core import resolve_addr, ToolError

def my_tool(params):
    ea = resolve_addr(params["addr"])  # "0x401000", "main", or "12345"
    # ... use ea ...
```

`resolve_addr` accepts `0x` hex, decimal integers, or IDA names. It raises `ToolError` if the name cannot be found.

## Built-in Tool Domains

Ramune-ida ships with 8 built-in tool packages under `core/`. They follow the exact same metadata + handler pattern as external plugins and serve as reference implementations.

| Domain | Package | Tools | Description |
|--------|---------|-------|-------------|
| Analysis | `core/analysis/` | `decompile`, `disasm`, `xrefs`, `survey` | Decompilation, disassembly, cross-references |
| Annotation | `core/annotate/` | `rename`, `get_comment`, `set_comment` | Symbol renaming, comments |
| Data | `core/data/` | `examine`, `get_bytes` | Memory inspection |
| Execution | `core/execution/` | `execute_python` | Arbitrary IDAPython execution |
| Listing | `core/listing/` | `list_funcs`, `list_strings`, `list_imports`, `list_names` | Enumeration with filtering/pagination |
| Search | `core/search/` | `search`, `search_bytes` | Regex and byte pattern search |
| Types | `core/types/` | `set_type`, `define_type` | Type annotation and declaration |
| Undo | `core/undo/` | `undo` | IDA 9.0+ native undo |

To add a new built-in tool, create a metadata entry and handler in the appropriate domain package — or create a new domain package under `core/`.

## Plugin Directory

Default: `~/.ramune-ida/plugins/`

Override with the `RAMUNE_PLUGIN_DIR` environment variable or the `--plugin-dir` CLI option.

The directory is scanned one level deep. Each sub-directory with a `metadata.py` is treated as a plugin package.

## Error Handling

Use `ToolError` for structured errors that should be returned to the AI:

```python
from ramune_ida.core import ToolError

def my_tool(params):
    addr = params.get("addr")
    if not addr:
        raise ToolError(-4, "Missing required parameter: addr")

    # ... work ...

    raise ToolError(-12, "Cannot resolve address")
```

Any other exception is caught by the dispatch layer and returned as an internal error with full traceback.

## Security Model

Plugins run inside the Worker process with full access to IDA APIs. The trust model is simple:

- **No sandbox** — IDA requires full system access for file I/O, memory mapping, etc.
- **Process isolation** — a plugin crash kills only its Worker, not the server or other workers. The project auto-restarts the worker on the next command.
- **Timeout protection** — the `timeout` value from metadata is enforced by the project layer
- **Cancellation** — `sys.setprofile` hook is automatically installed; long-running handlers can be interrupted via SIGUSR1 → SIGKILL escalation
- **Output truncation** — the server's output size limit applies uniformly to all tool responses

**Installing a plugin = trusting its code.** Review third-party plugins before deploying.

## Testing

Test handlers directly without the MCP server:

```python
def test_identify_crypto():
    from my_crypto.handlers import identify_crypto
    # mock IDA modules as needed
    result = identify_crypto({"addr": "0x401000"})
    assert "algorithms" in result
```

For integration testing through the full MCP stack, see `tests/test_mcp_tools.py` in the ramune-ida repository. It demonstrates how to use a mock worker that echoes plugin invocations.

## Name Conflicts

Tool names must be globally unique across all plugins and built-in tools. If a duplicate name is detected during discovery, the server will abort with an error message identifying both sources.

Use a namespace prefix for your tools: `crypto_identify` rather than `identify`.

## Complete Example: Crypto Identifier Plugin

```
~/.ramune-ida/plugins/
└── crypto_id/
    ├── __init__.py
    ├── metadata.py
    └── handlers.py
```

**metadata.py**:

```python
TOOLS = [
    {
        "name": "crypto_identify",
        "description": (
            "Scan binary for known cryptographic algorithm signatures. "
            "Checks S-boxes, round constants, and magic numbers against "
            "a built-in database of AES, DES, SHA, MD5, RC4, ChaCha20, etc."
        ),
        "tags": ["crypto", "kind:read"],
        "params": {
            "addr": {
                "type": "string",
                "required": False,
                "description": "Limit scan to a specific function (name or hex address). Scans all segments if omitted.",
            },
            "min_confidence": {
                "type": "number",
                "required": False,
                "default": 0.7,
                "description": "Minimum confidence threshold (0.0 - 1.0)",
            },
        },
        "timeout": 120,
    },
    {
        "name": "crypto_label",
        "description": "Label identified crypto constants with descriptive names and comments.",
        "tags": ["crypto", "kind:write"],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Address of the crypto constant to label",
            },
            "algorithm": {
                "type": "string",
                "required": True,
                "description": "Algorithm name (e.g. 'AES-128', 'SHA-256')",
            },
        },
    },
]
```

**handlers.py**:

```python
from ramune_ida.core import ToolError, resolve_addr

KNOWN_SBOXES = { ... }  # algorithm → byte signature

def crypto_identify(params):
    import ida_bytes
    import ida_segment
    import idautils

    addr = params.get("addr")
    min_conf = params.get("min_confidence", 0.7)

    if addr:
        ea = resolve_addr(addr)
        segments = [(ea, ea + 0x10000)]
    else:
        segments = [(s.start_ea, s.end_ea) for s in idautils.Segments()]

    results = []
    for start, end in segments:
        for algo, sig in KNOWN_SBOXES.items():
            found = ida_bytes.bin_search(start, end, sig, None, 0, 0)
            if found != 0xFFFFFFFFFFFFFFFF:
                results.append({
                    "algorithm": algo,
                    "addr": hex(found),
                    "confidence": 0.95,
                })

    return {
        "count": len(results),
        "results": [r for r in results if r["confidence"] >= min_conf],
    }


def crypto_label(params):
    import ida_name
    import ida_bytes

    ea = resolve_addr(params["addr"])
    algo = params["algorithm"]

    ida_name.set_name(ea, f"{algo}_constant", ida_name.SN_FORCE)
    ida_bytes.set_cmt(ea, f"Identified as {algo} constant table", True)

    return {"addr": hex(ea), "label": f"{algo}_constant"}
```

**__init__.py**:

```python
from crypto_id.handlers import crypto_identify, crypto_label

__all__ = ["crypto_identify", "crypto_label"]
```
