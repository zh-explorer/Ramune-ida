# IDA Pro MCP 使用体验报告

> **使用者**: Claude Opus 4.6 (Anthropic LLM)
> **使用场景**: Enigma Protector v1.31 + Enigma Virtual Box 加壳程序逆向分析
> **使用周期**: 多轮对话，累计分析 5+ 个二进制文件
> **日期**: 2026-03-25

---

## 一、项目背景

本次逆向分析的目标是一个多层加壳的 CS 游戏外挂程序，保护层级结构如下：

```
Layer 0: 原始 PE（Enigma Protector v1.31 加壳）
Layer 1: Enigma JIT VM（26 个函数，45K 操作码）
Layer 2: Enigma CISC VM（41 个操作码，270 个 unique 函数）
Layer 3: Enigma Virtual Box（LOADERX64.dll，42 个 API hook）
Layer 4: 实际载荷（NCNN 模型 + D3D11/Vulkan hook）
```

整个分析过程高度依赖 ida-pro-mcp 进行远程反编译和二进制数据提取。以下是基于实际使用的经验总结。

---

## 二、工具使用频率统计

### 2.1 高频工具（每次分析必用）

| 工具 | 典型用途 | 单次项目调用量 |
|------|----------|---------------|
| `decompile` | 函数反编译，核心分析手段 | 200+ 次 |
| `get_bytes` | 读取原始字节，密码学分析 | 100+ 次 |
| `xrefs_to` | 追踪交叉引用，理解调用链 | 80+ 次 |
| `rename` | 给函数/变量命名 | 120+ 次 |
| `find_bytes` | 搜索字节模式 | 50+ 次 |
| `list_funcs` / `lookup_funcs` | 定位和搜索函数 | 60+ 次 |

### 2.2 中频工具（按需使用）

| 工具 | 典型用途 |
|------|----------|
| `imports` / `imports_query` | 导入表分析，判断二进制功能 |
| `survey_binary` | 新二进制初始概览 |
| `disasm` | 验证反编译准确性，看原始汇编 |
| `set_comments` / `append_comments` | 标注分析结论 |
| `idalib_open` / `idalib_switch` | 多 session 管理 |
| `callees` / `callgraph` | 函数调用关系分析 |
| `get_string` | 读取字符串数据 |
| `stack_frame` | 查看局部变量布局 |

### 2.3 低频工具（很少使用或未成功使用）

| 工具 | 原因 |
|------|------|
| `declare_type` / `type_apply_batch` | 参数格式复杂，LLM 不易构造 |
| `infer_types` | 自动推断结果不明确 |
| `trace_data_flow` | 输出过于庞大，不如手动追踪 |
| `analyze_batch` / `analyze_component` | 功能定位不清，与 decompile 重叠 |
| `patch` / `patch_asm` | 本项目以静态分析为主，少有 patch 需求 |
| `enum_upsert` | 未找到合适使用场景 |
| `read_struct` | 结构体未定义，此工具无用武之地 |

### 2.4 未使用的工具

| 工具 | 备注 |
|------|------|
| `define_code` / `undefine` | 数据区转代码，本项目未涉及 |
| `define_func` | IDA 自动识别已足够 |
| `delete_stack` | 无需修改栈帧 |
| `put_int` | 无需修改二进制中的整数值 |
| `xrefs_to_field` | 结构体字段引用，前提是有结构体定义 |

---

## 三、优点分析

### 3.1 远程反编译 + 多 Session 并行（杀手级能力）

这是 ida-pro-mcp 最核心的价值。作为 LLM，我无法运行本地 GUI，但通过 MCP 协议可以获得完整的 Hex-Rays 反编译能力。

多 session 支持在本项目中是刚需。分析 Enigma 的 4 层嵌套结构时，我需要：

- Session 1: 主程序（1.1GB，14000+ 函数）
- Session 2: LOADERX64.dll（提取的 EVB 加载器）
- Session 3: dump 出来的脱壳 PE

`idalib_open` → `idalib_switch` 的流程顺畅，session 之间切换无感知延迟。

### 3.2 反编译 + 重命名 + 注释的正向循环

```
decompile(func) → 理解逻辑 → rename(sub_xxx, "RC4_decrypt") → decompile(caller)
                                                                    ↓
                                         caller 中出现 RC4_decrypt() 而非 sub_xxx()
                                                                    ↓
                                              caller 的逻辑更容易理解 → 继续命名
```

这个循环在分析 LOADERX64.dll 时效果显著。从 120+ 个 `sub_` 函数开始，最终命名出完整的函数表：

```
sub_110001000 → RC4_init
sub_110001060 → RC4_crypt
sub_110002000 → aPLib_decompress
sub_110003000 → hook_NtCreateFile
sub_110003200 → hook_NtReadFile
...（共 120+ 个命名）
```

每次 rename 后，所有引用该函数的 caller 的反编译结果都会自动更新，可读性逐步提升。

### 3.3 `get_bytes` + `find_bytes`：密码学分析的命脉

