# Ramune-ida

> **[开发中] 本项目正在积极开发中，API 和功能可能随时变更。**

Headless IDA Pro MCP Server —— 通过 [Model Context Protocol](https://modelcontextprotocol.io/) 将 IDA Pro 的逆向分析能力暴露给 AI Agent。

[English](README.md)

---

## 这是什么？

Ramune-ida 以 headless 模式运行 IDA Pro (idalib)，并将其封装为 MCP 服务器。Claude、Cursor 等 MCP 兼容客户端可以通过结构化工具调用来反编译函数、重命名符号、设置类型、执行任意 IDAPython。

## 核心设计

**进程分离** —— MCP Server 和 IDA 运行在不同进程中。Server 是纯 async Python；每个 IDA Worker 是单线程子进程，通过专用 fd-pair 管道（JSON line 协议）通信。从架构层面消灭线程安全问题。

**插件架构** —— 工具通过 metadata（描述、参数、tags）和 handler 函数定义。Server 启动时自动发现工具，动态生成 MCP tool 函数并分发调用到 Worker。添加新工具只需写一个 metadata 文件和 handler 实现——无样板注册代码。

**Worker 无状态** —— Worker 是一次性命令执行器。所有管理状态（任务队列、崩溃恢复）集中在 Project 层。Worker 崩溃后 Project 自动重启并重新打开 IDB，对使用者完全透明。

## 架构

```
MCP 客户端 (Claude / Cursor / ...)
    │  Streamable HTTP / SSE
    ▼
┌──────────────────────────────────┐
│  MCP Server (async Python)       │
│  FastMCP + Project 管理          │
│  插件发现 + 动态注册             │
└──────────────┬───────────────────┘
               │  fd-pair pipe (JSON lines)
         ┌─────┼─────┐
         ▼     ▼     ▼
      Worker Worker Worker
      idalib idalib idalib
      (插件 handler)
```

## 工具

Ramune-ida 提供 **26 个工具**（19 个插件工具 + 7 个会话工具），覆盖核心逆向工程工作流：

- **会话**（7）—— 项目生命周期、数据库打开/关闭、异步任务管理
- **分析**（4）—— 反编译、反汇编、交叉引用、二进制概览
- **标注**（3）—— 重命名符号、读写注释
- **数据**（2）—— 自动检测地址类型、读取原始字节
- **列表**（4）—— 枚举函数、字符串、导入、命名地址（支持过滤）
- **搜索**（2）—— 正则搜索（strings/names/disasm）、字节模式搜索
- **类型**（2）—— 设置函数/变量类型、声明 C 类型（struct/enum/typedef）
- **执行**（1）—— 执行任意 IDAPython（stdout/stderr 捕获）
- **撤销**（1）—— IDA 9.0+ 原生 undo

低频和探索性操作通过 `execute_python` 覆盖，它提供完整的 IDAPython 环境访问。

## 特性

- **元数据驱动插件系统** —— 启动时自动发现工具、动态 MCP 注册、外部插件文件夹
- **框架标签系统** —— `kind:read` / `kind:write` / `kind:unsafe`，写入工具自动创建 undo point
- **优雅取消** —— SIGUSR1 + `sys.setprofile` hook → 5 秒看门狗 → SIGKILL 兜底
- **崩溃恢复** —— 自动从 IDA 组件文件恢复、回退到 `.i64`、定期 `.i64` 打包
- **输出截断** —— 超长输出自动截断，HTTP 端点下载完整内容
- **文件上传/下载** —— HTTP 端点传输二进制和 IDB

## 插件

Ramune-ida 通过 `<data-dir>/plugins/`（默认 `~/.ramune-ida/plugins/`）支持外部插件。放入包含 `metadata.py` + `handlers.py` 的插件文件夹并重启，工具自动出现。

详细指南参见[编写插件](docs/writing-plugins_zh.md)，包含 metadata 字段说明、框架标签、handler 约定、安全模型和完整示例。

## 快速开始

### 环境要求

- Python >= 3.10
- IDA Pro 9.0+（含 idalib）
- [uv](https://docs.astral.sh/uv/)（包管理器）

### 安装

```bash
git clone https://github.com/user/Ramune-ida.git
cd Ramune-ida
uv sync
```

### 运行

```bash
# 默认：Streamable HTTP，127.0.0.1:8000
uv run ramune-ida

# 指定地址和端口
uv run ramune-ida http://0.0.0.0:8745

# 使用 IDA 自带的 Python 启动 Worker
uv run ramune-ida --worker-python /opt/ida/python3

# SSE 模式（兼容旧版 MCP 客户端）
uv run ramune-ida sse://127.0.0.1:9000
```

### Docker

需要预先构建 `ida-pro:latest` 基础镜像（含 IDA Pro），参见 [docker-ida](https://github.com/user/docker-ida)。

```bash
# 构建
docker build -t ramune-ida .

# 运行（默认 http://0.0.0.0:8000）
docker run -p 8000:8000 ramune-ida

# 自定义配置
docker run -p 8745:8745 \
  -e TRANSPORT="http://0.0.0.0:8745" \
  -e SOFT_LIMIT=2 \
  -e HARD_LIMIT=4 \
  ramune-ida

# 持久化数据目录（项目 + 插件）
docker run -p 8000:8000 \
  -v /path/to/data:/data/ramune-ida \
  ramune-ida
```

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `TRANSPORT` | `http://0.0.0.0:8000` | 传输协议地址 |
| `SOFT_LIMIT` | `4` | 并发 Worker 建议上限 |
| `HARD_LIMIT` | `8` | 并发 Worker 硬上限 |
| `RAMUNE_DATA_DIR` | `/data/ramune-ida` | 数据目录（项目 + 插件） |

### MCP 客户端配置

Claude Desktop 或 Cursor 中添加：

```json
{
  "mcpServers": {
    "ramune-ida": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### 基本工作流

```
1. open_project()                          → 获取 project_id
2. open_database(project_id, "target.exe") → IDA 分析二进制文件
3. decompile(project_id, "main")           → 反编译 C 代码
4. rename(project_id, addr="main", new_name="entry_main")
5. set_type(project_id, addr="0x401000", type="int foo(char *buf, int len)")
6. execute_python(project_id, code)        → 执行任意 IDAPython 脚本
7. close_database(project_id)              → 保存并关闭
8. close_project(project_id)               → 清理
```

## 目录结构

所有数据存放在统一的数据目录下（默认 `~/.ramune-ida`，可通过 `--data-dir` 或 `RAMUNE_DATA_DIR` 配置）：

| 路径 | 说明 |
|---|---|
| `<data-dir>/projects/` | 项目工作目录（IDB 文件、输出） |
| `<data-dir>/plugins/` | 外部插件目录 |

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `url` | `http://127.0.0.1:8000` | 传输协议地址 |
| `--worker-python` | `python` | Worker 子进程使用的 Python 解释器 |
| `--soft-limit` | `4` | 并发 Worker 建议上限 |
| `--hard-limit` | `8` | 并发 Worker 硬上限（0 = 不限） |
| `--data-dir` | `~/.ramune-ida` | 数据目录（项目 + 插件）（`RAMUNE_DATA_DIR`） |
| `--auto-save-interval` | `300` | 自动保存间隔秒数（0 = 禁用） |
| `--output-max-length` | `50000` | 工具输出截断字符数 |

## 许可证

MIT
