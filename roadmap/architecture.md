# Ramune-ida 架构设计文档

> 版本: 0.1 | 日期: 2026-03-25

---

## 一、项目定位

Ramune-ida 是一个 **headless IDA MCP Server**，将 IDA Pro idalib 的逆向分析能力通过 MCP 协议暴露给 AI Agent（Claude、Cursor 等）。

与参考项目 `ida-pro-mcp` 相比，核心差异：

| 维度 | ida-pro-mcp | Ramune-ida |
|------|-------------|------------|
| 运行模式 | GUI 插件 + headless + 池代理 三种 | **仅 headless idalib** |
| MCP 实现 | 自研 zeromcp (~1400 行) | 官方 MCP Python SDK (`mcp`) |
| 线程安全 | `@idasync` + `execute_sync` 补丁 | **进程分离，问题不存在** |
| 工具数量 | 71 个 | ~28 个核心工具 + `execute_python` 长尾覆盖 |
| 多实例 | 池代理 + Unix Socket HTTP 转发 | **WorkerPool + 专用 fd pair pipe** |
| Python | 3.11+ | 3.14（MCP Server 侧） |

---

## 二、核心设计原则

### 1. 进程分离消灭线程安全问题

IDA SDK 所有 API 必须在主线程调用。原项目把 MCP Server 嵌入 idalib 进程，导致 HTTP 工作线程需要 `execute_sync()` 回主线程、stdio 模式死锁等一系列问题。

**Ramune-ida 的解法：MCP Server 和 idalib 运行在不同进程中。**

- MCP Server 进程：纯 async Python，处理 MCP 协议、会话路由、并发控制
- Worker 进程：纯单线程，`recv → IDA API → send` 循环

`execute_sync` / `@idasync` 从架构层面不再需要。

### 2. 覆盖高频操作，长尾靠 execute_python

不追求原项目 71 个工具的全覆盖，但所有在实际逆向任务中被高频使用的操作都提供原生工具（结构化输入/输出、文档完备、错误处理友好）。低频和探索性需求通过 `execute_python` 在 IDA 环境中直接执行 IDAPython 脚本。

### 3. Worker 无状态，Pool 有状态

**Worker 是无状态的命令执行器。** 它唯一的"状态"是 idalib 当前加载的 IDB，而 IDB 是 IDA 引擎的状态，不是 Worker 代码的状态。Worker 的 Python 侧不维护任何状态变量——没有 `_current_db`、没有 session 跟踪、没有缓存。

所有管理状态（session 路由、Worker 分配、context 切换决策、LRU 驱逐）集中在 Pool 层。`session_id` 的传播范围在 MCP Server / Pool 层终止，永远不会到达 Worker。

这带来两个关键好处：
- **context 切换无风险** — Pool 可以随时让任何 Worker 关闭当前 IDB、打开另一个。不需要担心 Worker 内部残留状态导致的副作用
- **Worker 可替换** — 如果一个 Worker 崩溃，Pool 启动新 Worker 重新 open 同一个 IDB，从使用者角度完全透明。因为 Worker 没有需要迁移的状态，所有持久状态都在 IDB 里

### 4. Pool 池化管理

WorkerPool 统一管理 N 个 Worker 进程。每个 Worker 可以打开/关闭不同的 IDB 数据库，由 Pool 通过 session 路由将请求分发到正确的 Worker。

---

## 三、系统架构

### 3.1 进程模型

```
MCP Client (Claude / Cursor / ...)
    │
    │  stdio / Streamable HTTP
    ▼
┌─────────────────────────────────────────────────────┐
│              MCP Server 进程 (Python 3.14, async)    │
│                                                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ FastMCP  │  │  Session   │  │   WorkerPool     │  │
│  │ 工具注册  │  │  Router    │  │   N 个 Worker    │  │
│  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │
│       │              │                  │            │
│       └──────────────┴──────────────────┘            │
│                      │                               │
└──────────────────────┼───────────────────────────────┘
                       │ asyncio subprocess pipe (JSON line)
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ Worker 0 │ │ Worker 1 │ │ Worker 2 │
   │  idalib  │ │  idalib  │ │  idalib  │
   │ 单线程   │ │ 单线程   │ │ 单线程   │
   │ 可切换ctx│ │ 可切换ctx│ │ 可切换ctx│
   └──────────┘ └──────────┘ └──────────┘
```

### 3.2 Worker 内部结构

Worker 是一个极简的单线程命令执行器：

```python
def worker_main(pipe):
    while True:
        request = pipe.recv()           # 阻塞读取

        match request["method"]:
            case "open_database":
                idapro.open_database(request["params"]["path"])
            case "close_database":
                idapro.close_database()
            case "decompile":
                result = do_decompile(request["params"])
            case "exec_python":
                result = exec_python(request["params"]["code"])
            case ...

        pipe.send({"id": request["id"], "result": result})
```

关键特性：
- **所有 IDA API 调用都在主线程** — 因为整个 Worker 就是单线程
- **`execute_python` 天然安全** — `exec()` 直接在主线程执行
- **崩溃隔离** — 一个 Worker 崩溃不影响其他 Worker 和 MCP Server
- **可切换 context** — 同一 Worker 可以 `open_database` / `close_database` 切换不同 IDB

### 3.3 IPC 协议

MCP Server ↔ Worker 之间使用 **专用 fd pair + JSON line protocol**：

