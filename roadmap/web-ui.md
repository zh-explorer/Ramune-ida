# Ramune-ida Web UI 实现计划

> 为 headless IDA MCP Server 添加基于 Web 的观测界面，让用户在 AI agent 工作时能实时观察 IDA 数据库状态。

---

## 1. 整体架构

Web UI 作为现有 MCP Server 进程的**附加模块**运行，不引入新进程。

```
浏览器 (React SPA)
    │
    │  HTTP REST + WebSocket
    ▼
┌──────────────────────────────────────────────────────────┐
│              MCP Server 进程 (现有 Starlette app)         │
│                                                           │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ FastMCP  │  │  Web API     │  │  Activity Stream   │  │
│  │ /mcp     │  │  /api/       │  │  Middleware 拦截    │  │
│  └────┬─────┘  └──────┬───────┘  └────────┬───────────┘  │
│       │               │                   │               │
│       └───────────────┴───────────────────┘               │
│                       │                                    │
│              Project / AppState / Limiter                  │
│                       │                                    │
└───────────────────────┼───────────────────────────────────┘
                        │ UNIX socketpair
                   Worker 子进程群
```

### 关键决策

- **Web API 直接调用 Project 层**，不走 MCP 协议（避免多余序列化/反序列化开销）
- **AI 活动流通过 Starlette Middleware 在 HTTP 层拦截**，不改动 tool dispatch 内部
- **`--web` CLI 开关控制**，不开启时零导入、零侵入
- **前端构建产物内置于 Python 包中**，无需安装 Node.js 即可使用

---

## 2. 目录结构

```
src/ramune_ida/
├── web/                          # Web UI 全部后端代码
│   ├── __init__.py
│   ├── app.py                    # create_combined_app() — 组合 ASGI 应用
│   ├── api/                      # REST API 端点
│   │   ├── __init__.py
│   │   ├── projects.py           # 项目管理
│   │   ├── analysis.py           # 反编译/反汇编/xrefs
│   │   ├── listing.py            # 函数/字符串/导入列表
│   │   ├── files.py              # 文件下载
│   │   └── search.py             # 搜索
│   ├── activity.py               # ActivityStore + Middleware + WebSocket
│   └── frontend/                 # 前端构建产物（git-tracked）
│       ├── index.html
│       └── assets/
│
web-ui/                           # 前端源码（独立 npm 项目）
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/                      # API client 层
    │   ├── client.ts
    │   └── types.ts
    ├── stores/                   # Zustand 状态管理
    │   ├── projectStore.ts
    │   ├── activityStore.ts
    │   └── viewStore.ts
    ├── layouts/
    │   └── DockLayout.tsx        # 可拖拽面板布局
    ├── panels/                   # 各面板组件
    │   ├── FunctionList.tsx
    │   ├── Decompile.tsx
    │   ├── Disassembly.tsx
    │   ├── StringList.tsx
    │   ├── Imports.tsx
    │   ├── HexView.tsx
    │   ├── Xrefs.tsx
    │   ├── ActivityStream.tsx
    │   └── ProjectExplorer.tsx
    ├── components/               # 共享 UI 组件
    │   ├── AddressLink.tsx
    │   ├── SearchBar.tsx
    │   ├── StatusBar.tsx
    │   └── Toolbar.tsx
    └── theme/
        └── ida-dark.css          # IDA 风格深色主题
```

---

## 3. 后端 API 设计

### 3.1 设计原则

- 所有端点以 `/api/` 为前缀
- 需要 IDA 数据的端点都带 `project_id` 路径参数
- 返回 JSON
- 读操作用 GET，写操作用 POST
- 认证由全局层统一处理（不在 Web UI 模块内实现），Web API 和 MCP 端点共享同一套认证机制

### 3.2 端点清单

