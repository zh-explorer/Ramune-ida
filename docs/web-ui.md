# Web UI

Ramune-ida includes an optional web-based observation interface for monitoring and browsing IDA database state while AI agents work.

> **Disclaimer**: The Web UI frontend code was primarily written by Claude (AI) and has not undergone thorough code review. It is provided as-is for observation and debugging purposes. Use at your own discretion.

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

The UI uses a fully draggable dock layout (similar to IDA / VS Code). All panels can be:

- Dragged to any position
- Merged into tab groups
- Floated as independent windows
- Maximized
- Closed and re-opened via View menu

### Available Panels

| Panel | Description |
|-------|-------------|
| **Decompile** | C pseudocode view with tree-sitter syntax highlighting. Click to sync, double-click identifiers to navigate. |
| **IDA View** | Linear disassembly view with function headers, xref comments, data/string display. Infinite scroll with on-demand loading. |
| **Disassembly** | Function-scoped disassembly with address-level sync to Decompile. |
| **Hex View** | Classic hex dump with ASCII column. Follows the active address. |
| **Functions** | Function list with virtual scrolling and filter. Click to navigate. |
| **Strings** | String list with filter. Click to navigate. |
| **Names** | Named addresses with filter. |
| **Imports** | Import table with filter. |
| **Exports** | Export table. |
| **Segments** | Segment table (name, range, size, permissions). Click to jump. |
| **Local Types** | Structs, enums, typedefs from the IDB type library. |
| **Xrefs** | Cross-references for the current address. Click to jump. |
| **Activity** | Real-time AI activity stream. Shows tool calls, parameters, and timing. |
| **Project** | Project info, file list with download, open/close database. |

### Navigation

- **Double-click** function names or IDA-generated names (`sub_`, `loc_`, `unk_`, etc.) to navigate
- **Click** any token to highlight all occurrences across views
- **Ctrl+Click** for quick navigation (legacy, double-click preferred)
- **◀ ▶ buttons** in Decompile header for back/forward history
- **LABEL_N** goto labels jump within the current function
- All navigable tokens have a dotted underline

### Panel Sync (Channels)

Panels can be linked for synchronized scrolling and highlighting:

- Each syncable panel has a **link icon** (🔗 / ⛓️) in its header
- Click the icon to link/unlink with other panels
- Linked panels share navigation, highlighting, and scroll position
- By default, Decompile + IDA View + Disassembly + Hex are linked
- New panels created via "+" start independent

### Themes

Five built-in color themes available via Settings → Theme:

- Catppuccin Mocha (default)
- One Dark
- Dracula
- Nord
- Tokyo Night

### AI Activity Monitoring

The Activity panel shows real-time AI tool calls via WebSocket:

- Tool name, parameters, duration
- Color-coded by operation type (read/write/unsafe)
- Click an activity entry to jump to the address the AI was examining

## Building the Frontend

The Web UI frontend must be built before use. Pre-built assets are not included in the repository.

### Prerequisites

- Node.js >= 20 (recommended: use [fnm](https://github.com/Schniz/fnm) or [nvm](https://github.com/nvm-sh/nvm))
- npm

### Build Steps

```bash
# Install dependencies
cd web-ui
npm install

# Build (outputs to src/ramune_ida/web/frontend/)
npx vite build

# Copy WASM files (tree-sitter, required for syntax highlighting)
cp public/*.wasm ../src/ramune_ida/web/frontend/
```

After building, start the server with `--web`:

```bash
uv run ramune-ida --web
```

### Development Mode

For frontend development with hot reload:

```bash
# Terminal 1: Start the backend
uv run ramune-ida --web

# Terminal 2: Start Vite dev server (auto-proxies API to backend)
cd web-ui
npx vite
```

Then open `http://localhost:5173` (Vite dev server) instead of port 8000. Changes to frontend code will hot-reload instantly.

The `RAMUNE_WEB_DEV` environment variable can be set to load frontend assets from `web-ui/dist/` instead of the bundled location.

## Architecture

The Web UI is an optional module (`ramune_ida/web/`) that wraps the existing MCP ASGI app:

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
- **Activity Stream**: ASGI middleware intercepts MCP tool calls, broadcasts via WebSocket
- **Internal Tools**: `core/webview/` package contains UI-only tools tagged `mcp:false` (not visible to AI agents)
- **Frontend**: React + TypeScript + Vite, rc-dock for layout, tree-sitter for C parsing, zustand for state

## Frontend Code Quality Notice

The frontend code (`web-ui/`) was generated by Claude (Anthropic's AI assistant) during an interactive development session. While functional, it has the following caveats:

- **Not professionally reviewed**: The code has not been through a formal code review process
- **Rapid iteration**: Many features were built and refactored quickly, some patterns may be inconsistent
- **Known issues**: Some edge cases in scrolling, panel sync, and error handling may exist
- **Dependencies**: Uses rc-dock v3, web-tree-sitter, zustand, @tanstack/react-virtual

Contributions and improvements are welcome.
