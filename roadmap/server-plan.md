# MCP Server 框架实现计划

> 状态：框架已实现 | 日期：2026-03-25 | 更新：2026-03-25

## 现状

已实现的底层模块：

- `project.py` — Project + Task，任务队列、execute/cancel/force_close/save
- `limiter.py` — 全局实例计数 + soft/hard limit
- `worker_handle.py` — Worker 子进程管理
- `protocol.py` — IPC 消息类型
- `worker/` — Worker 进程侧

待实现：`server/` 目录（MCP 协议层）、`cli.py`、`__main__.py`

---

## 架构总览

```
MCP Client (Claude / Cursor / ...)
    │
    │  Streamable HTTP / SSE
    ▼
┌────────────────────────────────────────────────────────────┐
│              MCP Server 进程 (Python 3.14, async)           │
│                                                            │
│  FastMCP ─── Tools (server/tools/*.py)                     │
│      │         │                                           │
│      │         ▼                                           │
│      │      AppState ──→ dict[str, Project]                │
│      │         │         Limiter                           │
│      │         │         auto-save task                    │
│      │         │         OutputStore                       │
│      │                                                     │
│      ├── Resources (server/resources.py)                   │
│      │     项目文件信息、暂存区、下载 URL                      │
│      │                                                     │
│      └── custom_route (server/files.py, 仅 HTTP/SSE)      │
│            /files/upload, /files/{id}/idb, /outputs/{id}   │
│                                                            │
└─────────────────────┬──────────────────────────────────────┘
                      │ subprocess pipe (JSON line)
          ┌───────────┼───────────┐
          ▼           ▼           ▼
     Worker 0    Worker 1    Worker 2
      idalib      idalib      idalib
```

---

## 实现步骤

### 1. `config.py` — 配置

```python
@dataclass
class ServerConfig:
    worker_python: str = "python"
    soft_limit: int = 4
    hard_limit: int = 8
    auto_save_interval: float = 300.0  # 5 minutes
    work_base_dir: str = "~/.ramune-ida/projects"
```

从环境变量或 CLI 参数加载。

### 2. `server/state.py` — AppState 类

```python
class AppState:
    limiter: Limiter
    projects: dict[str, Project]
    default_project_id: str | None
    config: ServerConfig

    def open_project(exe_path, project_id?) -> Project  # 创建 project，路径去重
    def close_project(project_id) -> None               # close → force_close → 移除 → 清理
    def resolve_project(project_id?) -> Project          # 路由到具体 project
    def shutdown()                                       # force_close all
```

关键逻辑：

- `open_project`：路径去重（同一 exe_path 不重复打开）、AI 可指定 project_id 或自动生成（`{filename}-{short_hash}`）、创建 work_dir
- `close_project`：内部先 `execute("close_database")`（优雅），超时则 `force_close()` → 从 projects 移除 → 清理 work_dir
- `resolve_project(project_id=None)`：传 id 则查表，不传则用 default，找不到报错
- 定时 auto-save：`asyncio.create_task` 循环遍历 `limiter.active_projects`，对活跃 project 调 `save()`

### 3. `server/app.py` — FastMCP 实例 + lifespan

```python
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    state = AppState(config)
    try:
        yield {"state": state}
    finally:
        state.shutdown()  # force_close all projects

mcp = FastMCP("ramune-ida", lifespan=app_lifespan)
```

- `AppState` 持有 `limiter`、`projects`、`default_project_id`、`_auto_save_task`
- lifespan yield 后，所有 tool 通过 `ctx.request_context.lifespan_context["state"]` 访问
- shutdown 时 `force_close()` 所有 project

### 4. `server/tools/session.py` — 会话管理工具（9 个）

| 工具 | 实现要点 |
|------|----------|
| `open_project(path, project_id?)` | 创建 Project：生成 work_dir、注册到 state、返回 project_id。AI 可指定 id，不传则自动生成。不立即 spawn worker（lazy） |
| `close_project(project_id?)` | 销毁 Project：内部先 close_database（优雅关闭），超时则 force_close → 从 state.projects 移除 → 清理 work_dir。AI 调一次即可 |
| `close_database(project_id?)` | 仅关闭 worker 实例（save + 退出）。Project 继续存在，下次 execute 自动 respawn。用于主动释放资源 |
| `force_close(project_id?)` | 强制 kill worker。Project 继续存在。用于 IDA 卡死时强制结束 |
| `list_projects()` | 遍历 state.projects，返回 id/path/worker 状态/是否 default |
| `current_project()` | 返回 default project 信息 |
| `switch_default(project_id)` | 设置 state.default_project_id |
| `save_database(project_id?)` | project.save() |
| `get_task_result(task_id, project_id?)` | project.get_task_result(task_id) |

语义层次：

