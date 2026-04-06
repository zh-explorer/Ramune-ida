# Web UI

Ramune-ida includes an optional web-based observation interface for monitoring and browsing IDA database state while AI agents work.

> **Disclaimer**: The Web UI frontend code was primarily written by Claude (AI) and has not undergone thorough code review. It is provided as-is for observation and debugging purposes.

## Quick Start

```bash
# Start with Web UI enabled
uv run ramune-ida --web

# Open browser
# http://127.0.0.1:8000
```

The Web UI is served on the same port as the MCP server. When `--web` is not specified, no web-related code is loaded.

## Features

### Panel System

The UI uses a fully draggable dock layout (similar to IDA / VS Code). All panels can be dragged to any position, merged into tab groups, floated as independent windows, maximized, closed and re-opened via View menu. Layout is persisted to localStorage.

### Available Panels

| Panel | Description |
|-------|-------------|
| **Decompile** | C pseudocode view with tree-sitter syntax highlighting. Click to highlight, double-click to navigate. Function comments shown at top. Back/forward history. |
| **IDA View** | Linear disassembly with function headers, xref comments, data/string display. Virtual scrolling with bidirectional on-demand loading. |
| **Disassembly** | Function-scoped disassembly with address-level sync to Decompile view. |
| **Hex View** | Virtual-scrolling hex dump with byte-level selection, multi-format copy (hex, C array, Python bytes, ASCII), and gap-aware navigation. |
| **Functions** | Function list with virtual scrolling and filter. Click to navigate. |
| **Strings** | String list with filter. Click to navigate. |
| **Names** | Named addresses with filter. |
| **Imports** | Import table with filter. |
| **Exports** | Export table. |
| **Segments** | Segment table (name, range, size, permissions). Click to jump. |
| **Local Types** | Structs, enums, typedefs from the IDB type library. Click to expand inline C definition with byte offset comments. Nested types are clickable for navigation. |
| **Xrefs** | Cross-references panel. Manual query mode — click results to jump, results persist across navigation. |
| **Search** | Regex search (strings/names/types/disasm) and binary byte pattern search. |
| **Activity** | Real-time AI activity stream. Click to expand per-tool details (code, parameters, results). Click ↗ to jump to the address. |
| **Project** | Project info, file list with download, open/close database. Auto-navigates to main/start on open. |

### Overview Bar

Address space overview bar below the toolbar. Shows the entire binary colored by data type (code=blue, data=yellow, unknown=gray):

- **Click** to jump to that address
- **Drag** to slide through addresses (IDA View follows)
- **Ctrl+Scroll** to zoom, **Scroll** to pan
- **Double-click** to reset zoom
- Segment gaps shown as thin black separators
- Current position indicated by white cursor line
- Cached with activity-based invalidation (auto-refreshes after write operations)

### Context Menu

Right-click on any panel for:

- Copy address / Copy token
- Xrefs to... (auto-opens Xrefs panel if none exists)
- Go to definition

Available on all code views and list panels (Functions, Strings, Names, Imports, Exports, Xrefs, Search).

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **X** | Query Xrefs for last clicked address/symbol |
| **G** or **/** | Open/focus Search panel |
| **Esc** | Go back (navigation history) |
| **Mouse Back** | Go back |
| **Mouse Forward** | Go forward |

Shortcuts are ignored when typing in input fields.

### Hex View Copy Formats

Select bytes by click-drag, then right-click:

- **Copy hex**: `48 8B 05 00`
- **Copy as hex string**: `488b0500`
- **Copy as C array**: `{ 0x48, 0x8B, 0x05, 0x00 }`
- **Copy as Python bytes**: `b'\x48\x8b\x05\x00'`
- **Copy as ASCII**: `H...`

### Navigation

- **Double-click** function names or IDA-generated names (`sub_`, `loc_`, `unk_`, etc.) to navigate
- **Click** any token to highlight all occurrences across views
- **◀ ▶ buttons** in Decompile header for back/forward history
- **LABEL_N** goto labels jump within the current function

### Panel Sync (Channels)

Panels can be linked for synchronized scrolling and highlighting:

- Each syncable panel has a **link icon** in its header
- Click to link/unlink with other panels
- Linked panels share navigation, highlighting, and scroll position
- By default, Decompile + IDA View + Disassembly + Hex are linked

### Themes

Five built-in color themes available via Settings → Theme:

- Catppuccin Mocha (default)
- One Dark
- Dracula
- Nord
- Tokyo Night

### AI Activity Monitoring

The Activity panel shows real-time AI tool calls via WebSocket:

- Click to expand per-tool detail view:
  - **rename**: old name → new name
  - **set_comment**: target + comment text
  - **execute_python**: full code with syntax formatting + `_result` return value
  - **decompile/xrefs/search**: parameter details
  - Other tools: JSON fallback
- Color-coded by operation type (blue=read, orange=write, red=unsafe)
- Status icons: ✓ completed, ✗ failed, ⏳ pending
- Click ↗ button to jump to the address

## Building the Frontend

Pre-built assets are included in the repository. Rebuild only if you modify frontend code.

### Prerequisites

- Node.js >= 18
- npm

### Build Steps

```bash
cd web-ui
npm install
npx vite build
```

Output goes to `src/ramune_ida/web/frontend/`.

### Build via uv

```bash
RAMUNE_BUILD_WEB=1 uv build
```

The hatch build hook checks Node.js version, runs `npm ci && vite build`. Without `RAMUNE_BUILD_WEB`, existing assets are used.

### Development Mode

For frontend development with hot reload:

```bash
# Terminal 1: Start the backend
uv run ramune-ida --web

# Terminal 2: Start Vite dev server (auto-proxies API to backend)
cd web-ui
npx vite
```

Open `http://localhost:5173` instead of port 8000. The `RAMUNE_WEB_DEV` environment variable loads assets from `web-ui/dist/`.

## Architecture

```
Browser (React SPA)
    │  HTTP REST + WebSocket
    ▼
MCP Server Process
├── /api/*     → Web API (direct Project layer access)
├── /ws/*      → WebSocket (activity stream)
├── /mcp       → MCP protocol (for AI agents)
└── /*         → SPA static files
```

- **Backend**: REST endpoints call `Project.execute()` directly, bypassing MCP protocol overhead
- **Activity Stream**: ASGI middleware intercepts MCP tool calls, broadcasts via WebSocket with full params and result summaries
- **Internal Tools**: `core/webview/` package contains UI-only tools tagged `mcp:false` (func_view, linear_view, hex_view, overview_scan, resolve)
- **Overview Cache**: Server-side cache with activity-based invalidation and 60-second rescan cooldown
- **Graceful Shutdown**: Top-level SIGINT handling saves databases before exit
- **Frontend**: React + TypeScript + Vite, rc-dock for layout, tree-sitter for C parsing, zustand for state
