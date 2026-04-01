# Ramune-ida TODO

> 剩余未实现的功能和改进计划。
>
> 来源标记：[bench] = 2026-04-01 benchmark 测试中发现的问题

---

## 基础设施

- [ ] **tool call 批量化** — 支持单次请求中批量调用多个工具（如批量 rename、批量 set_type），减少 IPC 往返开销
- [ ] **tag filter 系统** — 基于 tags 的工具可见性过滤，客户端可按 domain/kind 筛选工具列表（如只显示 `kind:read` 或隐藏 `kind:unsafe`）
- [ ] **大文件上传流式写入** — `files.py` upload 端点改为分块流式写入磁盘，避免大文件全量读入内存
- [ ] [bench] **execute_python 硬超时去掉** — 统一走 MCP 层超时 + task_id 轮询/cancel。两层超时行为不可预测

---

## 新工具

- [ ] resolve — VA ↔ 文件偏移 ↔ ASLR 运行时地址互转
- [ ] stack_frame — 函数栈帧布局查看
- [ ] [bench] call_graph — `call_graph(func, depth?, direction?)` 返回调用树 JSON。用 `idautils.CodeRefsFrom`/`CodeRefsTo` 递归构建

---

## listing 扩展

> 当前：list_funcs, list_strings, list_imports, list_names（4 个）。
> 过滤统一为 `filter`（substring 包含）+ `exclude`（substring 排除），各接受单个字符串。去掉 offset/count 分页。

- [ ] list_exports — 导出函数
- [ ] list_segments — 段信息
- [ ] list_types — 本地类型库
- [ ] list_structs — 结构体列表
- [ ] list_enums — 枚举列表
- [ ] list_entries — 入口点

---

## xrefs 增强

> 当前：xrefs(addr) — XrefsTo 按地址/名称查引用。返回包含 total 字段。

- [ ] 区分 code ref / data ref（可选标记）
- [ ] direction 参数：`"to"` / `"from"`（XrefsFrom）
- [ ] xrefs(struct, field) — 结构体成员 xref（依赖 ida_typeinf TID）
- [ ] xrefs(type) — 谁使用了这个类型（遍历函数签名/变量）
- [ ] [bench] **间接引用搜索** — 当 `idautils.XrefsTo` 返回空时（Rust `&str` slice 引用、C++ vtable 间接调用等场景），自动搜索目标地址的小端序编码字节（4/8 字节），作为 fallback。或通过新增 `deep=true` 参数触发

---

## search 扩展

> 当前：regex 搜索 strings/names/types/disasm + 字节模式搜索。

- [ ] 反编译结果搜索 — 从 decompile 缓存中 regex 搜索伪代码
- [ ] 偏移/常量搜索 — 搜索立即数（immediate value），跨汇编和数据段
- [ ] 注释搜索 — 搜索用户注释和 IDA 自动注释

---

## decompile 增强

- [ ] 局部反编译 — 行范围或地址范围，大函数场景
- [ ] 摘要模式 — 签名 + 调用 + 字符串 + 控制流概览
- [ ] [bench] **非函数地址自动创建函数** — 当目标地址未被 IDA 识别为函数时，自动尝试 `ida_funcs.add_func(addr)` 后重试反编译。通过 `force` 参数控制（默认 false）

---

## 错误哲学

> **报告事实，不做翻译。** MCP 的消费者是 AI，不需要我们替它解读 IDA API 的返回值含义。
> 错误信息应直接反映"调了什么 API、传了什么参数、得到了什么结果"，让 AI 自己判断下一步。
> 例如：`"get_func(0x1234) returned None"` 而非 `"0x1234 is not a function"`。
> 参数校验错误（`"Missing required parameter: func"`）保持不变——这些本身就是事实陈述。

---

## 远期

- [ ] analysis_progress — 分析进度统计（已命名/已注释/已设类型比例）
- [ ] cluster_funcs — 基于调用图连通分量自动聚类
- [ ] 相似函数检测 — CFG 哈希或字节签名找结构相似函数
- [ ] FLIRT/Lumina 集成 — 自动标记已知库函数