```
MCP Server                        Worker
  os.pipe() ──→ fd pair A ──→  RAMUNE_READ_FD   (child reads)
  os.pipe() ──→ fd pair B ──→  RAMUNE_WRITE_FD  (child writes)

→ (fd A)  {"id": "req-001", "method": "decompile", "params": {"func": "main"}, "timeout": 30}
← (fd B)  {"id": "req-001", "result": {"code": "int main() { ... }", "addr": "0x401000"}}
```

MCP Server 通过 `os.pipe()` 创建两对 fd，用 `subprocess.Popen(pass_fds=...)` 传给 Worker，fd 号通过环境变量 `RAMUNE_READ_FD` / `RAMUNE_WRITE_FD` 告知。

#### 消息格式

**Request**（Pool → Worker）：

```json
{
    "id": "req-001",
    "method": "decompile",
    "params": {"func": "main"},
    "timeout": 30
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 唯一请求 ID，用于配对响应 |
| `method` | string | 命令名称 |
| `params` | object | 命令参数 |
| `timeout` | float \| null | 超时秒数（Pool 用于 `asyncio.wait_for`，**Worker 忽略此字段**） |

**Response**（Worker → Pool）：

```json
{"id": "req-001", "result": {"code": "int main() { ... }"}}
{"id": "req-001", "error": {"code": -1, "message": "Function not found"}}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 与 Request 配对 |
| `result` | any | 成功时的返回值 |
| `error` | object \| null | 失败时的错误信息（`code` + `message`） |

- 每条消息独占一行（`\n` 分隔）
- **stdin/stdout/stderr 完全不动** — IDA console messages、`print()`、logging 照常工作
- `timeout` 字段是 Pool 层的调度提示，不改变 Worker 的执行行为。Worker 不做超时自杀——超时控制权在 Pool

#### 三层通道模型

Pool 与 Worker 之间不只是单一的 pipe 通道，而是三个语义不同的通道协同工作：

```
通道 1: Queue（asyncio.Queue, Pool 进程内）
   命令 → 排队 → 等待上一个完成
   控制：排队中的命令可以被直接移除取消

通道 2: Pipe（专用 fd pair, 跨进程）
   当前执行的命令 → 写入 pipe → Worker 读取 → 执行 → 写回结果
   控制：Worker 执行期间此通道被占用，一次只有一个命令

通道 3: OS Signal（跨进程, 带外）
   SIGUSR1（优雅取消）、SIGKILL（强制终止）
   控制：完全绕过 Queue 和 Pipe，直达 Worker 进程
```

- **正常流**：Queue → Pipe → Worker 执行 → Pipe 返回
- **取消排队命令**：直接从 Queue 移除
- **取消执行中命令**：OS Signal（SIGUSR1 → grace period → SIGKILL）
- **崩溃检测**：Pipe 读取返回 EOF

#### 选型理由

选择专用 fd pair（而非 stdio pipe 或 Unix domain socket）：
- **stdout 无冲突** — 不需要劫持 stdout，idalib 和 `execute_python` 中的 print() 输出不会污染协议通道
- **subprocess 生命周期管理** — Worker 崩溃时 pipe 断开，MCP Server 立刻感知
- **零清理** — 不像 Unix socket 需要清理 socket 文件
- **零配置** — `os.pipe()` + `pass_fds`，不需要端口分配

---

## 四、Pool 层：会话、实例与任务管理

Pool 是 MCP Server 和 Worker 之间的管理层。它是系统中唯一持有管理状态的组件，承担三大职责：

```
Pool 职责
├── 1. Session 路由
│   ├── session_id → Worker 映射
│   ├── context 切换（close + open）
│   ├── LRU 驱逐
│   └── 路径去重
│
├── 2. Worker 生命周期
│   ├── spawn / kill / restart
│   ├── 健康检查（ping）
│   ├── 崩溃检测（pipe broken）
│   └── 崩溃恢复（auto reopen IDB）
│
└── 3. 任务执行管理
    ├── 命令队列（per-Worker 串行化）
    ├── 超时 → 返回 pending + task_id
    ├── 结果缓存（供后续查询）
    ├── 取消（排队中移除 / 执行中 signal+kill）
    └── 定期 auto-save IDB
```

### 4.1 Pool 对 IDA 命令的了解范围

**Pool 是一个对 IDA 语义几乎无感知的 session-aware 转发层。** 它只认识以下命令，且仅用于生命周期管理：

| 命令 | Pool 用途 |
|------|----------|
| `open_database` | context 切换、崩溃恢复后 reopen |
| `close_database` | context 切换、LRU 驱逐 |
| `save_database` | 定期 auto-save、驱逐前保存、取消前保存 |
| `ping` | 健康检查 |

其余所有命令（`decompile`、`rename`、`execute_python` 等）对 Pool 完全不透明——只是 `(method, params)` 转发。添加新的 IDA 工具时 Pool 层不需要任何修改。

超时策略也不由 Pool 硬编码：MCP Server 在 Request 中附带 `timeout` 字段，Pool 按该值执行 `asyncio.wait_for`。

### 4.2 Pool 公共接口

```python
class Pool:
    async def open_session(self, path: str) -> str:
        """打开二进制 → 分配 Worker → 返回 session_id"""

    async def close_session(self, session_id: str) -> None:
        """关闭 session → close_database → 释放 Worker"""

    async def execute(self, session_id: str, method: str, params: dict,
                      timeout: float | None = None) -> Any:
        """转发命令到 session 对应的 Worker
           - 确保 Worker 已加载正确的 IDB（必要时 context 切换）
           - 超时未完成 → 返回 PendingTask"""

    async def cancel(self, task_id: str) -> None:
        """取消任务（排队中 → 移除；执行中 → signal/kill Worker）"""

    async def get_task_result(self, task_id: str) -> Any:
        """查询异步任务的结果"""

    async def list_sessions(self) -> list[SessionInfo]:
        """列出所有 session 及其状态"""

    async def shutdown(self) -> None:
        """save 所有 IDB → 关闭所有 Worker"""
```