本项目涉及大量密码学逆向：

- **IDEA-CBC**: 通过 `get_bytes` 提取 key schedule 常量表，确认 IDEA 算法
- **XOR 编码**: 用 `find_bytes` 搜索已知明文的 XOR 编码形式，定位 key = 0xEC
- **RC4**: 通过 `get_bytes` 读取 S-box 初始化过程中的内存布局
- **C0DEC0DE 标记**: `find_bytes("C0DEC0DE")` 定位 Enigma 的 9 个 patch 点
- **VM 操作码表**: `get_bytes` 读取 45000 字节的 JIT VM 操作码流

`get_bytes` 返回的 hex dump 可以直接在 Python 中进一步处理，与外部脚本的衔接非常顺滑。

### 3.4 `survey_binary` 信息密度高

一次调用获得：

- 文件类型、架构、位宽
- Section 列表（名称、大小、权限）
- Entry point
- 导入/导出统计
- 函数数量

对于新打开的二进制，这是最高效的起点。

### 3.5 `xrefs_to` 支撑了关键的逆向突破

多个关键发现都依赖交叉引用追踪：

- 追踪 IDEA key 的来源：`xrefs_to(key_addr)` → 找到 key 被写入的位置 → 追溯到 EVB config block
- 追踪 hook 安装：`xrefs_to(NtCreateFile_IAT)` → 找到 hook installer → 理解完整的 hook 链
- 追踪 VM dispatch：`xrefs_to(handler_table)` → 找到所有 opcode handler 的注册点

---

## 四、痛点与不足

### 4.1 大函数反编译是最大的痛点

**问题描述**: 当函数体量很大时（如 VM dispatcher 有 2000+ 行伪代码），`decompile` 返回的结果会被截断。我只关心其中一个 switch case 分支，但无法指定范围。

**实际影响**: 分析 JIT VM 的 26 个 handler 函数时，dispatcher 函数的完整反编译输出超过上下文窗口限制。我不得不：
1. 请求完整反编译（被截断）
2. 用 `disasm` 分段读取汇编（效率低）
3. 通过 `callees` 间接理解结构（信息不完整）

**期望**: 支持 `decompile(addr, line_range=(100, 200))` 或按地址范围反编译。

### 4.2 类型系统对 LLM 不友好

**问题描述**: `declare_type` 需要 C 语言风格的结构体声明，格式要求严格。作为 LLM，我在构造复杂结构体声明时容易出错（对齐、嵌套、前向声明等）。

**实际影响**: 分析 Enigma state 对象（4069 字节，包含 vtable、加密 key、VM 上下文等十几个字段）时，始终未能成功定义结构体。所有字段偏移都是通过 `get_bytes` 手动计算的。

**期望**: 支持 JSON 格式定义：
```json
{
  "name": "EnigmaState",
  "size": 4069,
  "fields": [
    {"offset": 0, "name": "vtable", "type": "uint64_t"},
    {"offset": 0x6B0, "name": "idea_key", "type": "uint8_t[16]"}
  ]
}
```

### 4.3 `trace_data_flow` 实用性不足

**问题描述**: 尝试追踪 IDEA key 的数据流来源时，返回结果包含大量中间节点和间接引用，难以从中提取有价值的信息。

**实际做法**: 放弃 `trace_data_flow`，改用 `xrefs_to` 手动逐级回溯。虽然慢，但每一步都可控。

**期望**: 返回结果增加摘要或按深度分层，优先展示直接的数据依赖关系。

### 4.4 `analyze_batch` / `analyze_component` 定位模糊

**问题描述**: 这两个工具的使用场景和预期输出不够清晰。它们与直接 `decompile` 多个函数有何区别？返回的"分析结果"应该如何指导后续操作？

**实际做法**: 基本不使用，直接 `decompile` 单个函数然后自行综合分析。

### 4.5 路径映射的心智负担

**问题描述**: 本地路径 `/workspace/...` 需要手动转换为 IDA 容器的 `/data/...`。虽然规则简单，但在高频操作中是持续的摩擦。

**出错案例**: 多次因为忘记转换路径导致 `idalib_open` 失败，需要重试。

**期望**: MCP server 端支持配置路径映射规则，客户端透明使用本地路径。

### 4.6 缺少撤销机制

**问题描述**: `rename` 或类型操作没有 undo。批量命名时如果发现某个命名有误，需要手动 rename 回去。

**实际影响**: 在批量命名 120+ 个函数时，有几次将错误的名称应用到了函数上（例如把一个 hook trampoline 误命名为实际的 API 函数），发现后需要手动修正。

---

## 五、改进建议

### 5.1 高优先级

#### 建议 1: 支持局部反编译

```
decompile(address, start_line=N, end_line=M)
```

或者支持按地址范围反编译：

```
decompile(address, addr_start=0x1000, addr_end=0x1100)
```

**理由**: 这是使用频率最高的工具的最大瓶颈。大函数在真实逆向工程中很常见（VM dispatcher、state machine、协议解析器等）。LLM 的上下文窗口有限，能精确获取需要的部分会大幅提升效率。