#### 项目管理（直接读 AppState，不经 Worker）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 列出所有项目 |
| GET | `/api/projects/{pid}` | 项目详情（状态、路径、worker 状态） |
| GET | `/api/projects/{pid}/files` | 项目文件列表 |
| GET | `/api/projects/{pid}/files/{path:path}` | 下载文件 |
| GET | `/api/system` | 系统状态（实例计数、限制、配置） |

#### 分析视图（经 Worker 执行）

| 方法 | 路径 | 对应 tool |
|------|------|-----------|
| GET | `/api/projects/{pid}/decompile?func={addr}` | `decompile` |
| GET | `/api/projects/{pid}/disasm?addr={addr}&count={n}` | `disasm` |
| GET | `/api/projects/{pid}/xrefs?addr={addr}` | `xrefs` |
| GET | `/api/projects/{pid}/examine?addr={addr}` | `examine` |
| GET | `/api/projects/{pid}/bytes?addr={addr}&size={n}` | `get_bytes` |
| GET | `/api/projects/{pid}/survey` | `survey` |

#### 列表视图

| 方法 | 路径 | 对应 tool |
|------|------|-----------|
| GET | `/api/projects/{pid}/functions?filter=&exclude=` | `list_funcs` |
| GET | `/api/projects/{pid}/strings?filter=&exclude=` | `list_strings` |
| GET | `/api/projects/{pid}/imports?filter=&exclude=` | `list_imports` |
| GET | `/api/projects/{pid}/names?filter=&exclude=` | `list_names` |

列表端点返回完整数据（不经 OutputStore 截断），由前端虚拟滚动处理渲染。

#### 搜索

| 方法 | 路径 | 对应 tool |
|------|------|-----------|
| GET | `/api/projects/{pid}/search?pattern=&type=&count=` | `search` |
| GET | `/api/projects/{pid}/search/bytes?pattern=&count=` | `search_bytes` |

#### 活动流

| 方法 | 路径 | 说明 |
|------|------|------|
| WebSocket | `/ws/activity` | 实时活动流推送 |
| GET | `/api/activity?project_id=&limit=` | 历史活动记录 |

### 3.3 统一执行模式

所有需要 Worker 的端点共享一个通用执行入口：

```python
async def _execute_tool(project_id: str, tool_name: str, params: dict) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    invocation = PluginInvocation(tool_name, params)
    task = await project.execute(invocation, timeout=30.0)
    if task.error:
        raise HTTPException(status_code=500, detail=task.error.message)
    return task.result or {}
```

每个端点只需解析 query params、调用 `_execute_tool`、返回 JSONResponse。

---

## 4. 前端设计

### 4.1 整体布局

可拖拽的 Dock 面板布局，参考 IDA Pro 的多窗口排列：