MCP Server 调用 Pool API 时，`session_id` 在此层终止，不会传递给 Worker。

### 4.3 Session 概念模型

```
Session (对某个二进制的工作上下文)
  │
  └── 映射到 → Worker (实际持有 IDB 的进程)
```

- **session_id** 由 Pool 在 `open_session` 时生成，返回给 MCP Server 再返回给客户端
- 后续所有工具调用通过 `session_id` 参数路由到正确的 Worker
- 支持 **default session** — 不传 `session_id` 时使用默认会话，单二进制场景零摩擦

### 4.4 Worker-Session 绑定模型：混合模式

活跃 session 尽量独占 Worker（避免 context 切换开销），pool 满时才在 Worker 间切换：

| 策略 | 说明 |
|------|------|
| **池大小** | 可配置 `max_workers`（默认 4），`0` 表示无上限 |
| **独占优先** | 活跃 session 绑定到固定 Worker，只要 Worker 有空闲就不复用 |
| **路径去重** | 同一文件路径不会在两个 Worker 中同时打开（IDB 文件锁约束） |
| **LRU 驱逐** | 池满时，最久未使用的 session 被驱逐为 cold 状态（save + close IDB，释放 Worker）|
| **透明重激活** | 访问 cold session 时自动分配 Worker 重新打开 IDB，用户无感知 |
| **池满切换** | 当活跃 session 数 > Worker 数时，不得不在 Worker 间切换 context |

### 4.5 Session 生命周期

```
            open_session(path)
                   │
                   ▼
            ┌─────────────┐
            │    Active    │ ← 绑定到某个 Worker，IDB 已打开
            │              │
            └──────┬───┬───┘
                   │   │
        LRU 驱逐 ──┘   └── close_session
                   │          │
                   ▼          ▼
            ┌──────────┐  ┌────────┐
            │   Cold   │  │ Closed │
            │ 元数据保留│  │  销毁  │
            │ IDB 已关闭│  └────────┘
            └─────┬────┘
                  │
          访问时重激活
                  │
                  ▼
            ┌─────────────┐
            │    Active    │
            └─────────────┘
```

### 4.6 Context 切换策略

当一个请求到达 Pool：

```
1. session_id → 查 session 表 → 找到关联的 Worker
2. 如果该 Worker 当前 context 就是这个 session → 直接执行
3. 如果该 Worker 当前持有其他 session 的 context → 先 close → 再 open 目标 IDB
4. 如果 session 是 cold 状态（无 Worker）→ 从池中分配空闲 Worker → open IDB
5. 如果池满且无空闲 Worker → LRU 驱逐最旧 session（save + close）→ 释放 Worker → 分配
```

context 切换有开销（`open_database` 可能耗时数秒到数分钟），因此混合模式优先让活跃 session 独占 Worker 以减少切换。

### 4.7 WorkerHandle：单个 Worker 的 async 封装

WorkerHandle 是 Pool 内部组件，封装对单个 Worker 进程的所有交互：

```
WorkerHandle
├── 进程管理
│   ├── spawn()      启动 Worker 子进程，建立 pipe fd pair
│   ├── kill()       SIGKILL 终止进程
│   └── is_alive()   检查进程是否存活
│
├── 通信
│   ├── _pipe_send()   async 写 pipe（发送 Request）
│   ├── _pipe_recv()   async 读 pipe（接收 Response）
│   └── ping()         发送 ping，检查 Worker 响应
│
├── 命令队列
│   ├── _queue: asyncio.Queue    待执行命令 FIFO
│   ├── _current: PendingRequest  当前正在执行的命令
│   └── _consumer_task           后台 task：逐个取出执行
│
└── 状态
    ├── current_idb: str | None   当前加载的 IDB 路径（Pool 维护，非 Worker 维护）
    └── pid: int                  Worker 进程 ID
```

#### 三层通道模型

WorkerHandle 提供三种与 Worker 交互的通道，用于不同场景：

```
WorkerHandle 对外 API
│
├── submit(request) ──→ [Queue] ──→ [Pipe] ──→ Worker 执行
│                        FIFO         串行      单线程
│                     (asyncio.Queue)
│
├── cancel_queued(req_id) ──→ 直接从 Queue 移除，返回 cancelled
│
└── cancel_running() ──→ OS signal ──→ Worker 进程
                         SIGUSR1 → grace period → SIGKILL
                         完全绕过 pipe 和 queue
```

- **正常命令**通过 Queue → Pipe 的串行通道，保证 Worker 同一时间只处理一个命令
- **取消排队中的命令**直接操作 Queue，无需 Worker 参与
- **取消执行中的命令**通过 OS 信号绕过一切队列和 pipe，直达 Worker 进程

---

## 五、超时、取消与容错

IDA 不稳定——卡死、崩溃是常态。Worker 的无状态原则让我们能用"杀掉重启"作为万能后备。

### 5.1 超时与异步任务

MCP Client 有自己的超时限制。当 Worker 执行耗时超过预期时，Pool 不能无限等待。

