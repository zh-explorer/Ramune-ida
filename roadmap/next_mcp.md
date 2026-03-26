# Next IDA MCP — 新项目设计备忘

基于对 `ida-pro-mcp` 项目的深度分析和讨论，整理出新项目的架构方向、关键决策和需要避免的坑。

---

## 核心设计原则

### 1. 精简工具 + Python 执行

不再提供几十个细粒度 MCP 工具。核心只保留 5-8 个高频工具，长尾需求通过 `execute_python` 覆盖。

| 工具 | 用途 |
|------|------|
| `get_decompilation(func)` | 获取伪代码 |
| `get_disassembly(func)` | 获取反汇编 |
| `get_function_list()` | 函数列表（分页/过滤） |
| `rename(addr, name)` | 重命名 |
| `retype(addr, type)` | 修改类型 |
| `set_comment(addr, comment)` | 添加注释 |
| `get_strings()` | 字符串列表 |
| **`execute_python(code)`** | **万能后备，覆盖所有长尾需求** |

理由：
- 工具越多，AI 选择决策越慢、越容易选错
- 逆向工程是探索性工作，预定义工具无法穷举场景
- AI 对 IDAPython API 足够熟悉，能自己写分析脚本
- 核心工具保证高频操作的可靠性和结构化输出

### 2. 只支持 headless idalib，放弃 GUI

不维护 IDA GUI plugin 模式。原项目为 GUI 支持付出了 800+ 行代码（plugin loader、HTTP proxy、配置 UI），砍掉后代码量减少 30%+。

### 3. 使用官方 MCP Python SDK，不自己造轮子

原项目的 zeromcp（~1400 行手写代码）存在以下问题：
- JSON 字符串参数需要 hacky 自动 parse
- SSE 断连检测跨平台不稳定
- 协议版本硬编码，手动维护
- 无 streaming 支持（大输出只能截断+下载链接）
- schema 生成不如 Pydantic 灵活

#### MCP 框架选型：官方 SDK (`mcp`) vs 独立 FastMCP (`fastmcp`)

背景：FastMCP 1.0 于 2024 年合并进官方 SDK（`mcp.server.fastmcp`），但之后独立 FastMCP 2.0/3.0 与 SDK 内嵌版本"已充分分化"（Anthropic 维护者原话），现在是两个独立项目。

| 维度 | 官方 MCP SDK (`mcp`) | 独立 FastMCP (`fastmcp` 3.x) |
|------|---------------------|------------------------------|
| 维护者 | Anthropic | Prefect (jlowin) |
| 最新版本 | v1.x stable, v2 pre-alpha | 3.1.1 (2026.3) |
| 工具定义 | `@mcp.tool()` 装饰器 | 同样 `@mcp.tool()` |
| transport | stdio / SSE / Streamable HTTP | 同上 |
| schema 生成 | Pydantic 集成 | Pydantic 集成 |
| 核心抽象 | ServerSession, lifespan hooks | Provider / Transform / Session State |
| 服务器组合 | ASGI 挂载 | `mount()` + 命名空间隔离 |
| 代理能力 | 无内置 | ProxyProvider, `from_client()` |
| 规范合规 | 严格 | 较宽松 |
| 开发速度 | 稳定 | ~3x PR 合并频率 |

**选择：官方 MCP Python SDK (`mcp`)**

理由：
1. **我们的 dispatch 是非标的** — 请求发给 pipe 通信的哑 worker，不是另一个 MCP server。FastMCP 的 ProxyProvider / mount 是为 MCP-to-MCP 设计的，用不上
2. **工具数量少** — 只有 5-8 个工具，FastMCP 减少样板代码的优势可以忽略
3. **需要透明控制** — worker 管理、session 路由、pipe I/O 是核心逻辑，官方 SDK 更底层更透明
4. **长期稳定** — Anthropic 维护，规范兼容有保证。独立 FastMCP 历史上已分裂过一次

---

## 关键架构：进程分离消除线程安全问题

### 原项目的问题

IDA SDK 内部数据结构无锁保护，所有 API 必须在主线程调用。原项目把 MCP server 嵌入 idalib 进程内，导致：

- HTTP 工作线程需要 `execute_sync()` 回主线程 → 复杂
- 主线程同时跑 server 和 IDA API → 职责冲突
- stdio 模式下主线程调 `execute_sync()` 排队给自己 → 死锁
- 不得不运行时检测线程 ID 打补丁（`sync.py`）

### 新架构：MCP 进程 + idalib Worker 进程

```
MCP Client (Claude Agent)
    │
    ▼
MCP Server 进程 (Python, async)
    │  职责：MCP 协议、会话路由、并发控制、Agent 管理
    │  使用成熟 MCP 框架
    │  同时管理 N 个 worker 进程
    │
    ├──pipe──▶ Worker 0 (idalib, 分析 binary_a)
    │           主线程: recv → ida_api → send (纯单线程循环)
    │
    ├──pipe──▶ Worker 1 (idalib, 分析 binary_b)
    │
    └──pipe──▶ Worker 2 (idalib, 分析 binary_c)
```

**idalib Worker 是一个极简的单线程命令执行器：**

```python
def worker_main(ipc_channel):
    idapro.open_database(path)

    while True:
        cmd = ipc_channel.recv()        # 阻塞读取命令
        result = dispatch(cmd)          # 直接调 IDA API，就在主线程
        ipc_channel.send(result)        # 返回结果
```