```
┌─────────────────────────────────────────────────────────────┐
│ [Toolbar]  项目选择器 | 搜索栏 | 状态指示灯                   │
├────────────────┬──────────────────────┬──────────────────────┤
│                │                      │                      │
│  函数列表       │   反编译视图          │  反汇编视图           │
│  FunctionList  │   Decompile          │  Disassembly         │
│                │                      │                      │
│  虚拟滚动       │   CodeMirror 6       │  CodeMirror 6        │
│  过滤搜索       │   C 伪代码高亮        │  x86/ARM 语法高亮    │
│                │                      │                      │
├────────────────┼──────────────────────┴──────────────────────┤
│                │                                             │
│  字符串列表     │   AI 活动流 (ActivityStream)                 │
│  StringList    │                                             │
│                │   实时消息滚动                                │
│  虚拟滚动       │   每条消息可点击跳转                          │
│  过滤搜索       │                                             │
│                │                                             │
├────────────────┴─────────────────────────────────────────────┤
│ [StatusBar]  当前项目 | Worker 状态 | 实例计数 x/y            │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 核心面板

**FunctionList** — 虚拟滚动列表（万级条目），列：地址 | 函数名 | 大小。顶部过滤框即时过滤。点击跳转到反编译/反汇编视图。未命名函数 (`sub_*`) 灰色显示。

**Decompile** — CodeMirror 6，只读，C 语法高亮。函数名/地址可点击跳转。加载时显示 spinner。

**Disassembly** — CodeMirror 6，自定义汇编语法高亮。地址可点击跳转。

**StringList** — 虚拟滚动，列：地址 | 值 | 长度。过滤搜索。点击跳转到引用位置。

**ActivityStream** — 实时消息列表，新消息从底部追加。格式：`[时间] [项目] [操作] [参数摘要] [耗时]`。操作颜色标记：蓝色=read，橙色=write，红色=unsafe。地址可点击跳转。支持暂停自动滚动。

**Xrefs / HexView** — 可选打开的辅助面板。

### 4.3 共享组件

- **AddressLink** — 可点击的地址/函数名，点击触发导航，右键菜单（复制、xrefs）
- **SearchBar** — 全局正则搜索，支持范围选择（all/strings/names/disasm）
- **StatusBar** — 当前项目、Worker 状态、实例计数、最后活动时间

### 4.4 技术选型

| 技术 | 选择 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 生态最大，复杂 UI 成熟 |
| 构建 | Vite | 快速 HMR，生产构建小 |
| 状态管理 | Zustand | 极简，不需要 Redux 的复杂度 |
| 代码展示 | CodeMirror 6 | 轻量，C/ASM 高亮插件成熟 |
| 虚拟滚动 | @tanstack/virtual | React 生态标准 |
| 面板布局 | rc-dock | 可拖拽 dock 面板，IDA 风格 |
| HTTP 请求 | 原生 fetch | API 简单，不需要 axios |
| WebSocket | 原生 WebSocket | 协议简单，不需要 Socket.IO |
| CSS | Tailwind CSS | 快速 styling，深色主题方便 |

---

## 5. AI 活动流实现

### 5.1 拦截层：ASGI Middleware

在 HTTP 层拦截 MCP tool call 的请求/响应：

```
MCP Client → HTTP POST /mcp
          → ActivityMiddleware (新增)
              ├── 缓冲 request body → 解析 JSON-RPC → 记录 tool call
              ├── 转发给下层 FastMCP handler
              ├── 拦截 response → 记录完成/错误 + 耗时
              └── 广播 ActivityEvent 到所有 WebSocket 连接
          → FastMCP StreamableHTTP handler
```

只解析 `tools/call` 类型的 JSON-RPC 请求，忽略其他方法。

### 5.2 ActivityEvent 数据结构

```python
class ActivityEvent:
    id: str                    # 唯一 ID
    timestamp: float
    project_id: str | None     # 从 tool call params 中提取
    tool_name: str             # "decompile"
    params_summary: str        # "func=main"
    status: "pending" | "completed" | "failed"
    duration_ms: float | None
    kind: str                  # "read" | "write" | "unsafe"
```

### 5.3 params_summary 生成

从参数中提取最有信息量的字段（func, addr, pattern, new_name 等），排除 project_id，截断过长值，最多 3 个字段。

### 5.4 WebSocket 推送

浏览器连接 `/ws/activity` 后：
1. 先收到最近 50 条历史记录
2. 之后实时接收新事件
3. 支持自动重连

---

## 6. 与现有代码的集成

### 6.1 需要修改的文件（仅 2 个）

**`cli.py`** — 添加 `--web` / `--web-dev` 参数，条件加载 Web 模块：

```python
if args.web:
    from ramune_ida.web.app import create_combined_app
    asgi_app = create_combined_app(mcp_app=asgi_app, get_state=get_state)