```
MCP Client: execute_python("...长时间脚本...")
    │
    ▼
Pool.execute(session_id, method, params, timeout=30)
    │
    ├── Worker 在 30s 内响应 → 直接返回结果
    │
    └── Worker 超时未响应:
        ├── Pool 返回 {status: "running", task_id: "t-001"} 给 MCP Server
        ├── Worker 继续执行...
        ├── 结果最终到达 → Pool 缓存到 task_results[t-001]
        └── MCP Server 暴露 get_task_result(task_id) 工具供客户端轮询
```

超时值由 MCP Server 通过 Request 的 `timeout` 字段传递给 Pool，不由 Pool 硬编码。不同命令可以有不同超时：

| 命令类型 | 建议超时 | 说明 |
|---------|---------|------|
| `decompile` / `disasm` 等常规命令 | 30s | 正常不超过几秒 |
| `open_database` | 300s | 自动分析可能很慢 |
| `execute_python` | 60s（可配置） | AI 脚本复杂度不可预知 |
| `survey_binary` | 120s | 大型二进制概览耗时 |

### 5.2 取消机制

取消分两种情况，处理方式完全不同：

#### 取消排队中的命令

命令还在 WorkerHandle 的 Queue 中，尚未发给 Worker：

```
Pool.cancel(task_id)
  → 在 Queue 中找到该命令 → 移除 → 返回 cancelled
  Worker 完全不知道
```

#### 取消正在 Worker 中执行的命令

Worker 是单线程，正在 `exec()` 用户代码或调用 IDA API，无法从 pipe 读取取消命令。必须走带外通道：

```
Pool.cancel(task_id)
  → 发现该命令正在 Worker 中执行
  → 阶段 1：尝试优雅取消
  │   发送 SIGUSR1 → Worker 信号处理器设置 cancel flag
  │   等待 grace period（默认 5s）
  │   如果 Worker 在 grace period 内返回 → 成功
  │
  → 阶段 2：暴力取消（grace period 超时）
      发送 SIGKILL → Worker 立即终止
      spawn 新 Worker → 从最近 auto-save 重新 open IDB
```

**优雅取消的实现**（后续实现，第一版直接 kill）：
- Worker 收到 SIGUSR1 后，信号处理器设置 `_cancel_requested = True`
- `execute_python` handler 通过 `sys.settrace()` 在每行 Python 代码执行时检查该标志，抛出 `CancelledError`
- 这对纯 Python 代码有效，但对阻塞在 IDA C 扩展内部的调用无效（降级为 kill）
- `_cancel_requested` 是瞬时的执行时运行时状态，不跨越请求边界，不违反 Worker 无状态原则

**第一版策略**：取消 = 直接 kill Worker + restart + reopen IDB。简单可靠。

### 5.3 崩溃检测与恢复

```
Worker 崩溃
  │
  ▼
Pool 检测到 pipe 断开（读取返回 EOF）
  │
  ├── 标记该 Worker 为 dead
  ├── 标记其当前 session 为 cold
  ├── spawn 新 Worker
  └── 下次访问该 session 时自动 reopen IDB（透明重激活）
```

Pool 还通过定期 ping 检测 Worker 假死（进程在但不响应）：

```
Pool 健康检查循环：
  for worker in active_workers:
      response = await worker.ping(timeout=5s)
      if timeout:
          # Worker 假死，按崩溃处理
          worker.kill()
          spawn replacement
```

### 5.4 IDB 持久化

IDA 的所有分析成果（命名、类型、注释）存在 IDB 中。崩溃时未保存的修改会丢失。

**Auto-save（Pool 层）**：Pool 后台定时向活跃 Worker 发送 `save_database`，纯基础设施，用户不可见：

| 触发时机 | 说明 |
|---------|------|
| 定时（默认 5 分钟） | 后台 asyncio task，轮流向各活跃 Worker 发 save |
| LRU 驱逐前 | `close_database(save=True)` |
| 取消执行前（如果 Worker 还能响应） | 尝试发 `save_database`，超时则放弃 |
| `shutdown` 时 | 所有 Worker 逐个 save + close |

**Snapshot（MCP Server 层）**：IDB 文件级别的完整备份，用于防止逻辑错误（误操作、批量修改方向错误等），由 AI agent 主动触发：

```
snapshot_create(session_id, description?)
  1. pool.execute(session_id, "save_database")    ← flush IDB 到磁盘
  2. shutil.copy(idb_path, snapshot_dir/xxx.i64)  ← MCP Server 做文件拷贝
  3. 记录快照元数据（时间戳、描述、路径）

snapshot_restore(session_id, snapshot_id)
  1. pool.execute(session_id, "close_database")
  2. shutil.copy(snapshot_path, idb_path)          ← 覆盖回去
  3. pool.execute(session_id, "open_database", path)

snapshot_list(session_id)
  → 纯文件系统操作，不需要 Pool 参与
```

职责划分：
- **Pool 负责 auto-save** — 基础设施级别，防崩溃丢数据，对用户透明
- **MCP Server 负责 snapshot** — 用户可见的功能，Pool 不知道 snapshot 的存在
- **不做自动 snapshot** — IDB 文件可能很大（几百 MB+），自动快照的触发时机也无法合理判断。AI agent 在批量修改前主动 `snapshot_create` 是更好的策略

---

## 六、工具设计

### 6.1 设计原则

- **结构化输入/输出** — 所有工具使用 Pydantic model 定义参数和返回值
- **分页支持** — 可能返回大量结果的工具（list_funcs、imports、get_strings）内置分页
- **session_id 可选** — 所有工具接受可选的 `session_id` 参数，不传则使用 default session
- **错误信息清晰** — 完整的错误类型 + 人可读消息 + 相关上下文

