# Web UI

Ramune-ida 包含一个可选的 Web 界面，用于在 AI Agent 工作时实时观测和浏览 IDA 数据库状态。

> **声明**：Web UI 的前端代码主要由 Claude（AI）编写，未经过充分的代码审查。仅作为观测和调试用途提供。

## 快速开始

```bash
# 启用 Web UI
uv run ramune-ida --web

# 打开浏览器
# http://127.0.0.1:8000
```

Web UI 与 MCP Server 共用同一端口。未指定 `--web` 时，不加载任何 Web 相关代码。

## 功能

### 面板系统

采用可拖拽的 Dock 面板布局（类似 IDA / VS Code）。所有面板可拖拽、合并标签组、浮动、最大化、关闭后通过 View 菜单重新打开。布局持久化到 localStorage。

### 可用面板

| 面板 | 说明 |
|------|------|
| **Decompile** | C 伪代码视图，tree-sitter 语法高亮。点击高亮，双击导航。函数注释显示在顶部。支持前进/后退历史。 |
| **IDA View** | 线性反汇编，含函数头、交叉引用注释、数据/字符串显示。虚拟滚动 + 双向按需加载。 |
| **Disassembly** | 函数级反汇编，与 Decompile 地址级同步。 |
| **Hex View** | 虚拟滚动 Hex 视图，字节级选择，多格式复制（hex、C 数组、Python bytes、ASCII），Gap 感知导航。 |
| **Functions** | 函数列表，虚拟滚动 + 过滤。点击导航。 |
| **Strings** | 字符串列表 + 过滤。点击导航。 |
| **Names** | 命名地址列表 + 过滤。 |
| **Imports** | 导入表 + 过滤。 |
| **Exports** | 导出表。 |
| **Segments** | 段表（名称、范围、大小、权限）。点击跳转。 |
| **Local Types** | 本地类型库浏览器。点击展开内联 C 定义（含字节偏移注释），嵌套类型可点击跳转。 |
| **Xrefs** | 交叉引用面板。手动查询模式——结果不随导航刷新。点击结果跳转。 |
| **Search** | 搜索面板。支持正则搜索（strings/names/types/disasm）和字节模式搜索。 |
| **Activity** | AI 实时活动流。点击展开工具详情（代码、参数、返回值）。点击 ↗ 跳转到对应地址。 |
| **Project** | 项目信息、文件列表（下载）、打开/关闭数据库。打开后自动导航到 main/start。 |

### 地址空间概览条

工具栏下方的概览条，按数据类型着色显示整个二进制（代码=蓝、数据=黄、未知=灰）：

- **点击** 跳转到该地址
- **拖拽** 滑动浏览地址（IDA View 跟随）
- **Ctrl+滚轮** 缩放，**滚轮** 平移
- **双击** 重置缩放
- 段间 Gap 显示为细黑色分隔线
- 白色竖线指示当前位置
- 服务端缓存，写操作后自动刷新

### 右键上下文菜单

所有面板右键可用：

- 复制地址 / 复制符号
- Xrefs to...（无 Xrefs 面板时自动打开）
- Go to definition

覆盖所有代码视图和列表面板。

### 键盘快捷键

| 按键 | 功能 |
|------|------|
| **X** | 查询最近点击地址/符号的交叉引用 |
| **G** 或 **/** | 打开/聚焦搜索面板 |
| **Esc** | 后退（导航历史） |
| **鼠标侧键←** | 后退 |
| **鼠标侧键→** | 前进 |

输入框内自动忽略快捷键。

### Hex View 复制格式

字节选择后右键：

- **Copy hex**: `48 8B 05 00`
- **Copy as hex string**: `488b0500`
- **Copy as C array**: `{ 0x48, 0x8B, 0x05, 0x00 }`
- **Copy as Python bytes**: `b'\x48\x8b\x05\x00'`
- **Copy as ASCII**: `H...`

### 导航

- **双击** 函数名或 IDA 生成的名称（`sub_`、`loc_`、`unk_` 等）导航
- **点击** 任意 token 在所有视图中高亮匹配项
- Decompile 头部 **◀ ▶** 按钮 前进/后退
- **LABEL_N** 标签在当前函数内跳转

### 面板同步（Channel）

面板可链接实现同步滚动和高亮：

- 每个可同步面板头部有链接图标
- 点击链接/取消链接
- 链接后共享导航、高亮和滚动位置
- 默认 Decompile + IDA View + Disassembly + Hex 链接

### 主题

Settings → Theme 可选 5 种配色：

- Catppuccin Mocha（默认）
- One Dark
- Dracula
- Nord
- Tokyo Night

### AI 活动监控

Activity 面板通过 WebSocket 实时显示 AI 工具调用：

- 点击展开工具详情：
  - **rename**: 旧名 → 新名
  - **set_comment**: 目标 + 注释内容
  - **execute_python**: 完整代码 + `_result` 返回值
  - **decompile/xrefs/search**: 参数详情
  - 其他工具: JSON fallback
- 按操作类型着色（蓝=read、橙=write、红=unsafe）
- 状态图标：✓ 完成、✗ 失败、⏳ 进行中
- 点击 ↗ 跳转到对应地址

## 构建前端

仓库中包含预构建产物。仅修改前端代码时需要重新构建。

### 前置条件

- Node.js >= 18
- npm

### 构建步骤

```bash
cd web-ui
npm install
npx vite build
```

输出到 `src/ramune_ida/web/frontend/`。

### 通过 uv 构建

```bash
RAMUNE_BUILD_WEB=1 uv build
```

Hatch build hook 会检查 Node.js 版本并执行 `npm ci && vite build`。不设 `RAMUNE_BUILD_WEB` 时使用现有产物。

### 开发模式

前端热重载开发：

```bash
# 终端 1：启动后端
uv run ramune-ida --web

# 终端 2：启动 Vite 开发服务器（自动代理 API 到后端）
cd web-ui
npx vite
```

打开 `http://localhost:5173`。设置 `RAMUNE_WEB_DEV` 环境变量从 `web-ui/dist/` 加载资源。

## 架构

```
浏览器 (React SPA)
    │  HTTP REST + WebSocket
    ▼
MCP Server 进程
├── /api/*     → Web API（直接调用 Project 层）
├── /ws/*      → WebSocket（活动流）
├── /mcp       → MCP 协议（供 AI Agent）
└── /*         → SPA 静态资源
```

- **后端**：REST 端点直接调用 `Project.execute()`，跳过 MCP 协议开销
- **活动流**：ASGI 中间件拦截 MCP 工具调用，通过 WebSocket 广播完整参数和结果摘要
- **内部工具**：`core/webview/` 包含仅 UI 使用的工具（`mcp:false`）：func_view、linear_view、hex_view、overview_scan、resolve
- **概览缓存**：服务端缓存 + 基于 Activity 的失效机制 + 60 秒 rescan 冷却
- **优雅退出**：顶层 SIGINT 拦截，退出前保存数据库
- **前端**：React + TypeScript + Vite，rc-dock 布局，tree-sitter C 解析，zustand 状态管理