核心收益：
- **`execute_sync()` 完全不需要** — 主线程既读命令又执行，无跨线程
- **`@idasync` 装饰器不需要** — 没有多线程，没有同步问题
- **线程安全问题从架构层面消失** — 不是更好地处理，而是根本不存在
- **`execute_python` 天然安全** — AI 发来的代码直接在主线程 `exec()`

### IPC 通道选择：stdin/stdout pipe

| 方式 | 优点 | 缺点 |
|------|------|------|
| **stdin/stdout** ✅ | 最简单，subprocess 原生 | 只能一对一 |
| Unix Socket | 可重连 | 需要清理 socket 文件 |
| 共享内存 | 最快 | 复杂，序列化麻烦 |

推荐 stdin/stdout：
- `subprocess.Popen` 天然获得 pipe
- 协议简单：一行 JSON 进，一行 JSON 出
- worker 崩溃时 pipe 断开，MCP server 立刻感知
- 不需要端口分配、文件清理

---

## 实例管理与多 Agent 协同

### 从原项目继承的好设计

1. **Cold/Hot 会话模型** — 池满时 LRU 驱逐最旧会话为 cold（元数据保留，实例释放），下次访问时透明重新激活，用户无感知
2. **路径去重** — 同一二进制文件不开两个实例，防止 IDB 文件锁冲突
3. **锁释放策略** — spawn/kill 等 I/O 期间释放锁，避免死锁
4. **Default session 指针** — `switch` 只改指针，零 IDB 切换开销

### 原项目的不足（新项目要解决）

#### 问题 1：无 Agent 身份概念

原项目的 `session_id` 面向"打开的二进制"，不面向"谁在操作"。无法追踪哪个 Agent 做了什么。

新设计引入三层模型：

```
Agent (身份 + 权限)
  └── Session (Agent 对某个二进制的工作上下文)
       └── Worker (实际持有 IDB 的进程)
```

#### 问题 2：同一二进制无法多 Agent 并行

路径去重导致同一文件只能有一个实例。两个 Agent 分析同一个二进制会共享实例，IDA 全局状态互相干扰。

解决方案：允许 COW 副本 — 拷贝 `.i64` 到临时目录，不同 Agent 各自持有独立 IDB。

#### 问题 3：Pool Proxy 同步转发是瓶颈

原项目的 proxy 用同步 `http.client.HTTPConnection` 转发。高并发时阻塞。

解决方案：MCP server 本身就是 async 的，用 asyncio subprocess pipe 与 worker 通信，天然非阻塞。

#### 问题 4：无协同原语

没有锁防止两个 Agent 同时修改同一函数，没有变更通知，没有冲突解决。

最小可行方案：
- **乐观并发** — 修改附带版本号，冲突时后者 fail
- **变更订阅** — 用 MCP notification 推送修改事件
- **分工协议** — 在 Agent 编排层划分分析区域，不在 server 层解决

---

## 注意事项

### idalib 初始化耗时

`idapro.open_database()` 可能耗时几分钟（自动分析）。Worker 阻塞期间 pipe 上的命令排队等待。MCP server 需要：
- 给 `open` 设较长超时
- 不因一个 worker 在初始化就阻塞其他 worker 的请求
- 可选：`open` 异步返回 "analyzing" 状态，完成后推送通知

### IDB 文件锁

IDA 打开 `.i64` 时创建锁文件（`.i64~` 等），同路径不能在两个进程中打开。路径去重或 COW 副本机制必须保留。

### execute_python 的要求

- 返回值要可控 — 执行结果需结构化返回，不能只 `print`
- 错误信息要清晰 — 完整 traceback 传回
- 超时保护 — 防止死循环
- 能访问完整 IDA API — 不人为限制

### 输出大小

IDA 某些操作返回巨量数据（如全函数列表、大型反汇编）。新框架如果有 streaming 则用 streaming；否则仍需截断 + 分页机制。

---

## 技术栈

| 组件 | 选择 | 备注 |
|------|------|------|
| MCP 框架 | `mcp` (Anthropic 官方 Python SDK) | 用 `mcp.server.fastmcp.FastMCP` 定义工具 |
| async 运行时 | asyncio | SDK 原生 async |
| Worker 通信 | subprocess stdin/stdout pipe | JSON line protocol |
| 序列化 | 标准 json（性能不够再换 orjson） | |
| Worker 管理 | 自研（参考原项目 InstanceManager 设计） | |
| Python 版本 | 3.11+ | |
| IDA 版本 | IDA Pro 9.0+（idalib） | |

### MCP Server 端代码结构预览

```python
from mcp.server.fastmcp import FastMCP

server = FastMCP("ida-mcp")

# WorkerPool 是我们自己实现的核心模块
pool = WorkerPool(max_workers=4)

@server.tool()
async def get_decompilation(func: str, session_id: str = None) -> str:
    """获取函数伪代码"""
    worker = await pool.resolve(session_id)
    result = await worker.send_command("decompile", {"func": func})
    return result["code"]

@server.tool()
async def execute_python(code: str, session_id: str = None) -> str:
    """在 IDA 中执行 Python 代码"""
    worker = await pool.resolve(session_id)
    result = await worker.send_command("exec_python", {"code": code})
    return result["output"]
```