| 层级 | 操作 | 对象 | Project 存活 |
|------|------|------|-------------|
| Project 生命周期 | `open_project` / `close_project` | Project 本身 + work_dir + 文件 | 创建 / 销毁 |
| 实例资源管理 | `close_database` / `force_close` | 仅 worker 进程 | 保持存活 |

每个工具签名模式：

```python
@mcp.tool
async def open_project(path: str, ctx: Context, project_id: str | None = None) -> dict:
    state = get_state(ctx)
    ...
```

`get_state(ctx)` 提取 lifespan context 中的 AppState，封装为一行 helper。

### 5. `server/files.py` — HTTP 文件端点（仅 HTTP/SSE transport）

文件传输走纯 HTTP，**不注册为 MCP tool**（避免浪费 token/context）。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/files/upload` | POST | multipart 上传二进制到 server 暂存区，返回 server 端路径 |
| `/files/{project_id}/idb` | GET | 下载项目 IDB |
| `/files/{project_id}/exe` | GET | 下载原始二进制 |
| `/files/{project_id}` | GET | 列出项目 work_dir 下的文件 |
| `/outputs/{output_id}` | GET | 下载被截断输出的完整内容 |

通过 `@mcp.custom_route` 注册，与 MCP 端点共享同一 HTTP 服务。

**输出截断联动**：tool 返回超过阈值时，`server/output.py` 存完整内容，tool 返回截断文本 + `full_output_url`（如 `/outputs/out-001`）。AI 通过 URL 自行获取。

### 6. `server/resources.py` — MCP Resources（文件/路径信息查询）

将下载路径、暂存文件等信息通过 MCP Resource 协议暴露。AI 可读取查看，不消耗 tool call 额度。

```python
@mcp.resource("project://{project_id}/files")
def project_files(project_id: str) -> dict:
    """项目文件信息：IDB/exe 路径、大小、下载 URL"""

@mcp.resource("project://{project_id}/outputs")
def project_outputs(project_id: str) -> dict:
    """项目的截断输出列表：output_id、截断长度、完整长度、下载 URL"""

@mcp.resource("files://staging")
def staging_files() -> dict:
    """暂存区文件列表：已上传但未关联 project 的文件"""

@mcp.resource("files://downloads")
def download_urls() -> dict:
    """所有可用下载端点汇总"""
```

**Resource vs Tool 边界原则**：需要 worker 参与计算的一律 Tool（decompile、disasm、get_bytes 等）。Resource 只放 MCP server 进程自己就能回答的东西（文件路径、元数据、状态信息）。

### 7. `server/output.py` — 输出截断 + 全文缓存

```python
class OutputStore:
    def truncate_if_needed(content: str, max_len: int) -> tuple[str, str | None]
        # 返回 (可能截断的内容, full_output_url 或 None)
    def get_full(output_id: str) -> str | None
```

被所有可能产生大输出的 tool 使用（decompile、execute_python、list_funcs 等）。

### 8. `server/tools/__init__.py` — 统一注册

import 所有 tool 模块触发 `@mcp.tool` 装饰器注册。

### 9. `cli.py` + `__main__.py` — CLI 入口

传输方式通过 URL 指定，支持 http / sse 两种：

```
ramune-ida                          # 默认 http://127.0.0.1:8000
ramune-ida http://0.0.0.0:8000     # Streamable HTTP
ramune-ida sse://127.0.0.1:9000    # SSE (legacy)
```

```python
# cli.py
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8000",
                        help="Transport URL: http://host:port, sse://host:port")
    # ... --soft-limit, --hard-limit, --worker-python, etc.
    args = parser.parse_args()
    transport, host, port = parse_transport_url(args.url)
    mcp.run(transport=transport, host=host, port=port)
```

`parse_transport_url` 解析 URL scheme/host/port，默认 `http://127.0.0.1:8000`。

---

## 设计要点

- **over_soft_limit 通知**：`list_projects` 和涉及 execute 的工具返回结果中附带 `over_soft_limit: true`，让 AI 感知并主动关闭不需要的项目
- **project_id**：由 AI 在 `open_project` 时自行指定（如 `"firmware_v2"`）。不传则自动生成 `{filename}-{short_hash}`。重复 id 报错
- **路径去重**：`open_project` 对 `os.path.realpath(path)` 检查是否已有 project 打开同一文件
- **Transport URL 解析**：统一入口格式 `scheme://host:port`，支持 `http://host:port`、`sse://host:port`
- **tool 返回格式**：统一返回 dict，包含 `status`、业务字段、可选的 `warning`（如 over_soft_limit）
- **文件传输不走 MCP tool**：走 custom_route REST 端点，纯 HTTP binary 传输

---

## 文件结构（当前）