```

**`config.py`** — 添加 `web_enabled: bool = False` 字段。

### 6.2 不需要修改的文件

- `server/app.py` — FastMCP 实例和 lifespan 不变
- `server/state.py` — AppState 不变
- `server/plugins.py` — plugin discovery 不变
- `server/files.py`、`server/output.py` — 现有端点不变
- `server/tools/`、`server/resources.py` — MCP 注册不变
- `project.py`、`worker_handle.py` — Project/Worker 层不变
- `worker/` — 整个 Worker 侧不变

### 6.3 ASGI 应用组合

`--web` 启用时，构建外层 Starlette app：

```
外层 Starlette app
├── Mount("/api", web_api_app)           # Web UI REST API
├── Route("/ws/activity", websocket)     # WebSocket 活动流
├── Mount("/", static_files)             # SPA 静态资源
└── Mount("", mcp_asgi_app)              # 原有 MCP 路由 (fallback)
```

---

## 7. 技术注意事项

### 并发安全

Web API 与 MCP tool call 共享 `Project.execute()` 入口。`Project._exec_lock` 保证同一项目请求串行执行。如果 AI 正在长时间操作，Web UI 请求会排队。

对策：为只读操作设短 timeout（10s），超时返回 "Worker busy"，前端显示忙碌状态。

### 跨域

Web UI 和 API 同进程 serve，无跨域问题。开发模式下用 Vite proxy 转发。

### 前端构建与分发

构建产物不进 git，只保留前端源码。两条构建路径：

- **Python 打包**：hatch build hook，`uv build` 时自动执行 `npm run build`，产物打入 wheel。从 wheel 安装不需要 Node.js
- **Docker**：Dockerfile 中 multi-stage build，Node.js 阶段构建前端，最终镜像不带 Node.js

---

## 8. 实施进度

### Phase 1：基础框架 + 项目概览 ✅

- 后端：`web/` 目录结构、`create_combined_app()`、项目管理 API、`--web` CLI 参数
- 前端：Vite + React 初始化、IDA 深色主题（Catppuccin 色调 + 等宽字体）、基础布局 shell、ProjectExplorer
- `ensure_state()` 解决 FastMCP 的 per-session lifespan 导致 AppState 未初始化的问题
- 安装 `websockets` 解决 uvicorn WebSocket 支持

### Phase 2：核心分析视图 ✅

- 后端：decompile/disasm/xrefs/examine/bytes/survey/listing/search 端点，统一 `_execute_tool()` 模式
- 前端：FunctionList（@tanstack/virtual 虚拟滚动 + 前端过滤）、Decompile/Disassembly（CodeMirror 6 + 语法高亮）、StringList
- API 响应格式适配（数据在 `items` 字段）
- 完整函数反汇编（count=500）

### Phase 3：AI 活动流 ✅

- 后端：ActivityStore（内存 deque，maxlen=1000）、ActivityMiddleware（HTTP 层拦截 JSON-RPC `tools/call`）、WebSocket 实时推送
- 前端：ActivityStream 面板、操作颜色标记（read/write/unsafe）、自动滚动 + 暂停
- 修复 `send_bytes` → `send_text`（二进制帧前端无法 JSON.parse）
- 修复 `/api/activity` 路由被 Mount 拦截的问题

### Phase 4：交互增强 ✅

- 所有分隔线可拖拽（通用 SplitPane 组件，支持水平/垂直）
- 反编译/反汇编改为左右分栏布局，三级嵌套 SplitPane
- 交叉引用跳转：Ctrl+Click 反编译中的 `sub_xxxx` / `loc_xxxx` / `0xHEX` 跳转到对应函数
- 反汇编中 `call`/`jmp` 目标可 Ctrl+Click 跳转
- Activity 面板点击事件直接跳转到 AI 正在查看的函数
- HexView 面板（经典 hex dump + ASCII，地址输入跳转）
- 选择高亮（`highlightSelectionMatches`，黄色底色 + 下划线）

### Phase 5：跳转系统 ✅

**A. resolve 接口 ✅**
- `core/webview/` 独立包，所有 UI 内部工具（`mcp:false`）集中管理
- `resolve` 工具：传入名称/地址，返回 `{type, addr, func_name?, func_addr?, size?}`
- `func_view`、`linear_view` 从 `core/analysis/` 迁移至 `core/webview/`

**B. 统一跳转逻辑 ✅**
- `navigateTo` 先调 resolve → 根据 type 决定行为
- `function` / `code` → func_view 加载 + IDA View 跳转
- `data` / `string` / `unknown` → 只设 targetAddr，IDA View 跳转
- 同函数内跳转跳过 func_view（性能优化）
- tree-sitter C 解析器替代正则判断可导航性
- LABEL 跳转：函数内 goto 标签前端本地跳转

**C. Hex View 跟随 ✅**
- 纳入 channel 同步体系（ChannelBadge + tabChannel）
- targetAddr / highlightDisasmAddrs 变化时自动加载对应区域
- 高亮当前地址对应的字节

**D. 导航历史 UI ✅**
- Decompile 面板头部 ◀ ▶ 按钮
- goBack / goForward 方法，基于 channel 的 history + historyIndex

**IDA View 重构 ✅**
- 后端：`linear_view` 支持 `direction=forward|backward`，`prev_head` 线性反向遍历
- 前端：稀疏数据模型，jumpTo 清空重建，上下边界按需加载
- 段间 gap 自动跳过，未知字节折叠（≥64 阈值，醒目 badge）
- 可见则不滚动优化

**反编译 ↔ 反汇编行级同步 ✅**
- func_view 返回 eamap 行映射（ctree color tag 解析 + cinsn group 聚合）
- 点击反编译行 → 反汇编/IDA View 高亮对应指令，反之亦然
- 自动滚动到高亮位置居中

**Dock 面板布局 ✅**
- rc-dock v3 全面板自由拖拽、浮动、合并 tab、最大化
- Channel 同步：面板间 1:1 链接，ChannelBadge UI
- TabTitle 响应式命名，多实例自动编号
- 布局持久化到 localStorage
- Tab 换行溢出（替代滚动）

### Phase 6：信息面板 ✅

**E. Xrefs 面板 ✅**
- 手动查询模式：地址输入框 + 回车触发查询，点击结果不会刷新列表
- 点击 xref 条目跳转到引用位置
- 首次加载时自动查询当前地址，后续仅用户主动触发
- 待优化：需要快捷键（X）从其他面板触发 xrefs 查询（见 Phase 7.H）

**新增面板 ✅**
- Imports — 虚拟滚动 + 过滤，点击跳转
- Exports — 从 survey 数据
- Names — 虚拟滚动 + 过滤
- Segments — 表格（名称/起止/大小/权限），点击跳到段起始
- Local Types — 基于 `list_types` + `get_type` MCP 工具，按 kind 着色，点击就地展开完整 C 定义（带偏移注释 + 语法高亮），嵌套类型点击自动跳转展开

**F. 搜索面板**
- 待做：后端已有 `/api/projects/{pid}/search`

### Phase 7：交互细节

**G. 右键上下文菜单**
- 待做：代码视图右键（复制地址、查看 Xrefs、跳转）

**H. 键盘快捷键**
- 待做：全局快捷键系统
- X = 对当前地址/选中符号查询 Xrefs（在已有 xrefs 面板中刷新，无则新开）
- G = 跳转到地址
- Esc = 返回（导航历史）
- / = 搜索
- N = 重命名

**L. 地址空间 Overview 导航条**
- 待做：Canvas 横条，按类型着色，点击跳转，Ctrl+滚轮缩放

### Phase 8：工程化

**I. 构建与打包**
- 待做：pyproject.toml hatch build hook + Dockerfile multi-stage

**J. 独立测试**
- 待做：`tests/web/`

**K. 认证**
- 待做：全局认证层

---

## 9. 隔离原则

Web UI 模块在不启用时**完全隐形**：

- **代码**：全部在 `ramune_ida/web/` 和 `web-ui/` 下，`--web` 未开启时零导入
- **测试**：独立的测试目录（如 `tests/web/`），不混入主测试套件，默认测试命令不执行 web 测试
- **构建**：前端构建仅在显式触发时执行（hatch hook / Docker stage），不影响正常的 `uv sync`
- **依赖**：前端依赖在 `web-ui/package.json` 中管理，与 Python 依赖无关
