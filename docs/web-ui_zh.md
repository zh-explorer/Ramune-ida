# Web UI

Ramune-ida 包含一个可选的 Web 界面，用于在 AI Agent 工作时实时观测和浏览 IDA 数据库状态。

> **声明**：Web UI 的前端代码主要由 Claude（AI）编写，未经过充分的代码审查。仅作为观测和调试用途提供，请自行评估后使用。

## 快速开始

```bash
# 启用 Web UI
uv run ramune-ida --web

# 打开浏览器
# http://127.0.0.1:8000
```

Web UI 与 MCP 服务共用同一端口。不指定 `--web` 时，不会加载任何 Web 相关代码。

## 功能

### 面板系统

UI 使用完全可拖拽的 Dock 布局（类似 IDA / VS Code）。所有面板支持：

- 拖拽到任意位置
- 合并为 Tab 组
- 浮动为独立窗口
- 最大化
- 关闭后通过 View 菜单重新打开

### 可用面板

| 面板 | 说明 |
|------|------|
| **Decompile** | C 伪代码视图，tree-sitter 语法高亮。点击同步，双击标识符跳转。 |
| **IDA View** | 线性反汇编视图，包含函数头、交叉引用注释、数据/字符串显示。无限滚动按需加载。 |
| **Disassembly** | 函数级反汇编，与 Decompile 地址级同步。 |
| **Hex View** | 经典十六进制 dump + ASCII 列。跟随活动地址。 |
| **Functions** | 函数列表，虚拟滚动 + 过滤。点击导航。 |
| **Strings** | 字符串列表 + 过滤。点击导航。 |
| **Names** | 命名地址列表 + 过滤。 |
| **Imports** | 导入表 + 过滤。 |
| **Exports** | 导出表。 |
| **Segments** | 段表（名称、范围、大小、权限）。点击跳转。 |
| **Local Types** | IDB 类型库中的结构体、枚举、typedef。 |
| **Xrefs** | 当前地址的交叉引用列表。点击跳转。 |
| **Activity** | AI 实时活动流。显示工具调用、参数和耗时。 |
| **Project** | 项目信息、文件列表（含下载）、打开/关闭数据库。 |

### 导航

- **双击**函数名或 IDA 生成的名称（`sub_`、`loc_`、`unk_` 等）进行跳转
- **单击**任意标记可高亮所有同名出现处（跨视图）
- **Ctrl+点击**快速导航（旧版，推荐使用双击）
- Decompile 头部 **◀ ▶ 按钮**用于前进/后退历史
- **LABEL_N** goto 标签在当前函数内跳转
- 所有可导航标记有虚线下划线提示

### 面板同步（Channel）

面板可链接实现同步滚动和高亮：

- 每个可同步面板头部有**链接图标**（🔗 / ⛓️）
- 点击图标链接/取消链接其他面板
- 链接的面板共享导航、高亮和滚动位置
- 默认：Decompile + IDA View + Disassembly + Hex 已链接
- 通过"+"新建的面板默认独立

### 主题

通过 Settings → Theme 切换，内置五种配色：

- Catppuccin Mocha（默认）
- One Dark
- Dracula
- Nord
- Tokyo Night

### AI 活动监控

Activity 面板通过 WebSocket 实时显示 AI 工具调用：

- 工具名、参数摘要、耗时
- 按操作类型着色（read/write/unsafe）
- 点击活动条目跳转到 AI 正在查看的地址

## 构建前端

Web UI 前端需要手动构建，仓库中不包含预编译产物。

### 前置要求

- Node.js >= 20（推荐使用 [fnm](https://github.com/Schniz/fnm) 或 [nvm](https://github.com/nvm-sh/nvm)）
- npm

### 构建步骤

```bash
# 安装依赖
cd web-ui
npm install

# 构建（输出到 src/ramune_ida/web/frontend/）
npx vite build

# 复制 WASM 文件（tree-sitter，语法高亮需要）
cp public/*.wasm ../src/ramune_ida/web/frontend/
```

构建完成后，启动服务并启用 Web UI：

```bash
uv run ramune-ida --web
```

### 开发模式

前端开发时可使用热重载：

```bash
# 终端 1：启动后端
uv run ramune-ida --web

# 终端 2：启动 Vite 开发服务器（自动代理 API 到后端）
cd web-ui
npx vite
```

然后打开 `http://localhost:5173`（Vite 开发服务器）而不是 8000 端口。前端代码修改会即时热重载。

设置环境变量 `RAMUNE_WEB_DEV` 可从 `web-ui/dist/` 加载前端资源，而非打包位置。

## 架构

Web UI 是一个可选模块（`ramune_ida/web/`），包装在现有的 MCP ASGI 应用之上：

```
浏览器 (React SPA)
    │  HTTP REST + WebSocket
    ▼
MCP Server 进程
├── /api/*     → Web API（直接调用 Project 层）
├── /ws/*      → WebSocket（活动流）
├── /mcp       → MCP 协议（给 AI Agent）
└── /*         → SPA 静态文件
```

- **后端**：REST 端点直接调用 `Project.execute()`，绕过 MCP 协议开销
- **活动流**：ASGI 中间件拦截 MCP 工具调用，通过 WebSocket 广播
- **内部工具**：`core/webview/` 包含仅供 UI 使用的工具，标记 `mcp:false`（AI 不可见）
- **前端**：React + TypeScript + Vite，rc-dock 布局，tree-sitter C 解析，zustand 状态管理

## 前端代码质量声明

前端代码（`web-ui/`）由 Claude（Anthropic 的 AI 助手）在交互式开发过程中生成。虽然功能可用，但存在以下注意事项：

- **未经专业审查**：代码未经过正式的 code review 流程
- **快速迭代**：许多功能是快速构建和重构的，部分模式可能不一致
- **已知问题**：滚动、面板同步、错误处理等方面可能存在边界情况
- **依赖**：使用 rc-dock v3、web-tree-sitter、zustand、@tanstack/react-virtual

欢迎贡献和改进。