### 6.2 工具清单

#### 会话管理（9 个）

| 工具 | 说明 |
|------|------|
| `open_database(path)` | 打开 IDB/二进制文件，返回 session_id |
| `close_database(session_id)` | 关闭会话 |
| `switch_default(session_id)` | 切换 default session 指针 |
| `list_sessions()` | 列出所有 session（含状态） |
| `current_session()` | 返回当前 default session 信息 |
| `save_database(session_id?)` | 保存 IDB |
| `snapshot_create(session_id?, description?)` | 创建 IDB 快照（save + 文件拷贝），MCP Server 层实现 |
| `snapshot_list(session_id?)` | 列出快照（纯文件系统操作） |
| `snapshot_restore(session_id?, snapshot_id)` | 恢复快照（close → 覆盖 IDB → reopen） |

#### 分析类（8 个）

| 工具 | 说明 | 原项目对应 |
|------|------|-----------|
| `decompile(func, session_id?)` | 反编译函数，支持地址/名称 | `decompile` |
| `disasm(addr, count?, session_id?)` | 反汇编指令 | `disasm` |
| `xrefs_to(addr, session_id?)` | 获取到某地址的交叉引用 | `xrefs_to` |
| `callees(func, session_id?)` | 获取函数调用的所有函数 | `callees` |
| `callgraph(funcs, depth?, session_id?)` | 调用图 | `callgraph` |
| `find_bytes(pattern, session_id?)` | 搜索字节模式 | `find_bytes` |
| `find_regex(pattern, session_id?)` | 正则搜索 | `find_regex` |
| `survey_binary(session_id?)` | 二进制文件概览 | `survey_binary` |

#### 核心查询类（4 个）

| 工具 | 说明 | 原项目对应 |
|------|------|-----------|
| `list_funcs(filter?, offset?, count?, session_id?)` | 函数列表，支持过滤/分页 | `list_funcs` + `lookup_funcs` |
| `list_strings(filter?, offset?, count?, session_id?)` | 字符串列表，支持过滤/分页 | `find_regex(".*")` 等 |
| `list_imports(module?, offset?, count?, session_id?)` | 导入表，支持按模块/分页 | `imports` + `imports_query` |
| `list_globals(filter?, offset?, count?, session_id?)` | 全局变量列表 | `list_globals` |

#### 内存读取类（3 个）

| 工具 | 说明 | 原项目对应 |
|------|------|-----------|
| `get_bytes(addr, size, session_id?)` | 读取原始字节 | `get_bytes` |
| `get_string(addr, session_id?)` | 读取字符串 | `get_string` |
| `get_int(addr, size?, session_id?)` | 读取整数值 | `get_int` |

#### 修改类（4 个）

| 工具 | 说明 | 原项目对应 |
|------|------|-----------|
| `rename(targets, session_id?)` | 重命名函数/变量（支持批量） | `rename` |
| `set_type(targets, session_id?)` | 设置/修改类型（支持批量） | `set_type` |
| `set_comment(targets, session_id?)` | 设置注释（支持批量） | `set_comments` |
| `declare_type(declaration, session_id?)` | 声明结构体/枚举/typedef | `declare_type` |

#### 栈帧类（1 个）

| 工具 | 说明 | 原项目对应 |
|------|------|-----------|
| `stack_frame(func, session_id?)` | 查看函数栈帧布局 | `stack_frame` |

#### Python 执行（1 个）

| 工具 | 说明 |
|------|------|
| `execute_python(code, session_id?)` | 在 idalib 环境中执行任意 Python 代码 |

**合计：30 个工具**

### 6.3 execute_python 规范

`execute_python` 是覆盖所有长尾需求的万能后备。它的行为需要精确定义：

```python
# Worker 侧执行逻辑
def handle_exec_python(code: str) -> dict:
    namespace = {"__builtins__": __builtins__}
    # 预注入常用模块，减少 AI 的 import 样板
    exec("import idaapi, idautils, ida_funcs, ida_bytes, ida_hexrays, idc", namespace)

    try:
        exec(code, namespace)
    except Exception:
        return {"output": "", "error": traceback.format_exc()}

    result = namespace.get("_result", None)
    stdout_capture = ... # 捕获 print 输出

    return {"output": stdout_capture, "result": result, "error": None}
```

约定：
- 代码中将 `_result` 变量赋值即为结构化返回值
- `print()` 输出被捕获为 `output` 字段
- 完整 traceback 返回给客户端
- 超时保护（可配置，默认 60 秒）
- 预注入 IDA 常用模块

### 6.4 输出大小控制

| 策略 | 说明 |
|------|------|
| 截断 | 超过阈值（默认 50KB）的输出截断，附带 `truncated: true` 标记 |
| 分页 | 列表类工具内置 `offset` + `count` 参数 |
| 摘要模式 | `decompile` 支持 `summary=true` 参数，只返回签名+调用+字符串+控制流概览 |

---

## 七、模块划分