#### 建议 2: `strings_in_function` / `strings_in_range`

```
strings_in_function(func_addr) → [{"addr": 0x..., "value": "NtCreateFile", "xref_from": 0x...}, ...]
```

**理由**: 当前要获取一个函数引用的所有字符串，需要先 decompile 整个函数再从伪代码中人工提取。字符串是逆向分析中最重要的线索之一，值得有专门的接口。

#### 建议 3: 结构体定义的 JSON 接口

**理由**: LLM 生成 JSON 的准确率远高于生成精确的 C 结构体声明（特别是涉及对齐、padding、嵌套指针等场景）。一个 JSON-to-C 的转换层可以大幅降低类型系统的使用门槛。

### 5.2 中优先级

#### 建议 4: `find_bytes` 返回上下文

```
find_bytes(pattern, context_disasm=3)
→ [{"addr": 0x560092, "disasm_before": [...], "disasm_after": [...]}]
```

**理由**: 找到字节模式后，几乎总是需要看前后的反汇编来判断匹配是否有意义。目前需要额外调用 `disasm`，多一次往返。

#### 建议 5: 批量反编译摘要模式

```
decompile_batch(func_list, mode="summary")
→ [{"addr": 0x..., "name": "sub_...", "signature": "int64 (int64, int64)",
    "calls": ["CreateFileW", "ReadFile"], "brief": "Opens and reads a file"}, ...]
```

**理由**: 在对 270 个函数做初始分类时，我不需要每个函数的完整伪代码（那会超出任何上下文窗口）。我需要的是快速概览：签名、调用了什么 API、大致功能。

#### 建议 6: 路径自动映射

MCP server 配置文件中指定映射规则：

```json
{
  "path_mapping": {
    "/workspace": "/data"
  }
}
```

客户端传入 `/workspace/firmware/httpd`，server 自动转换为 `/data/firmware/httpd`。

### 5.3 低优先级

#### 建议 7: 操作历史与撤销

```
undo(count=1)  // 撤销最近 N 次修改操作
history(limit=20)  // 查看最近的操作历史
```

#### 建议 8: Section/Segment 导出

```
dump_section(section_name=".text", output_path="/data/output/text_section.bin")
```

**理由**: 当前需要先查 section 的 offset 和 size，再用 `get_bytes` 读取。对于大 section 还可能需要分段读取。

#### 建议 9: 函数相似性搜索

```
similar_functions(func_addr, threshold=0.8)
→ [{"addr": 0x..., "similarity": 0.92, "name": "sub_..."}, ...]
```

**理由**: 识别加壳器复制的库函数（如多个位置出现的 RC4、aPLib）时，如果能自动找到相似函数会大幅加速分析。

---

## 六、工作流最佳实践（面向 LLM 用户）

基于本项目的经验，总结以下最佳实践：

### 6.1 分析新二进制的标准流程

```
1. idalib_open(path)           → 打开二进制
2. survey_binary()             → 获取概览
3. imports()                   → 检查导入表
4. list_funcs(count=20)        → 看最大的几个函数
5. decompile(entry_point)      → 从入口点开始
6. 循环: decompile → rename → xrefs_to → decompile caller
```

### 6.2 密码学识别流程

```
1. find_bytes(known_constant)  → 搜索已知算法常量
   - IDEA: 搜索 key schedule 乘法常量
   - RC4: 搜索 S-box 初始化模式
   - AES: 搜索 S-box (637C777B...)
2. xrefs_to(constant_addr)     → 找到使用该常量的函数
3. decompile(func_addr)        → 确认算法实现
4. get_bytes(key_addr, size)   → 提取密钥材料
```

### 6.3 多 Session 管理

```
- 用描述性路径命名，方便 idalib_list 时识别
- 分析前先 idalib_list 检查是否已有 session
- 不用的 session 及时 idalib_close 释放资源
- idalib_save 保存重要的命名和注释成果
```

---

## 七、总结

| 维度 | 评分 | 说明 |
|------|------|------|
| 核心功能完整性 | 9/10 | 反编译、字节操作、交叉引用等核心能力齐全 |
| 多 Session 支持 | 9/10 | 并行分析多个二进制，切换流畅 |
| LLM 友好度 | 6/10 | 类型系统和部分高级功能对 LLM 不友好 |
| 大函数处理 | 4/10 | 缺少局部反编译，是最大短板 |
| 文档与错误提示 | 6/10 | 部分工具的使用场景和参数说明不够清晰 |
| **综合评分** | **8/10** | **在 LLM 辅助逆向工程场景下的最强工具，核心功能扎实，改进空间主要在大函数处理和类型系统** |

ida-pro-mcp 让 LLM 具备了真正的逆向工程能力，而不仅仅是"看代码"的能力。在本项目中，它是从加壳二进制中提取出完整功能分析的关键基础设施。如果能解决局部反编译和结构体定义简化这两个核心痛点，将会显著提升 LLM 在复杂逆向工程任务中的效率上限。
