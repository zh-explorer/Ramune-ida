# 编写 Ramune-ida 插件

Ramune-ida 支持通过外部插件添加 IDA 分析工具。插件会被自动发现并注册为 MCP 工具，无需修改源码。

[English](writing-plugins.md)

---

## 插件工作原理

Ramune-ida 采用**元数据驱动的插件架构**。每个工具由两个文件定义：

- `metadata.py` — 声明工具的名称、描述、参数、标签和超时
- `__init__.py` — 按名称导出 handler 函数（实现可以放在任何文件中）

启动时，Server 通过 `--list-plugins` 子进程扫描内置工具包（`core/`）和外部插件目录，收集所有 metadata 并以 JSON 返回。Server 据此动态生成 MCP 工具函数——包含类型签名、描述和参数验证——并注册到 FastMCP。

运行时，当客户端调用插件工具时，Server 将调用封装为 `PluginInvocation` 命令，通过 IPC 管道发送给 Worker。Worker 的 dispatch 层按名称查找 handler 并执行。

```
启动流程：
  Server ──subprocess──▶ Worker --list-plugins
                         │ 扫描 core/ 子包
                         │ 扫描插件文件夹
  Server ◀── JSON metadata ──┤
  │
  register_plugin_tools()
  → 生成带 __signature__ 的 MCP 工具函数

运行时调用：
  MCP 客户端 → Server（插件工具调用）
    → PluginInvocation("plugin:<tool_name>", params)
    → Project.execute() → Worker IPC
    → Worker dispatch → handler 函数
    → dict 结果 → MCP 响应
```

## 快速开始

在 `~/.ramune-ida/plugins/` 下创建一个文件夹：

```
~/.ramune-ida/plugins/
└── my_crypto/
    ├── __init__.py      # 导出 identify_crypto
    └── metadata.py      # TOOLS = [...]
```

### 1. 定义 metadata

```python
# metadata.py
TOOLS = [
    {
        "name": "identify_crypto",
        "description": "Identify cryptographic algorithms by constant signatures (S-box, round constants).",
        "tags": ["crypto", "kind:read"],
        "params": {
            "addr": {
                "type": "string",
                "required": False,
                "description": "Limit scan to a specific function address or name",
            },
        },
        "timeout": 120,
    },
]
```

### 2. 实现并导出

handler 函数必须能通过包名按名称导入。代码怎么组织随你——写在 `__init__.py` 里、拆成多个模块都行：

```python
# __init__.py
from ramune_ida.core import ToolError

def identify_crypto(params):
    import idaapi
    import ida_bytes

    addr = params.get("addr")
    # ... 扫描加密常量 ...

    if not results:
        raise ToolError(-12, "No crypto patterns found")

    return {
        "algorithms": ["AES-128", "SHA-256"],
        "details": [
            {"name": "AES S-box", "addr": "0x4050A0", "confidence": 0.98},
        ],
    }
```

重启服务器，工具会自动出现在 MCP 工具列表中。

---

## Metadata 字段说明

`TOOLS` 列表中的每个条目：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | str | 是 | 工具名，全局唯一 |
| `description` | str | 是 | AI 在 MCP schema 中看到的描述 |
| `params` | dict | 否 | 参数定义（见下方） |
| `tags` | list[str] | 否 | 框架标签 + 自定义标签 |
| `timeout` | int | 否 | 默认超时秒数（默认 30） |
| `handler` | str | 否 | 函数名（不指定则与 name 相同） |

参数定义：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | str | `"string"` | `"string"`, `"integer"`, `"number"`, `"boolean"` |
| `required` | bool | `True` | 是否必填 |
| `default` | any | — | 可选参数的默认值 |
| `description` | str | — | AI 在 MCP schema 中看到的描述 |

## 框架标签（Framework Tags）

标签是 `tags` 列表中的字符串。框架识别带有 `kind:` 前缀的标签并自动应用行为：

| 标签 | 含义 | 框架行为 |
|------|------|----------|
| `kind:read` | 只读操作 | 无副作用 |
| `kind:write` | 修改 IDA 数据库 | 执行前自动创建 undo point |
| `kind:unsafe` | 破坏性或不可逆操作 | 不创建 undo point——工具/AI 自行承担后果 |