```
src/ramune_ida/
├── __init__.py
├── __main__.py                  # python -m ramune_ida
├── cli.py                       # CLI 入口（argparse）
├── config.py                    # 配置定义（Pydantic Settings）
│
├── server/                      # MCP Server 层
│   ├── __init__.py
│   ├── app.py                   # FastMCP 实例创建、lifespan 管理
│   ├── tools/                   # 工具定义（按类别分文件）
│   │   ├── __init__.py          # 统一注册所有工具
│   │   ├── session.py           # 会话管理工具
│   │   ├── analysis.py          # decompile, disasm, xrefs_to, ...
│   │   ├── query.py             # list_funcs, list_strings, list_imports, ...
│   │   ├── memory.py            # get_bytes, get_string, get_int
│   │   ├── modify.py            # rename, set_type, set_comment, declare_type
│   │   └── python.py            # execute_python
│   ├── output.py                # 输出截断/格式化
│   └── snapshot.py              # IDB 快照管理（create/list/restore，纯文件操作）
│
├── pool/                        # Worker 池管理层
│   ├── __init__.py
│   ├── manager.py               # WorkerPool — Pool 公共接口、auto-save 循环
│   ├── router.py                # SessionRouter — session_id → Worker 映射、LRU 驱逐
│   ├── worker_handle.py         # WorkerHandle — 单个 Worker 的 async 封装、命令队列
│   ├── session_state.py         # Session 状态机（Active/Cold/Closed）
│   └── task_store.py            # 异步任务结果缓存（pending/completed/cancelled）
│
├── worker/                      # Worker 进程侧（运行在 idalib 环境中）
│   ├── __init__.py
│   ├── main.py                  # Worker 入口：消息循环
│   ├── dispatch.py              # 命令分发：method → handler
│   ├── handlers/                # 各命令的具体实现（调用 IDA API）
│   │   ├── __init__.py
│   │   ├── session.py           # open/close/save database
│   │   ├── analysis.py          # decompile, disasm, xrefs_to, ...
│   │   ├── query.py             # list_funcs, imports, strings, ...
│   │   ├── memory.py            # get_bytes, get_string, get_int
│   │   ├── modify.py            # rename, set_type, set_comment, ...
│   │   └── python.py            # execute_python
│   └── pipe_io.py               # 专用 fd pair JSON line 读写
│
└── protocol.py                  # IPC 消息定义（Request/Response schema）
```

**双侧对称设计**：`server/tools/` 和 `worker/handlers/` 的文件结构一一对应。
- `server/tools/analysis.py` 定义 MCP 工具接口、参数校验、调用 Worker
- `worker/handlers/analysis.py` 实现具体的 IDA API 调用逻辑

### 模块职责边界

| 模块 | 职责 | 不做什么 |
|------|------|----------|
| `server/` | MCP 协议、参数校验、输出格式化、IDB 快照管理 | 不调用任何 IDA API |
| `pool/` | Worker 生命周期、session 路由、并发控制、auto-save | 不知道具体工具和快照 |
| `worker/` | IDA API 调用、结果序列化 | 不知道 MCP 协议的存在 |
| `protocol.py` | 定义两侧共享的消息格式 | 不含业务逻辑 |

---

## 八、技术栈

| 组件 | 选择 | 版本 | 备注 |
|------|------|------|------|
| MCP 框架 | `mcp` (Anthropic 官方 SDK) | latest | 用 `mcp.server.fastmcp.FastMCP` |
| async 运行时 | asyncio | 标准库 | |
| 参数校验 | Pydantic | v2 | FastMCP 原生集成 |
| Worker 通信 | 专用 fd pair (`os.pipe` + `pass_fds`) | 标准库 | JSON line protocol |
| 序列化 | orjson | latest | 性能优于标准 json，IPC 高频场景值得 |
| CLI | argparse / click | 标准库 | |
| Python (MCP Server) | 3.14 | | |
| Python (Worker) | idalib 要求的版本 | 可能是 3.12 | 见注意事项 |
| IDA | IDA Pro 9.0+ (idalib) | | |
| 包管理 | PDM | | pyproject.toml 已配置 |

---

## 九、MCP Transport 支持

| Transport | 优先级 | 场景 |
|-----------|--------|------|
| **stdio** | P0（首版必须） | Claude Desktop、Cursor 等本地 MCP 客户端 |
| **Streamable HTTP** | P1 | 远程部署、容器化、多客户端共享 |
| SSE | 不做 | 被 Streamable HTTP 取代 |

stdio 模式下 MCP Server 自身通过 stdin/stdout 与 MCP Client 通信，与 Worker 的 pipe 是独立的（Worker 通过 `subprocess.Popen` 的 pipe 通信，不占用 MCP Server 的 stdio）。

---

## 十、配置

```python
class RamuneConfig:
    max_workers: int = 4            # Worker 池大小，0=无上限
    worker_python: str = "python"   # Worker 使用的 Python 路径（可能需要指向 IDA 的 Python）
    ida_dir: str | None = None      # IDADIR 环境变量
    output_limit: int = 50_000      # 输出截断阈值（字符数）
    exec_timeout: int = 60          # execute_python 超时（秒）
    open_timeout: int = 300         # open_database 超时（秒）
    transport: str = "stdio"        # stdio | http://host:port
    log_level: str = "INFO"
```

配置来源优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值

---

## 十一、注意事项

### 11.1 Worker Python 版本

MCP Server 使用 Python 3.14，但 Worker 进程需要 `import idapro`，受 idalib 的 Python 版本约束（IDA Pro 9.0 通常捆绑 Python 3.12）。因此 Worker 可能需要使用不同版本的 Python 启动。

通过 `worker_python` 配置项解决：

```bash
# MCP Server 用系统 Python 3.14
ramune-ida --worker-python /opt/ida/python3 --transport stdio
```

这也意味着 `worker/` 目录下的代码不能使用 Python 3.13+ 的新语法特性。

### 11.2 idalib 初始化耗时

`idapro.open_database()` 对新文件可能触发自动分析，耗时数秒到数分钟。

