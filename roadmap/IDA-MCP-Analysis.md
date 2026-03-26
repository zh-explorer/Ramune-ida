# IDA Pro MCP 项目分析与改进建议

## 一、项目概述

**ida-pro-mcp** 是一个 [MCP (Model Context Protocol)](https://modelcontextprotocol.io) 服务器，将 IDA Pro 的反汇编/反编译能力暴露给 AI 助手（Claude、Cursor、VS Code 等），实现 **"Vibe Reversing"** — 用自然语言驱动 IDA Pro 进行逆向工程。

---

## 二、目录结构

```
ida-pro-mcp/
├── pyproject.toml              # 项目配置，定义 3 个入口点
├── ida-plugin.json             # IDA 插件描述文件
├── CLAUDE.md                   # Claude Code 的项目上下文指南
├── README.md                   # 文档
├── src/ida_pro_mcp/            # 主包
│   ├── server.py               # MCP Server 入口 (stdio/SSE 代理模式)
│   ├── idalib_server.py        # headless idalib 服务端 (独立进程)
│   ├── idalib_session_manager.py # idalib 多会话管理
│   ├── installer.py            # 安装器逻辑
│   ├── installer_tui.py        # 安装 TUI 界面
│   ├── installer_data.py       # 各 MCP 客户端的配置数据
│   ├── test.py                 # 测试入口 (ida-mcp-test)
│   ├── __main__.py             # python -m 入口
│   └── ida_mcp/                # ★ IDA 插件侧的核心实现
│       ├── __init__.py         # 包初始化，导入所有 api_*.py 模块
│       ├── rpc.py              # MCP Server 实例、@tool/@resource/@unsafe 装饰器、输出限流
│       ├── sync.py             # @idasync - IDA 主线程同步执行 + 超时/取消
│       ├── http.py             # HTTP 请求处理、配置页面、CORS、输出下载
│       ├── utils.py            # TypedDict 定义、地址解析、分页、通用工具函数
│       ├── compat.py           # IDA 版本兼容层
│       ├── framework.py        # 测试框架 (@test 装饰器、断言助手、测试运行器)
│       ├── api_core.py         # 核心 API：函数列表、全局变量、导入导出、字符串、数值转换
│       ├── api_analysis.py     # 分析 API：反编译、反汇编、交叉引用、字节搜索、指令搜索
│       ├── api_memory.py       # 内存 API：读字节/整数/字符串、结构体读取、补丁
│       ├── api_types.py        # 类型 API：类型声明、类型推断、类型应用
│       ├── api_modify.py       # 修改 API：注释、重命名、汇编补丁、定义函数/代码
│       ├── api_stack.py        # 栈帧 API：栈变量操作
│       ├── api_debug.py        # 调试器 API：断点、单步、寄存器、内存读写
│       ├── api_python.py       # Python 执行：在 IDA 上下文中运行任意 Python
│       ├── api_resources.py    # MCP Resources：ida:// 协议的只读数据
│       ├── api_survey.py       # 综合调查 API
│       ├── api_composite.py    # 复合分析 API (analyze_function, analyze_component, diff_before_after, trace_data_flow)
│       ├── zeromcp/            # ★ 自实现的轻量 MCP 协议库
│       │   ├── mcp.py          # McpServer - HTTP/SSE/stdio 传输 + JSON-RPC 分发
│       │   └── jsonrpc.py      # JSON-RPC 2.0 实现
│       └── tests/              # 测试用例 (test_api_*.py)
├── tests/                      # 测试用二进制文件
│   ├── crackme03.elf
│   ├── typed_fixture.elf
│   └── ...
├── skills/                     # Claude Code skills
└── devdocs/                    # 开发文档
```

---

## 三、架构设计

整体采用 **两层代理架构**：

```
MCP 客户端 (Claude/Cursor/...)
     ↕ stdio 或 HTTP
server.py (外部 MCP Server 进程)
     ↕ HTTP JSON-RPC (POST /mcp)
ida_mcp/ (IDA 插件侧，运行在 IDA Pro 内部)
     ↕ IDA SDK
IDA Pro 数据库 (IDB)
```

### 关键流程

1. **`server.py`** 启动一个 MCP Server（支持 stdio/SSE/Streamable HTTP），但它 **不直接处理业务逻辑**。它通过 `dispatch_proxy` 将所有非 `initialize` 的 JSON-RPC 请求转发到 IDA Pro 内部运行的 HTTP 服务（默认 `127.0.0.1:13337`）。

2. **`ida_mcp/`** 作为 IDA 插件加载，在 IDA 内部启动一个 HTTP 服务。所有 API 函数通过 `@tool` 装饰器自动注册为 MCP 工具。

3. **`@idasync`** 装饰器确保所有 IDA SDK 调用都在 IDA 主线程上执行（通过 `idaapi.execute_sync`），并支持超时和取消。

4. **`zeromcp/`** 是一个 **自己实现的轻量 MCP 协议库**（零依赖），支持 JSON-RPC 2.0、HTTP/SSE/stdio 传输、工具自动参数提取（从 type hints 生成 JSON Schema）。

### 另一种模式：idalib headless

**`idalib_server.py`** 提供无 GUI 的 headless 模式，直接用 idalib 打开二进制文件，支持多会话管理（`--isolated-contexts`），适合自动化场景。

---

## 四、实现的功能（71 个工具 + 24 个资源）

### 核心查询 (`api_core.py`)
- `lookup_funcs` / `list_funcs` / `list_globals` — 函数和全局变量查找
- `imports` — 导入表分页浏览
- `int_convert` — 数值格式转换（十六进制、字节、ASCII、二进制）

### 分析 (`api_analysis.py`)
- `decompile` / `disasm` — 反编译和反汇编
- `xrefs_to` / `xrefs_to_field` / `callees` — 交叉引用
- `basic_blocks` / `callgraph` — 基本块和调用图
- `find_regex` / `find_bytes` / `find_insns` / `find` — 多种搜索

### 内存读取 (`api_memory.py`)
- `get_bytes` / `get_int` / `get_string` / `get_global_value` — 读取原始数据
- `read_struct` / `search_structs` — 结构体操作
- `patch` / `put_int` — 写入/补丁

### 类型系统 (`api_types.py`)
- `set_type` / `declare_type` / `infer_types` — 类型声明和推断
- `export_funcs` — 函数导出（JSON/C 头文件/原型）

### 修改 (`api_modify.py`)
- `set_comments` / `rename` / `patch_asm` — 注释、重命名、汇编补丁
- `define_func` / `define_code` / `undefine` — 定义/取消定义

### 复合分析 (`api_composite.py`)
- `analyze_function` — 单函数紧凑分析（反编译+xrefs+strings+callees，一次调用替代多个工具）
- `analyze_component` — 多函数组件分析（内部调用图、共享全局变量、接口/内部分类）
- `diff_before_after` — 执行修改并立即对比修改前后的反编译结果
- `trace_data_flow` — 沿交叉引用追踪数据流（前向/后向，多跳）

### 栈帧 (`api_stack.py`)
- `stack_frame` / `declare_stack` / `delete_stack`

### 调试器 (`api_debug.py`，扩展功能，需 `?ext=dbg`)
- 断点管理、单步执行、寄存器读取、内存读写

### Python 执行 (`api_python.py`)
- `py_eval` — 在 IDA 上下文执行任意 Python 代码

### MCP Resources (`api_resources.py`，`ida://` 协议)
- `ida://idb/metadata` / `ida://idb/segments` / `ida://idb/entrypoints`
- `ida://cursor` / `ida://selection`（UI 状态）
- `ida://types` / `ida://structs` / `ida://struct/{name}`
- `ida://import/{name}` / `ida://export/{name}` / `ida://xrefs/from/{addr}`

---

## 五、设计亮点

1. **零样板代码添加新功能**：只需在 `api_*.py` 里加一个 `@tool` + `@idasync` 函数，MCP 工具就自动注册，参数 schema 从 type hints 自动生成。

2. **Batch-first 设计**：大多数 API 同时支持单个和批量输入，返回统一的 `[{..., error: null|string}]` 格式。

3. **输出限流**：超过 50KB 的输出自动截断并缓存，提供下载 URL，防止 token 溢出。

4. **线程安全**：通过 `@idasync` 保证所有 IDA SDK 调用在主线程执行，支持超时和请求取消。

5. **安全防护**：unsafe 操作需显式标记，CORS 策略可配置，Web 配置页面有 CSRF/DNS Rebinding/Clickjacking 防护。

6. **自实现 MCP 库 (zeromcp)**：零外部依赖，便于在 IDA 的 Python 环境中直接加载。

---

## 六、总体评价

**优点：**
- 71 个工具覆盖了逆向工程的绝大部分操作
- batch-first 设计对 AI 很友好（减少往返次数）
- `analyze_function` 一次性获取函数的反编译、xrefs、callees、strings、常量，token 效率高
- `analyze_component` 已经支持函数组的组件级分析（内部调用图、共享全局变量）
- `diff_before_after` 已经实现了修改前后对比（支持 rename/set_type/set_comment）
- `trace_data_flow` 已经实现了多跳数据流追踪
- 输出限流 50KB + 下载机制，防止 context 爆炸
- `py_eval` 作为兜底，AI 可以执行任意 IDA Python，理论上能做任何事

**做源码还原足够用**，但在 AI 驱动的高效源码还原场景下，有以下维度可以改进。

---

## 七、改进建议

> **注**：经过代码审查，`api_composite.py` 中已经实现了 `diff_before_after`（修改前后对比）和 `analyze_component`（组件级分析），说明作者也在往 AI 辅助逆向的方向演进。以下建议聚焦在尚未覆盖的部分。

### 1. 缺少分析进度追踪（优先级：最高）

这是最大的缺口。源码还原是一个 **渐进式** 过程，AI 需要知道：
- 哪些函数已经分析/重命名了，哪些还没有
- 当前还原的整体覆盖率是多少

现在 AI 只能反复调用 `list_funcs` 然后自己判断哪些 `sub_xxx` 还没改名。对于几百个函数的二进制，这很低效。

**建议增加：**
```python
@tool
@idasync
def analysis_progress() -> dict:
    """返回分析进度统计"""
    # 已命名函数 vs sub_xxx 函数比例
    # 已注释函数比例
    # 已设置类型的函数比例
    # 按 segment 分组的覆盖率
```

### 2. 函数分类/聚类能力（优先级：高）

`analyze_component` 可以分析一组给定的函数，但前提是你得先知道哪些函数该分到一组。缺少一个自动聚类工具。

**建议增加：**
```python
@tool
@idasync
def cluster_funcs() -> list[dict]:
    """基于调用图和地址邻近性，将函数自动聚类分组"""
    # 按 segment + 调用图连通分量分组
    # 标注每组的字符串特征（推测模块功能）
    # 标注每组的库函数占比
```

### 3. 大函数的摘要模式（优先级：中）

`analyze_function` 的反编译上限是 100 行，但对于初步扫描来说仍然太多。

**建议增加 `decompile` 的 `summary=True` 模式：**
```python
# summary 模式只返回：
# - 函数签名
# - 调用的函数列表
# - 使用的字符串/常量
# - 主要控制流结构（if/switch/loop 数量）
# - 行数
```

### 4. 缺少 "undo" / 快照能力（优先级：中）

`diff_before_after` 可以在修改时看到对比，但如果 AI 批量修改了多个函数后发现方向错了，没有办法回退。

**建议增加：**
```python
@tool
@idasync
def snapshot_create(name: str) -> dict:
    """创建 IDB 快照"""

@tool
@idasync
def snapshot_restore(name: str) -> dict:
    """恢复到快照"""
```

### 5. 其他小改进

| 改进点 | 说明 |
|--------|------|
| 相似函数检测 | 基于 CFG 哈希或 bytes 签名找结构相似的函数，批量处理同类函数 |
| 自动识别已知库 | 封装 FLIRT/Lumina 的匹配结果，标记哪些函数是已知库代码不需要分析 |
| `set_type` 的错误反馈 | 当前类型设置失败的错误信息不够清晰，AI 经常猜错 C 类型语法 |

---

## 八、Multi-Agent 逆向架构

### 核心思路

模拟人类逆向工程师的工作流：先根据经验将程序分块、还原符号、猜测用途，然后基于已有结果整体修正偏差，如此循环往复。用一个 orchestrator agent 做全局调度，多个 sub-agent 分模块并行分析。

### 核心矛盾与解法

IDA 的 IDB 是 **共享可变状态**，且只能在主线程串行修改（`@idasync`）。因此关键是把 **"读+推理"** 和 **"写"** 分离：

- **读 + 推理**：可以并行。每个 sub-agent 拿到一份数据去独立分析推理
- **写（修改 IDB）**：必须串行。由 orchestrator 统一审核并应用

这恰好和人类团队逆向一样 — 大家各自看各自的模块，最后汇总到同一个 IDB 里。

### 架构总览

```
┌──────────────────────────────────────────────────────┐
│                 Orchestrator Agent                     │
│  (全局视野：所有模块、进度、依赖关系)                  │
│                                                       │
│  1. Survey:   调 MCP 收集全局信息                     │
│  2. Plan:     划分模块，分配任务                       │
│  3. Dispatch: 并行派发 sub-agent                      │
│  4. Merge:    审核结果，冲突解决，批量写入 IDB         │
│  5. Evaluate: 重新反编译验证，决定是否继续             │
│  └─→ 回到 2，带上新的上下文                           │
└───────────┬──────────┬──────────┬────────────────────┘
            │          │          │
      ┌─────▼──┐ ┌─────▼──┐ ┌────▼───┐
      │ Agent A│ │ Agent B│ │ Agent C│
      │ 网络模块│ │ 加密模块│ │ UI模块  │
      └────────┘ └────────┘ └────────┘
      各自独立推理，输出结构化建议
      (不直接修改 IDB)
```

### Phase 1: Survey（侦察）

Orchestrator 调 MCP 收集全局信息：

```python
# orchestrator 执行
imports = mcp.imports()                  # 导入表 → 判断用了哪些库
strings = mcp.find_regex(".*")           # 所有字符串 → 关键线索
callgraph = mcp.callgraph(entries)       # 从入口点展开调用图
funcs = mcp.list_funcs()                 # 所有函数列表
segments = resource("ida://idb/segments")
```

基于这些信息，orchestrator 做初步判断：
- 调用了 `send/recv/socket` → 存在网络模块
- 字符串里有 `AES/key/encrypt` → 存在加密模块
- 调用了 `CreateWindow/MessageBox` → 存在 UI 模块
- 按调用图连通分量 + 地址邻近性聚类

### Phase 2: 派发 Sub-agent

每个 sub-agent 收到一个 **任务包**（由 orchestrator 调 MCP 读取后整理）：

```python
task = {
    "module_name": "network",
    "hypothesis": "这组函数负责 C2 通信，基于 HTTP",
    "functions": ["sub_401000", "sub_401200", ...],
    "relevant_imports": ["send", "recv", "WSAStartup"],
    "relevant_strings": ["POST /api/beacon", "User-Agent: ..."],
    "cross_module_refs": {
        "sub_401000": {"callers": ["sub_405000"], "callees": ["sub_402000"]},
    },
    # ★ 关键：给每个函数附上当前反编译结果
    "decompilations": {
        "sub_401000": "int __cdecl sub_401000(int a1, ...) { ... }",
        ...
    },
}
```

Sub-agent **不直接调 MCP 修改 IDB**，而是输出结构化的 **建议**：

```python
result = {
    "module_name": "network",
    "confidence": 0.85,
    "summary": "C2 通信模块，使用 HTTP POST 发送 beacon，AES-CBC 加密 payload",
    "renames": [
        {"addr": "0x401000", "old": "sub_401000", "new": "c2_send_beacon", "reason": "..."},
        {"addr": "0x401200", "old": "sub_401200", "new": "c2_parse_response", "reason": "..."},
    ],
    "type_changes": [
        {"addr": "0x401000", "type": "int __cdecl c2_send_beacon(C2_CTX *ctx, void *data, int len)"},
    ],
    "struct_proposals": [
        {"name": "C2_CTX", "decl": "struct C2_CTX { SOCKET sock; char *host; int port; AES_KEY key; };"},
    ],
    "comments": [
        {"addr": "0x401050", "comment": "XOR key 解密 C2 地址"},
    ],
    "unresolved": [
        "sub_401500 被本模块调用但功能不明确，可能是加密模块的接口",
    ],
    "cross_module_hints": [
        {"func": "sub_402000", "hint": "疑似 AES 加密函数，加密模块 agent 应重点分析"},
    ],
}
```

### Phase 3: Merge（合并）

Orchestrator 收集所有 sub-agent 结果：

```python
# 1. 冲突检测
#    - Agent A 说 sub_402000 是 "aes_encrypt"
#    - Agent B 说 sub_402000 是 "encrypt_payload"
#    → orchestrator 选置信度更高的，或合并为 "aes_encrypt_payload"

# 2. 依赖排序
#    - 先声明 struct（被其他类型依赖）
#    - 再设类型（依赖 struct）
#    - 最后重命名

# 3. 批量应用到 IDB
mcp.declare_type(all_structs)
mcp.set_type(all_type_changes)
mcp.rename(all_renames)
mcp.set_comments(all_comments)

# 4. 验证：重新反编译关键函数，检查质量
for func in key_functions:
    new_code = mcp.decompile(func)
    # 或者使用已有的 diff_before_after
```

### Phase 4: Evaluate & Iterate（评估与迭代）

```python
# 评估当前进度
progress = mcp.analysis_progress()

# 基于新信息重新规划
# - 有些 unresolved 函数现在有了新的上下文
# - cross_module_hints 指向了新的分析方向
# - 某些模块的反编译质量在应用类型后大幅改善，可以做更深入分析

# 进入下一轮迭代...
```

### 实现路径

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| **A: Claude Code Agent tool** | 主对话作 orchestrator，用内置 Agent tool 起 sub-agent | 零额外开发，立刻可用 | sub-agent 共享 MCP 连接串行读取；context 隔离靠 prompt 约束 |
| **B: Claude Agent SDK** | 用 Anthropic Agent SDK 写专用逆向编排器 | 完全控制工作流、token 预算、并发 | 需要开发工作 |
| **C: MCP 服务端内置** | 在 ida-pro-mcp 里实现 `orchestrated_analysis` 工具 | 对客户端透明，任何 MCP 客户端可用 | 在 MCP server 里调 LLM API，架构别扭 |

**建议：先用方案 A 验证思路**，等流程跑通后再考虑方案 B 做精细控制。

---

## 九、Agent 间数据共享策略

### 核心洞察：IDB 本身就是天然的共享黑板

这是最关键的认识。当 Agent A 做了以下操作：

```python
mcp.rename({"func": [{"addr": "0x401000", "name": "c2_send_beacon"}]})
mcp.set_type([{"addr": "0x401000", "type": "int c2_send_beacon(C2_CTX *ctx, void *data, int len)"}])
mcp.set_comments([{"addr": "0x401050", "comment": "XOR 解密 C2 地址"}])
```

之后，Agent B 调用 `decompile("sub_405000")`（一个调用了 `0x401000` 的函数），它看到的反编译结果 **自动** 变成了：

```c
int result = c2_send_beacon(ctx, payload, payload_len);  // 而不是 sub_401000(a1, a2, a3)
```

Agent A 的所有成果 — 函数名、类型签名、注释 — **零成本** 传播到了 Agent B 的视野中。不需要任何额外的同步机制。

### 为什么 IDB 是最佳的主共享层

| 特性 | IDB comments/names/types | 外部文件 |
|------|-------------------------|----------|
| 地址绑定 | 天然的，数据就在对应地址上 | 需要额外映射，地址变化时可能失效 |
| 自动传播 | `decompile` 自动包含所有已知信息 | 需要 agent 主动读取 |
| 额外 I/O | 零（已包含在正常 MCP 调用中） | 需要额外读写操作 |
| IDA UI 可见 | 是（人类也能直接看到） | 否 |
| 结构化程度 | 低（字符串形式） | 高（JSON 等） |
| 持久化 | 随 IDB 保存/加载 | 需要额外管理 |

### 哪些数据适合放在 IDB 中

**Tier 1：直接写入 IDB（通过现有 MCP 工具）**

这些就是逆向分析的 **成果本身**，天然属于 IDB：

| 数据类型 | IDB 存储方式 | MCP 工具 | 自动传播到 decompile |
|----------|-------------|----------|---------------------|
| 函数名 | `set_name` | `rename` | 是 |
| 变量名 | Hex-Rays 局部变量名 | `rename` (local) | 是 |
| 函数原型 | `apply_tinfo` | `set_type` | 是 |
| 结构体定义 | local type library | `declare_type` | 是 |
| 地址注释 | `set_cmt` | `set_comments` | 是 |
| 反编译器注释 | Hex-Rays 注释 | `set_comments` | 是 |

**关键原则：保持注释干净、人类可读。** 注释应该是分析结论，不是 JSON 元数据。

```
✅ 好的注释：XOR 解密 C2 服务器地址，key = 0x5A
❌ 坏的注释：{"agent": "network_agent", "confidence": 0.85, "finding": "XOR decrypt"}
```

### 哪些数据不适合放在 IDB 注释中

有些 **协调信息** 不属于逆向结果，不应该出现在 IDB 注释里：

- **模块划分**："sub_401000 ~ sub_401F00 属于网络模块"
- **任务分配**："加密模块已由 Agent B 分析完毕"
- **置信度**："Agent A 对 c2_send_beacon 这个命名 85% 确定"
- **跨模块提示**："sub_402000 可能是加密模块的接口"
- **分析历史**："第一轮将 sub_401000 命名为 send_data，第二轮修正为 c2_send_beacon"

### 推荐方案：IDB 主体 + netnode 日志

IDA 的 **netnode** 机制可以在 IDB 中存储任意 key-value 数据，对 IDA UI 不可见。项目已有 `config_json_get/set` 基础设施（见 `http.py`）。

```
┌─────────────────────────────────────────────────────┐
│                      IDB 文件                        │
│                                                      │
│  ┌─ 人类可见层 ──────────────────────────────────┐   │
│  │  函数名、变量名、类型、注释                    │   │
│  │  → 通过 decompile/disasm 自动传播给所有 agent  │   │
│  └────────────────────────────────────────────────┘   │
│                                                      │
│  ┌─ 机器可见层 (netnodes) ────────────────────────┐  │
│  │  分析日志 (analysis journal)                    │  │
│  │  → 模块划分、任务状态、置信度、跨模块提示      │  │
│  │  → 通过专用 MCP 工具 journal_read/write 访问   │  │
│  └────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### 需要新增的 MCP 工具

```python
@tool
@idasync
def journal_write(entries: list[JournalEntry]) -> list[dict]:
    """写入分析日志条目到 IDB netnode"""
    # JournalEntry = {
    #     "module": "network",           # 模块名
    #     "agent": "agent_a",            # 来源 agent
    #     "type": "finding|assignment|hint|correction",
    #     "content": "...",              # 结构化内容
    #     "functions": ["0x401000"],     # 关联函数
    #     "confidence": 0.85,            # 可选
    # }
    # 存入 netnode: $ ida_mcp.journal

@tool
@idasync
def journal_read(
    module: str | None = None,
    type: str | None = None,
) -> list[dict]:
    """读取分析日志，可按模块或类型过滤"""

@tool
@idasync
def journal_clear(module: str | None = None) -> dict:
    """清除日志（全部或按模块）"""
```

#### 典型使用流程

```
第一轮:
  Orchestrator → journal_write: module="network", type="assignment",
                                content="Agent A 负责分析网络模块"
  Agent A 分析完 → Orchestrator 应用结果到 IDB (rename/set_type/set_comments)
                 → journal_write: module="network", type="finding",
                                  content="C2 通信模块，HTTP POST + AES"
                 → journal_write: type="hint",
                                  content="sub_402000 疑似 AES，加密 agent 应重点看"
第二轮:
  Orchestrator → journal_read() 获取所有日志
               → 看到 hint，将 sub_402000 加入 Agent B 的任务
  Agent B 分析 sub_402000 → 确认是 AES-128-CBC
  Orchestrator → 应用结果
               → journal_write: type="correction",
                                content="确认 sub_402000 = aes_128_cbc_encrypt"
```

### 为什么不用纯外部文件

| 考量 | netnode（IDB 内） | 外部 .analysis.json |
|------|-------------------|---------------------|
| 与 IDB 一体 | 是，保存/加载自动同步 | 否，需要额外管理，可能遗漏 |
| 利用现有基础设施 | 是，`config_json_get/set` 已就绪 | 否，需要新建文件 I/O |
| IDB 发给别人 | 日志随 IDB 一起走 | 容易忘记附带 |
| 可调试性 | 低（需要 IDA 查看 netnode） | 高（直接看 JSON 文件） |
| 大小限制 | netnode 单 blob 上限 ~1GB | 无限制 |

**结论：优先用 netnode**。如果需要人工检查日志，可以加一个 `journal_export()` 工具导出为 JSON 文件。

### 数据流总结

```
Agent A (网络模块分析)
  │
  │ 输出结构化建议 (renames, types, comments, findings)
  │
  ▼
Orchestrator
  │
  ├─→ mcp.rename / set_type / set_comments  →  IDB 人类可见层
  │                                               │
  │                                               │ (自动传播)
  │                                               ▼
  │                                         Agent B 调 decompile()
  │                                         自动看到 Agent A 的成果
  │
  └─→ mcp.journal_write(findings, hints)   →  IDB netnode 层
                                               │
                                               │ (按需读取)
                                               ▼
                                         Orchestrator 下轮调 journal_read()
                                         获取所有模块的分析状态和跨模块提示
```

---

## 十、答案生成阶段：直接调用 vs Sub-agent

### 场景描述

分析阶段基本完成后，更高层的决策者需要一个具体的"答案" — 例如某个加密算法的等效 Python 实现、漏洞利用方案、或协议解析脚本。这个阶段的工作模式和分析阶段有本质区别。

### 三种场景与对应策略

#### 场景 A：直接查 IDB 就能回答

> "加密函数的 S-box 是什么？"

Orchestrator 直接调 `get_bytes("0x404000", 256)` 就完事了。不需要 sub-agent。

**特征**：答案就在数据里，不需要推理。

#### 场景 B：需要深度推理 + 迭代验证

> "把这个自定义加密算法用 Python 等效实现"

这是典型需要 **sub-agent** 的场景。原因：

1. **Context 干净**：Orchestrator 此时的 context 已经塞满了模块划分、多轮日志、冲突解决等协调信息。而 sub-agent 可以把全部 context 集中在那几个加密函数上。

2. **迭代性强**：写 Python → 发现不理解某个常量 → 回 IDB 查 `get_bytes` → 修正实现 → 再验证。这种紧密的 "写码 ↔ 查 IDB" 循环，放在一个专注的 agent 里效率最高。

3. **IDB 已经被充分标注**：这是关键。经过分析阶段，函数名、类型、注释都已经写入 IDB 了。Sub-agent 调 `decompile` 看到的是 `aes_128_cbc_encrypt(ctx, plaintext, len)` 而不是 `sub_402000(a1, a2, a3)`。**前面所有 agent 的成果已经沉淀在 IDB 里了**，sub-agent 不需要分析历史就能理解代码。

**特征**：需要持续推理 + 反复查 IDB + 代码生成。

#### 场景 C：需要跨模块综合判断

> "这个样本的完整攻击链是什么？从入侵到持久化到数据窃取，写一份分析报告"

Orchestrator 自己来更合适，因为它有全局视野 — 知道哪些模块做什么、模块间怎么协作。如果 context 不够了，可以起一个 sub-agent 但把 journal 全量喂给它。

**特征**：需要全局知识，跨越多个模块的综合判断。

### 决策框架

不应该硬编码策略，而是给 agent 一个 **启发式决策树**：

```
收到 "求解/实现" 类请求
│
├─ 只需要查数据？（读 S-box、读常量、看函数签名）
│  → 直接调 MCP，orchestrator 回答
│
├─ 需要深度分析单个模块？（等效实现、漏洞利用、协议解析）
│  → 起 sub-agent，给它：
│     1. journal 中该模块的摘要
│     2. 相关函数列表
│     3. MCP 只读访问权
│     4. 明确的交付物定义（"输出可运行的 Python 脚本"）
│
├─ 需要跨模块综合？（攻击链报告、整体架构文档）
│  → orchestrator 自己写（它有全局日志）
│  → 或起 sub-agent，但把 journal 全量 + 各模块摘要喂给它
│
└─ 不确定？
   → 先让 orchestrator 评估复杂度
   → 如果预估需要 >5 次 MCP 调用 + 代码生成 → sub-agent
   → 否则直接处理
```

### 关键设计原则：Sub-agent 应有只读 MCP 访问权

生成等效实现时，agent 经常需要反复回去查细节：

```
"这个循环跑几次？"         → decompile 看循环边界
"a3 到底是什么类型？"      → 看 callers 的传参
"这个常量表有多大？"       → get_bytes
"解密后的结果应该是什么？"  → 用 debugger 跑一下对比
```

这些查询 **无法预先穷举**。给 sub-agent MCP 读取权，让它自己按需查。

但 **不给写权限**，因为：

- 分析阶段已经结束，IDB 不该再被随意修改
- 避免 sub-agent 不小心改坏了其他 agent 的成果
- 如果确实需要修改（比如要补个漏掉的类型），sub-agent 返回建议，由 orchestrator 决定是否应用

### 答案生成阶段的数据流

```
Orchestrator
  │
  │ 收到 "实现加密算法的 Python 版本" 请求
  │
  ├─ 评估：需要深度分析 crypto 模块 → 起 sub-agent
  │
  │ 构造任务包：
  │  {
  │    question: "实现 aes_custom_encrypt 的等效 Python",
  │    module_summary: journal_read(module="crypto"),
  │    key_functions: ["0x402000", "0x402200", "0x402500"],
  │    permissions: "read-only MCP access",
  │    deliverable: "可运行的 Python 脚本 + 测试向量验证",
  │  }
  │
  ▼
Sub-agent (crypto solver)
  │
  │ 1. decompile("0x402000")  → 看到已标注的 aes_custom_encrypt
  │ 2. get_bytes("0x404000", 256) → 读取 S-box
  │ 3. 写 Python 实现
  │ 4. decompile("0x402200")  → 看 key schedule 细节
  │ 5. 修正实现
  │ 6. get_bytes("0x405000", 32) → 读测试向量
  │ 7. 验证 Python 输出 == IDB 中的已知结果
  │
  ▼
返回给 Orchestrator：
  {
    solution: "encrypt.py 源码",
    test_vectors: [...],
    verified: true,
    notes: "自定义 S-box，标准 AES 流程但 MixColumns 步骤被替换",
    idb_suggestions: [  // 可选：建议修改 IDB
      {"addr": "0x402100", "comment": "自定义 MixColumns 替代实现"},
    ],
  }
```

---

## 十一、改进优先级总结

针对 AI 驱动源码还原 + multi-agent 场景，建议按以下优先级实施：

### 第一阶段：使能 multi-agent（最小可行）

1. **`analysis_progress()`** — 全局进度统计（已命名/已注释/已设类型的比例）
2. **`cluster_funcs()`** — 自动将函数按调用图聚类为模块
3. **`journal_write/read/clear()`** — 基于 netnode 的分析日志

这三个工具加上已有的 `analyze_component` + `diff_before_after`，就足够支撑一个基本的 multi-agent 工作流。

### 第二阶段：提升效率

4. **函数摘要模式** — `decompile(summary=True)` 快速 triage
5. **`snapshot_create/restore()`** — IDB 快照用于安全回退
6. **`export_module_context()`** — 一次性打包一组函数的完整上下文给 sub-agent

### 第三阶段：高级能力

7. **相似函数检测** — 批量处理同类函数
8. **FLIRT/Lumina 集成** — 自动标记已知库函数
9. **Prompt 策略 resource** — `ida://analysis/strategy` 自动推送分析方法论