写入工具自动获得 undo 支持——如果 AI 犯了错误，`undo` 可以撤销修改。unsafe 工具明确不参与此机制：它们标记无法可靠撤销的操作（如数据库修复、批量破坏性编辑）。AI 在调用 unsafe 工具前应自行创建快照或采取其他保护措施。

自定义标签（如 `"crypto"`、`"analysis"`）原样透传，可用于自己的分类体系。

### 示例

```python
from ramune_ida.worker.tags import TAG_KIND_WRITE

TOOLS = [
    {
        "name": "apply_signature",
        "description": "Apply a FLIRT signature to a function.",
        "tags": ["signatures", TAG_KIND_WRITE],
        "params": { ... },
    },
]
```

也可以直接使用字符串字面量：`"kind:read"`、`"kind:write"`、`"kind:unsafe"`。

## Handler 约定

```python
def tool_name(params: dict[str, Any]) -> dict[str, Any]:
```

- **输入**：`params` dict，字段由 metadata 中 `params` 定义
- **输出**：`dict`，会合并到 MCP 工具返回结果中
- **错误**：抛 `ToolError(code, message)` 返回结构化错误
- **IDA 导入**：在函数体内 import（`--list-plugins` 模式不加载 idalib）
- **取消**：由 dispatch 层通过 `sys.setprofile` 自动处理，handler 无需关心
- **Python 版本**：须兼容 Worker 的 Python（>= 3.10）

### 地址解析

使用 `ramune_ida.core` 中的 `resolve_addr()` 将名称或 hex 字符串转为整数地址：

```python
from ramune_ida.core import resolve_addr, ToolError

def my_tool(params):
    ea = resolve_addr(params["addr"])  # "0x401000"、"main" 或 "12345"
    # ... 使用 ea ...
```

`resolve_addr` 接受 `0x` 十六进制、十进制整数或 IDA 名称。找不到名称时抛出 `ToolError`。

## 内置工具域

Ramune-ida 在 `core/` 下内置了 8 个工具包。它们遵循与外部插件完全相同的 metadata + handler 模式，可作为参考实现。

| 领域 | 包 | 工具 | 说明 |
|------|-----|------|------|
| 分析 | `core/analysis/` | `decompile`, `disasm`, `xrefs`, `survey` | 反编译、反汇编、交叉引用 |
| 标注 | `core/annotate/` | `rename`, `get_comment`, `set_comment` | 符号重命名、注释 |
| 数据 | `core/data/` | `examine`, `get_bytes` | 内存检查 |
| 执行 | `core/execution/` | `execute_python` | 任意 IDAPython 执行 |
| 列表 | `core/listing/` | `list_funcs`, `list_strings`, `list_imports`, `list_names`, `list_types` | 枚举（支持过滤/分页） |
| 搜索 | `core/search/` | `search`, `search_bytes` | 正则和字节模式搜索 |
| 类型 | `core/types/` | `set_type`, `define_type`, `get_type` | 类型查询、标注和声明 |
| 撤销 | `core/undo/` | `undo` | IDA 9.0+ 原生 undo |

添加新的内置工具，只需在对应的领域包中增加 metadata 条目和 handler——或在 `core/` 下新建一个领域包。

## 插件目录

默认路径：`~/.ramune-ida/plugins/`

可通过 `RAMUNE_PLUGIN_DIR` 环境变量或 `--plugin-dir` CLI 选项覆盖。

目录只扫描一层。每个含有 `metadata.py` 的子目录被视为一个插件包。handler 函数必须能从该包中导入（即通过 `__init__.py` 导出）。

## 错误处理

使用 `ToolError` 返回结构化错误：

```python
from ramune_ida.core import ToolError

def my_tool(params):
    addr = params.get("addr")
    if not addr:
        raise ToolError(-4, "Missing required parameter: addr")

    raise ToolError(-12, "Cannot resolve address")
```

其他异常由 dispatch 层捕获，作为内部错误返回（包含完整 traceback）。

## 安全模型

