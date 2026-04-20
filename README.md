# Ramune-ida

> **[WIP] This project is under active development. APIs and features may change without notice.**
>
> **The main branch contains unstable updates. For stable versions, please use commits marked with release tags.**

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

Ramune-ida provides **28 tools** (21 plugin tools + 7 session tools) covering the core reverse engineering workflow:

- **Session** (7) — project lifecycle, database open/close, async task management
- **Analysis** (4) — decompile, disassemble, cross-references, binary overview
- **Annotation** (3) — rename symbols, read/write comments
- **Data** (2) — auto-detect address type, read raw bytes
- **Listing** (5) — enumerate functions, strings, imports, names, types (with filtering)
- **Search** (2) — regex search across strings/names/disasm, byte pattern search
- **Types** (3) — get/set types on functions/variables, declare C types (struct/enum/typedef)
- **Execution** (1) — run arbitrary IDAPython with stdout/stderr capture
- **Undo** (1) — IDA 9.0+ native undo

Low-frequency or exploratory operations are covered by `execute_python`, which provides full IDAPython access within the IDA environment.

## Features

- **Metadata-driven plugin system** — tools auto-discovered at startup, dynamic MCP registration, external plugin folder support
- **Framework tags** — `kind:read` / `kind:write` / `kind:unsafe` — write tools auto-create undo points
- **Tag filtering** — `--exclude-tags` to hide tools from MCP by tag, path glob, or name
- **Graceful cancellation** — SIGUSR1 + `sys.setprofile` hook → 5s watchdog → SIGKILL fallback
- **Crash recovery** — auto-recover from IDA component files, fallback to `.i64`, periodic `.i64` packing
- **Output truncation** — oversized output truncated with HTTP download for full content
- **File upload/download** — HTTP endpoints for binary and IDB transfer

## Plugins

Ramune-ida supports external plugins via `<data-dir>/plugins/` (default `~/.ramune-ida/plugins/`). Drop a plugin folder with `metadata.py` + `handlers.py` and restart — tools appear automatically.

See [Writing Plugins](docs/writing-plugins.md) for the full guide, including metadata reference, framework tags, handler contract, security model, and a complete example.

## Quick Start

### Requirements

- Python >= 3.10
- IDA Pro 9.0+ with idalib
- [uv](https://docs.astral.sh/uv/) (package manager)

### Install

```bash
git clone https://github.com/RamuneIDA/Ramune-ida.git
cd Ramune-ida
uv sync
```

### Run

```bash
# Default: Streamable HTTP on 127.0.0.1:8000
uv run ramune-ida

# Specify host and port
uv run ramune-ida http://0.0.0.0:8745

# Use IDA's bundled Python for workers
uv run ramune-ida --worker-python /opt/ida/python3

# SSE transport (legacy MCP clients)
uv run ramune-ida sse://127.0.0.1:9000
```

### MCP Client Configuration

For Claude Desktop or Cursor, add to your MCP config:

```json
{
  "mcpServers": {
    "ramune-ida": {
      "type": "http",
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

## Web UI (Experimental)

<img src="docs/web-ui-demo.gif" width="800" />

Ramune-ida includes an optional web interface for observing AI agent activity and browsing IDA database state in real time. Enable it with `--web`:

```bash
uv run ramune-ida --web
```

**Features:**
- IDA-style linear disassembly (IDA View) with virtual scrolling and bidirectional loading
- Decompilation with tree-sitter C syntax highlighting and line-level sync
- Hex View with byte-level selection, multi-format copy, and virtual scrolling
- Address space overview bar with per-pixel type mapping, zoom, and click-to-navigate
- Right-click context menu on all panels (Copy address, Xrefs, Go to definition)
- Keyboard shortcuts (X=Xrefs, G=Search, Esc=Back, mouse side buttons)
- Cross-reference panel with manual query mode
- Local Types browser with inline C definition expansion and nested type navigation
- Search panel (regex + byte pattern)
- Real-time AI activity stream with per-tool detail expansion
- Dockable panel layout (drag, float, merge tabs) with persistent state
- Auto-navigate to main/start on database open

See [Web UI Documentation](docs/web-ui.md) for details.

> **Note**: The Web UI frontend was primarily written by AI (Claude) and has not undergone thorough code review.

## Directory Layout

All data is stored under a single data directory (default `~/.ramune-ida`, configurable via `--data-dir` or `RAMUNE_DATA_DIR`):

| Path | Description |
|---|---|
| `<data-dir>/projects/` | Project work directories (IDB files, outputs) |
| `<data-dir>/plugins/` | External plugin folder |

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `url` | `http://127.0.0.1:8000` | Transport URL |
| `--worker-python` | `python` | Python interpreter for IDA workers |
| `--soft-limit` | `4` | Advisory threshold for concurrent workers |
| `--hard-limit` | `8` | Maximum concurrent workers (0 = unlimited) |
| `--data-dir` | `~/.ramune-ida` | Data directory for projects and plugins (`RAMUNE_DATA_DIR`) |
| `--auto-save-interval` | `300` | Seconds between auto-saves (0 = disabled) |
| `--output-max-length` | `20000` | Truncate tool output beyond this many chars |
| `--exclude-tags` | — | Comma-separated tags to exclude from MCP (supports `::*` globs) |
| `--web` | off | Enable Web UI on the same port |

## Building

### From source

```bash
git clone https://github.com/RamuneIDA/Ramune-ida.git
cd Ramune-ida
uv sync
uv run ramune-ida
```

### With frontend rebuild

Requires Node.js >= 18:

```bash
RAMUNE_BUILD_WEB=1 uv build
```

Without `RAMUNE_BUILD_WEB`, `uv build` uses the pre-built frontend assets in the repository.

### Docker

Requires a pre-built `ida-pro:latest` base image with IDA Pro installed

The Dockerfile uses multi-stage build — Node.js builds the frontend, the final image only contains Python + IDA. Web UI is enabled by default.

```bash
docker build -t ramune-ida .
docker run -p 8000:8000 ramune-ida
```

| Environment Variable | Default | Description |
|---|---|---|
| `TRANSPORT` | `http://0.0.0.0:8000` | Transport URL |
| `SOFT_LIMIT` | `4` | Advisory threshold for concurrent workers |
| `HARD_LIMIT` | `8` | Maximum concurrent workers |
| `RAMUNE_DATA_DIR` | `/data/ramune-ida` | Data directory (projects + plugins) |

## License

MIT