- MCP Server 不因一个 Worker 在初始化就阻塞其他请求
- `open_database` 工具异步执行，前端可以轮询状态或等待完成
- 后续考虑：返回 "analyzing" 中间状态 + 完成通知

### 11.3 IDB 文件锁

IDA 打开 `.i64` 时创建锁文件。同一路径不能在两个进程中同时打开。

- SessionRouter 在路由层做路径去重检查
- 如果未来需要多 Agent 分析同一文件 → COW 副本（拷贝 `.i64` 到临时目录）

### 11.4 execute_python 安全边界

`execute_python` 允许在 Worker 中执行任意代码。安全策略：

- **超时保护** — 默认 60 秒，防死循环
- **输出限制** — 截断超大输出
- **进程隔离** — Worker 崩溃不影响 MCP Server
- **不做沙箱** — idalib 环境需要完整权限，人为限制得不偿失

---

## 十二、数据流示例

### 12.1 单次工具调用

```
MCP Client                    MCP Server                    Worker
    │                              │                           │
    │  tools/call: decompile       │                           │
    │  {func: "main",             │                           │
    │   session_id: "sess-001"}   │                           │
    │ ───────────────────────────▶ │                           │
    │                              │ 查 session 表              │
    │                              │ sess-001 → Worker 0       │
    │                              │ Worker 0 当前 ctx 匹配    │
    │                              │                           │
    │                              │  {"id":"r1",              │
    │                              │   "method":"decompile",   │
    │                              │   "params":{"func":"main"}}│
    │                              │ ─────────────────────────▶ │
    │                              │                           │ ida_hexrays.
    │                              │                           │ decompile()
    │                              │  {"id":"r1",              │
    │                              │   "result":{"code":"..."}}│
    │                              │ ◀───────────────────────── │
    │                              │                           │
    │  result: {code: "int main   │                           │
    │   () { ... }"}              │                           │
    │ ◀─────────────────────────── │                           │
```

### 12.2 Context 切换

```
MCP Client                    MCP Server                     Worker 0
    │                              │                            │
    │  decompile(func="main",      │                            │ 当前 ctx:
    │   session_id="sess-002")     │                            │  sess-001
    │ ───────────────────────────▶  │                            │  (binary_a)
    │                              │ 查表: sess-002 → Worker 0  │
    │                              │ Worker 0 ctx ≠ sess-002    │
    │                              │                            │
    │                              │  close_database             │
    │                              │ ──────────────────────────▶ │ close binary_a
    │                              │                            │
    │                              │  open_database(binary_b)    │
    │                              │ ──────────────────────────▶ │ open binary_b
    │                              │                            │
    │                              │  decompile(main)            │
    │                              │ ──────────────────────────▶ │ 执行
    │                              │ ◀────────────────────────── │ 返回结果
    │                              │                            │ 当前 ctx:
    │  result: ...                 │                            │  sess-002
    │ ◀─────────────────────────── │                            │  (binary_b)
```

---

## 十三、CLI 接口

```bash
# 基本用法（stdio 模式，给 Claude Desktop / Cursor 用）
ramune-ida --transport stdio

# 指定 Worker 池大小和 IDA 路径
ramune-ida --transport stdio --max-workers 4 --ida-dir /opt/ida-pro-9.0

# HTTP 模式（远程/容器部署）
ramune-ida --transport http://0.0.0.0:8745

# Worker 使用 IDA 自带的 Python
ramune-ida --transport stdio --worker-python /opt/ida-pro-9.0/python3

# 直接打开一个文件（省去 open_database 步骤）
ramune-ida --transport stdio --open /path/to/binary
```

入口点定义（pyproject.toml）：

```toml
[project.scripts]
ramune-ida = "ramune_ida.cli:main"
```

---

## 十四、与 ida-pro-mcp 功能对照

下表列出 ida-pro-mcp 中实际被使用的功能及 Ramune-ida 的覆盖方式：

| ida-pro-mcp 工具 | 使用频率 | Ramune-ida 覆盖 |
|------------------|---------|----------------|
| `decompile` | 极高 (200+/项目) | `decompile` 原生工具 |
| `get_bytes` | 极高 (100+) | `get_bytes` 原生工具 |
| `xrefs_to` | 高 (80+) | `xrefs_to` 原生工具 |
| `rename` | 高 (120+) | `rename` 原生工具 |
| `find_bytes` | 高 (50+) | `find_bytes` 原生工具 |
| `list_funcs` / `lookup_funcs` | 高 (60+) | `list_funcs`（合并，支持过滤） |
| `imports` / `imports_query` | 中 | `list_imports` 原生工具 |
| `survey_binary` | 中 | `survey_binary` 原生工具 |
| `disasm` | 中 | `disasm` 原生工具 |
| `set_comments` | 中 | `set_comment` 原生工具 |
| `callees` / `callgraph` | 中 | `callees` + `callgraph` 原生工具 |
| `get_string` | 中 | `get_string` 原生工具 |
| `stack_frame` | 中 | `stack_frame` 原生工具 |
| `set_type` | 中 | `set_type` 原生工具 |
| `declare_type` | 低 | `declare_type` 原生工具 |
| `py_eval` | 低 | `execute_python`（增强版） |
| `idalib_open/close/switch/list/save` | 中 | 会话管理工具组 |
| `find_regex` | 中 | `find_regex` 原生工具 |
| `list_globals` | 低 | `list_globals` 原生工具 |
| `get_int` | 低 | `get_int` 原生工具 |
| `trace_data_flow` | 低（实用性不足） | `execute_python` 覆盖 |
| `analyze_batch/component` | 低（定位模糊） | `execute_python` 覆盖 |
| `diff_before_after` | 低 | `execute_python` 覆盖 |
| `patch` / `patch_asm` | 低 | `execute_python` 覆盖 |
| `enum_upsert` | 未使用 | `execute_python` 覆盖 |
| `read_struct` / `search_structs` | 未使用 | `execute_python` 覆盖 |
| `dbg_*` (调试器) | 未使用 | 不支持（headless 无调试器） |