插件运行在 Worker 进程中，拥有完整的 IDA API 访问权限。信任模型很简单：

- **不做沙箱** — IDA 需要完整的系统权限（文件 I/O、内存映射等）
- **进程隔离** — 插件崩溃只会 kill 所在的 Worker，不影响 Server 或其他 Worker。Project 在下一条命令时自动重启 Worker
- **超时保护** — metadata 中的 `timeout` 值由 Project 层强制执行
- **取消支持** — `sys.setprofile` hook 自动安装；长时间运行的 handler 可被 SIGUSR1 → SIGKILL 升级中断
- **输出截断** — Server 层的输出大小限制统一生效

**安装插件 = 信任其代码。** 部署前请审查第三方插件。

## 测试

直接测试 handler，无需启动 MCP 服务器：

```python
def test_identify_crypto():
    from my_crypto.handlers import identify_crypto
    result = identify_crypto({"addr": "0x401000"})
    assert "algorithms" in result
```

完整 MCP 链路的集成测试参考 ramune-ida 仓库中的 `tests/test_mcp_tools.py`，其中演示了如何使用 mock worker 回显插件调用。

## 名称冲突

工具名在所有插件和内置工具中必须全局唯一。发现重名时服务器会中止启动并报错。

建议使用命名空间前缀：`crypto_identify` 而非 `identify`。

## 完整示例：加密算法识别插件

```
~/.ramune-ida/plugins/
└── crypto_id/
    ├── __init__.py      # 导出 crypto_identify, crypto_label
    └── metadata.py
```

**metadata.py**:

```python
TOOLS = [
    {
        "name": "crypto_identify",
        "description": (
            "Scan binary for known cryptographic algorithm signatures. "
            "Checks S-boxes, round constants, and magic numbers against "
            "a built-in database of AES, DES, SHA, MD5, RC4, ChaCha20, etc."
        ),
        "tags": ["crypto", "kind:read"],
        "params": {
            "addr": {
                "type": "string",
                "required": False,
                "description": "Limit scan to a specific function (name or hex address). Scans all segments if omitted.",
            },
            "min_confidence": {
                "type": "number",
                "required": False,
                "default": 0.7,
                "description": "Minimum confidence threshold (0.0 - 1.0)",
            },
        },
        "timeout": 120,
    },
    {
        "name": "crypto_label",
        "description": "Label identified crypto constants with descriptive names and comments.",
        "tags": ["crypto", "kind:write"],
        "params": {
            "addr": {
                "type": "string",
                "required": True,
                "description": "Address of the crypto constant to label",
            },
            "algorithm": {
                "type": "string",
                "required": True,
                "description": "Algorithm name (e.g. 'AES-128', 'SHA-256')",
            },
        },
    },
]
```

**__init__.py**:

```python
from ramune_ida.core import ToolError, resolve_addr

KNOWN_SBOXES = { ... }  # algorithm → byte signature


def crypto_identify(params):
    import ida_bytes
    import idautils

    addr = params.get("addr")
    min_conf = params.get("min_confidence", 0.7)

    if addr:
        ea = resolve_addr(addr)
        segments = [(ea, ea + 0x10000)]
    else:
        segments = [(s.start_ea, s.end_ea) for s in idautils.Segments()]

    results = []
    for start, end in segments:
        for algo, sig in KNOWN_SBOXES.items():
            found = ida_bytes.bin_search(start, end, sig, None, 0, 0)
            if found != 0xFFFFFFFFFFFFFFFF:
                results.append({
                    "algorithm": algo,
                    "addr": hex(found),
                    "confidence": 0.95,
                })

    return {
        "count": len(results),
        "results": [r for r in results if r["confidence"] >= min_conf],
    }


def crypto_label(params):
    import ida_name
    import ida_bytes

    ea = resolve_addr(params["addr"])
    algo = params["algorithm"]

    ida_name.set_name(ea, f"{algo}_constant", ida_name.SN_FORCE)
    ida_bytes.set_cmt(ea, f"Identified as {algo} constant table", True)

    return {"addr": hex(ea), "label": f"{algo}_constant"}
```