```
src/ramune_ida/
├── __init__.py
├── __main__.py                  # python -m ramune_ida
├── cli.py                       # CLI 入口（URL 解析 + argparse）
├── config.py                    # ServerConfig dataclass
│
├── protocol.py                  # Wire format: Method, Request/Response, ErrorCode, TaskStatus
├── commands.py                  # Command 基类 + 所有命令 dataclass（含 Result 内部类）
├── limiter.py                   # Limiter — 全局实例计数 + soft/hard limit
├── worker_handle.py             # WorkerHandle — 单个 Worker 子进程 (socketpair IPC)
├── project.py                   # Project + Task — 拥有 WorkerHandle、任务队列、执行循环
│
├── server/                      # MCP Server 层
│   ├── __init__.py
│   ├── app.py                   # FastMCP 实例、lifespan、register_tool 装饰器
│   ├── state.py                 # AppState（Project 集合、Limiter、OutputStore）
│   ├── output.py                # OutputStore（磁盘存储、自动截断、按 project 管理）
│   ├── files.py                 # HTTP 文件端点（custom_route，binary 上传/下载）
│   ├── resources.py             # MCP Resources（projects://、project://、outputs://、files://）
│   └── tools/
│       ├── __init__.py          # ★ Tool 注册表 — 所有 tool 在此集中声明
│       └── session.py           # 会话管理 tool 实现（纯 async 函数）
│
└── worker/                      # Worker 进程侧（运行在 idalib 环境中）
    ├── __init__.py
    ├── main.py                  # Worker 入口：消息循环
    ├── dispatch.py              # 命令分发：Method enum → handler
    ├── socket_io.py             # UNIX socketpair JSON line 读写
    └── handlers/                # 各命令的具体实现（调用 IDA API）
        ├── __init__.py
        ├── session.py           # open/close/save database
        └── analysis.py          # decompile, disasm
```

### 双侧对称设计

`server/tools/` 和 `worker/handlers/` 的文件结构一一对应：

- `server/tools/session.py` — MCP 接口层（调用 `project.execute(Command())`）
- `worker/handlers/session.py` — IDA 实现层（接收 Command，调用 `idapro` API）

---

## 添加新功能的开发流程

以添加 `xrefs_to` 工具为例：

### Step 1: 定义 Command（`commands.py`）

```python
@dataclass(slots=True)
class XrefsTo(Command):
    method: ClassVar[Method] = Method.XREFS_TO  # 先在 protocol.py 的 Method 枚举中添加
    addr: str = ""
    max_results: int = 100

    @dataclass(slots=True)
    class Result:
        addr: str = ""
        xrefs: list[dict[str, Any]] = field(default_factory=list)

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
```

同时在 `protocol.py` 中添加 `Method.XREFS_TO = "xrefs_to"`，
在 `commands.py` 底部的 `COMMAND_TYPES` 注册表中加入 `XrefsTo`。

### Step 2: 实现 Worker handler（`worker/handlers/analysis.py`）

```python
@handler(Method.XREFS_TO)
def handle_xrefs_to(cmd: XrefsTo) -> dict[str, Any]:
    import idautils
    addr = _resolve_addr(cmd.addr)
    xrefs = []
    for xref in idautils.XrefsTo(addr):
        xrefs.append({"from": hex(xref.frm), "type": xref.type})
        if len(xrefs) >= cmd.max_results:
            break
    return {"addr": hex(addr), "xrefs": xrefs}
```

在 `worker/main.py` 中确认 handler 模块已被 import（现有的
`import ramune_ida.worker.handlers.analysis` 会自动覆盖）。

### Step 3: 编写 MCP tool 实现（`server/tools/analysis.py`）

```python
async def xrefs_to(
    addr: str,
    ctx: Context,
    project_id: str | None = None,
    max_results: int = 100,
) -> dict:
    state = get_state()
    project = state.resolve_project(project_id)
    task = await project.execute(XrefsTo(addr=addr, max_results=max_results))
    return {
        "project_id": project.project_id,
        "status": task.status.value,
        **(task.result or {}),
    }
```

### Step 4: 注册 tool（`server/tools/__init__.py`）

```python
from ramune_ida.server.tools import analysis

register_tool(
    description=(
        "Get all cross-references to the given address or function name. "
        "Returns a list of {from, type} entries."
    ),
)(analysis.xrefs_to)
```

### 检查清单

- [ ] `protocol.py` — `Method` 枚举新增
- [ ] `commands.py` — `Command` 子类 + `Result` 内部类 + `COMMAND_TYPES` 注册
- [ ] `worker/handlers/` — `@handler(Method.XXX)` 实现
- [ ] `server/tools/<module>.py` — async 实现函数
- [ ] `server/tools/__init__.py` — `register_tool(description=...)(impl)` 注册
- [ ] `tests/` — 测试覆盖