---

## 十五、长期愿景

### Ramune-ida 不是 IDAPython 的远程代理

第一版的 27 个工具本质上是 IDA API 的结构化封装——`decompile` 对应 `ida_hexrays`，`rename` 对应 `set_name`，`get_bytes` 对应 `ida_bytes`。这是必要的基础设施，但不是终点。

**长期目标：Ramune-ida 是一个 AI-native 的逆向分析平台，提供 IDA 本身不具备的高层语义能力。**

IDA 提供的是"工具"——反编译、交叉引用、字节读取。这些工具要求使用者已经知道自己在找什么。而 AI 驱动的逆向工程需要的是"能力"——给我一个二进制，告诉我它做了什么。

两者的区别：

```
IDA API 层（第一版）             高层能力层（远期）
────────────────────            ────────────────────
decompile(func)                 "这个函数在做什么加密？"
get_bytes(addr, size)           "提取这个算法的所有常量表"
xrefs_to(addr)                  "追踪这个 key 从哪里来"
rename(addr, name)              "根据分析结果批量命名这个模块"
list_funcs()                    "把函数按功能聚类"
```

### 演进路线

#### Phase 2：结构化分析能力

在原子工具之上，构建 **组合性更强、输出更结构化** 的分析工具。这些工具在 MCP Server 侧或 Worker 侧实现复合逻辑，一次调用完成 AI 原本需要 5-10 次工具调用才能拼凑的工作。

| 能力 | 说明 | 与"原子工具组合"的区别 |
|------|------|----------------------|
| **`analyze_function`** | 函数的完整画像：反编译+签名+调用关系+引用字符串+使用常量+栈帧，一次返回 | AI 不需要分 5 次调用再自己拼装 |
| **`decompile` 摘要模式** | `summary=true` 只返回签名、调用列表、字符串引用、控制流概览 | 批量 triage 几百个函数时，token 消耗降低 10x |
| **`diff_before_after`** | 执行修改并立即对比修改前后的反编译变化 | 原子操作无法保证"先快照→改→再反编译→对比"的原子性 |
| **`export_module_context`** | 一次性打包一组函数的完整上下文（反编译+xrefs+字符串+调用图），供 sub-agent 消费 | 手动拼装会漏掉关键上下文 |
| **`analysis_progress`** | 全局进度统计：已命名/已注释/已设类型的函数比例，按 segment 分 | 原本需要 list_funcs 全量拉取再客户端统计 |
| **JSON 结构体定义** | 用 JSON 而非 C 语法定义结构体，Server 侧转换为 C 声明后调用 IDA API | 降低 LLM 构造类型声明的错误率 |

#### Phase 3：智能分析能力

MCP Server 自身具备分析智能，不完全依赖客户端 AI 的推理：

| 能力 | 说明 |
|------|------|
| **`cluster_funcs`** | 基于调用图连通分量 + 地址邻近性 + 字符串特征，自动将函数聚类为功能模块 |
| **`identify_crypto`** | 基于常量表签名（S-box、round constants）自动识别加密算法 |
| **`identify_libraries`** | 封装 FLIRT/Lumina 匹配结果，标记已知库函数，告诉 AI "这些不用分析" |
| **`similar_functions`** | 基于 CFG 哈希或字节签名找到结构相似的函数，支持批量处理同类函数 |
| **`suggest_types`** | 基于调用约定、参数传递模式、已知 API 签名，推测函数参数和返回值类型 |

这些能力的共同点：**它们编码了逆向工程的领域知识**，而不只是暴露底层 API。AI 调用一次 `cluster_funcs` 就能获得一个经验丰富的逆向工程师花 30 分钟才能完成的模块划分。

#### Phase 4：Multi-Agent 协同平台

当 Ramune-ida 同时服务多个 AI Agent 进行协同逆向时，它不只是被动的工具提供者，而是主动的协调基础设施：

| 能力 | 说明 |
|------|------|
| **Agent 身份与会话模型** | 追踪哪个 Agent 做了什么修改 |
| **COW 副本** | 多个 Agent 可以安全地并行分析同一二进制 |
| **Journal 机制** | 基于 IDB netnode 的分析日志：模块划分、任务状态、跨模块提示、置信度 |
| **变更订阅** | MCP notification 推送修改事件，Agent 实时感知其他 Agent 的成果 |
| **乐观并发** | 修改附带版本号，冲突时后者 fail，由 orchestrator 仲裁 |
| **IDB 快照** | `snapshot_create/restore` — 批量修改后发现方向错误时安全回退 |

### 一句话总结

> **第一版做好 IDA 的手和眼（读取 + 修改），后续版本做 IDA 的大脑（理解 + 决策 + 协同）。**

---

## 十六、其他后续改进（不在第一版范围内）

| 方向 | 说明 |
|------|------|
| **路径映射** | 客户端路径 ↔ 服务端路径自动转换 |
| **Docker 支持** | Dockerfile + compose，一键部署 |
| **MCP Resources** | `ida://` 协议的只读数据资源（metadata、segments、types 等） |
| **输出 streaming** | 大输出流式返回，替代截断+下载 |
