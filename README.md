# Ramune-ida

> **[WIP] This project is under active development. APIs and features may change without notice.**

Headless IDA Pro MCP Server — expose IDA Pro's reverse engineering capabilities to AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

[中文版](README_zh.md)

---

## What is this?

Ramune-ida runs IDA Pro (idalib) in headless mode and wraps it as an MCP server. AI agents like Claude, Cursor, or any MCP-compatible client can decompile functions, rename symbols, set types, and execute arbitrary IDAPython — all through structured tool calls.

## Key Design Decisions

**Process separation** — The MCP server and IDA run in separate processes. The server is pure async Python; each IDA worker is a single-threaded subprocess communicating via dedicated fd-pair pipes (JSON line protocol). This eliminates all thread-safety issues that plague IDA SDK usage.

**Plugin architecture** — Tools are defined by metadata (description, parameters, tags) and handler functions. The server discovers tools at startup, dynamically generates MCP tool functions, and dispatches calls to the worker. Adding a new tool requires only a metadata file and a handler — no boilerplate registration code.

**Worker is stateless** — Workers are disposable command executors. All management state (task queues, crash recovery) lives in the Project layer. If a worker crashes, the project spawns a new one and reopens the IDB transparently.

## Architecture

```
MCP Client (Claude / Cursor / ...)
    │  Streamable HTTP / SSE
    ▼
┌──────────────────────────────────┐
│  MCP Server (async Python)       │
│  FastMCP + Project management    │
│  Plugin discovery + registration │
└──────────────┬───────────────────┘
               │  fd-pair pipe (JSON lines)
         ┌─────┼─────┐
         ▼     ▼     ▼
      Worker Worker Worker
      idalib idalib idalib
      (plugin handlers)
```

## Tools

Ramune-ida provides **26 tools** (19 plugin tools + 7 session tools) covering the core reverse engineering workflow:

- **Session** (7) — project lifecycle, database open/close, async task management
- **Analysis** (4) — decompile, disassemble, cross-references, binary overview
- **Annotation** (3) — rename symbols, read/write comments
- **Data** (2) — auto-detect address type, read raw bytes
- **Listing** (4) — enumerate functions, strings, imports, names (with filtering/pagination)
- **Search** (2) — regex search across strings/names/disasm, byte pattern search
- **Types** (2) — set types on functions/variables, declare C types (struct/enum/typedef)
- **Execution** (1) — run arbitrary IDAPython with stdout/stderr capture
- **Undo** (1) — IDA 9.0+ native undo

Low-frequency or exploratory operations are covered by `execute_python`, which provides full IDAPython access within the IDA environment.

## Features

- **Metadata-driven plugin system** — tools auto-discovered at startup, dynamic MCP registration, external plugin folder support
- **Framework tags** — `kind:read` / `kind:write` / `kind:unsafe` — write tools auto-create undo points
- **Graceful cancellation** — SIGUSR1 + `sys.setprofile` hook → 5s watchdog → SIGKILL fallback
- **Crash recovery** — auto-recover from IDA component files, fallback to `.i64`, periodic `.i64` packing
- **Output truncation** — oversized output truncated with HTTP download for full content
- **File upload/download** — HTTP endpoints for binary and IDB transfer

## Plugins

Ramune-ida supports external plugins via `~/.ramune-ida/plugins/` (or `RAMUNE_PLUGIN_DIR`). Drop a plugin folder with `metadata.py` + `handlers.py` and restart — tools appear automatically.

See [Writing Plugins](docs/writing-plugins.md) for the full guide, including metadata reference, framework tags, handler contract, security model, and a complete example.

## Quick Start

### Requirements

- Python >= 3.10
- IDA Pro 9.0+ with idalib
- PDM (package manager)

### Install

```bash
git clone https://github.com/user/Ramune-ida.git
cd Ramune-ida
pdm install
```

### Run

```bash
# Default: Streamable HTTP on 127.0.0.1:8000
ramune-ida

# Specify host and port
ramune-ida http://0.0.0.0:8745

# Use IDA's bundled Python for workers
ramune-ida --worker-python /opt/ida/python3

# SSE transport (legacy MCP clients)
ramune-ida sse://127.0.0.1:9000
```

### MCP Client Configuration

For Claude Desktop or Cursor, add to your MCP config:

```json
{
  "mcpServers": {
    "ramune-ida": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### Basic Workflow

```
1. open_project()                          → get project_id
2. open_database(project_id, "target.exe") → IDA analyzes the binary
3. decompile(project_id, "main")           → decompiled C code
4. rename(project_id, addr="main", new_name="entry_main")
5. set_type(project_id, addr="0x401000", type="int foo(char *buf, int len)")
6. execute_python(project_id, code)        → run any IDAPython script
7. close_database(project_id)              → save and close
8. close_project(project_id)               → clean up
```

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `url` | `http://127.0.0.1:8000` | Transport URL |
| `--worker-python` | `python` | Python interpreter for IDA workers |
| `--soft-limit` | `4` | Advisory threshold for concurrent workers |
| `--hard-limit` | `8` | Maximum concurrent workers (0 = unlimited) |
| `--work-dir` | `~/.ramune-ida/projects` | Base directory for project files |
| `--auto-save-interval` | `300` | Seconds between auto-saves (0 = disabled) |
| `--output-max-length` | `50000` | Truncate tool output beyond this many chars |

## License

MIT
