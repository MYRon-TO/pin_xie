# 多行日志解析执行计划

## 依据与固定决策

本执行计划落实 `docs/multiline-log-parsing-plan.md`。该文档第 2、5、7、9、10 节中的设计决策、验收标准和非目标均为固定约束，实施过程中不得擅自变更。

基线（实施前）：`pytest -q` 通过，结果为 6 passed；`jieba/pkg_resources` 弃用提示按项目规约忽略。计划中的测试均为本地纯单元/文件测试，不涉及数据库或大语言模型。

## 执行规约

- 串行执行以下步骤；每一步只允许一个 fresh-context Worker 修改当前工作区。
- Worker 不得调用子智能体、不得提交、不得实施后续步骤。
- Worker 遇到未决产品/架构问题必须停止并联系主智能体。
- 每一步由 Worker 自测并报告：改动文件、验证命令及结果、偏差、阻塞项、残余风险。
- 主智能体轻量审查无偏差后，立即为该步骤创建独立提交。
- 某一步有缺陷时，仅允许复用该 Worker 一次进行返工；仍失败则中止并通知用户。

## 步骤 1：输入配置与 Header 基础能力

### 范围

- 修改：`src/pin_xie/config.py`、`src/pin_xie/header.py`、`src/pin_xie/api.py`（仅配置样本验证所需部分）、`src/pin_xie/__init__.py`、`tests/test_header_validation.py`。
- 可为保持本步骤测试可运行而更新测试内的配置构造器；不得实现日志组装、文件 API、缓存升级或文档改动。

### 完成标准

- 新增并导出 `InputMode`、`InputConfig`，`DemoConfig.input` 必填。
- `[input]`、`input.mode`、`[header]` 和占位符/字段正则按主计划校验。
- multiline 模式执行 `<context>` 末尾、非空 Header 前缀等额外校验。
- Header 正则从位置 0 完整匹配；物理行与逻辑日志使用不同正则；新增 `is_header_line()`；逻辑日志 context 支持换行。
- 配置样本标准化只删除物理行终止符，并落实 single/multiline 样本语义。

### 验证

- `pytest -q tests/test_header_validation.py`
- `ruff check src/pin_xie/config.py src/pin_xie/header.py src/pin_xie/api.py src/pin_xie/__init__.py tests/test_header_validation.py`

## 步骤 2：独立逻辑日志组装器

### 范围

- 新增：`src/pin_xie/multiline.py`、`tests/test_multiline_assembly.py`。
- 修改：`src/pin_xie/__init__.py`（仅导出公共组装类型）。
- 不得接入 Engine、文件 API 或缓存。

### 完成标准

- 实现 `LogicalLog`、`LogAssemblyError`、`LogRecordAssembler`。
- single/multiline 的 `feed()`、`flush()`、`assemble()` 完全符合主计划 5.3 和 7.3–7.4。
- 保留正文空白/缩进，规范化行终止符，准确记录起止行；重复 flush 幂等。

### 验证

- `pytest -q tests/test_multiline_assembly.py`
- `ruff check src/pin_xie/multiline.py src/pin_xie/__init__.py tests/test_multiline_assembly.py`

## 步骤 3：Engine、文件处理与输出

### 范围

- 修改：`src/pin_xie/api.py`、`src/pin_xie/demo.py`、必要的现有测试。
- 新增：`tests/test_multiline_engine.py`。
- 可修改与 Engine 输出模型直接相关的代码；不得升级模板缓存版本或改文档/示例配置。

### 完成标准

- 新增 `process_log()`，`process_line()` 仅委托；`process_lines()` 与 `run_file()` 共用逻辑日志组装语义。
- `ParsedRecord` 增加 `end_line_id`、`physical_line_count`；`RunReport` 改为 `processed_records`、`processed_physical_lines`，删除 `processed_lines`。
- 三种 RunMode 使用相同边界；JSONL 每条逻辑日志一行并保留换行；学习模式即使不写解析输出也经过同一组装流程。
- CLI 使用新的两个统计字段。

### 验证

- `pytest -q tests/test_multiline_engine.py tests/test_multiline_assembly.py tests/test_header_validation.py`
- `ruff check src/pin_xie/api.py src/pin_xie/demo.py tests/test_multiline_engine.py`

## 步骤 4：模板缓存版本与配置一致性

### 范围

- 修改：`src/pin_xie/parser.py`、`src/pin_xie/api.py`、相关测试（优先放在 `tests/test_multiline_engine.py`，必要时新增专用测试文件）。
- 不得改文档或示例配置。

### 完成标准

- 缓存版本升级到 2，保存完整 `input` 和 `header` 配置。
- 加载时先校验根对象、版本及 input/header 结构，再精确比较当前配置，最后恢复模板。
- mode、parse_structure、strict_mode、field_patterns 任一不一致均报出差异；版本 1 明确要求重新 learn；失败不得部分加载模型。

### 验证

- `pytest -q tests/test_multiline_engine.py tests/test_header_validation.py tests/test_multiline_assembly.py`
- `ruff check src/pin_xie/parser.py src/pin_xie/api.py tests`

## 步骤 5：示例配置与文档

### 范围

- 修改：`config/Config.toml`、`config/Config.dynamic_example.toml`、`README.md`、`docs/build_sequence_training_csv.md`。
- 如文档示例需要测试，可新增最小测试；不得再改变已批准的实现设计。

### 完成标准

- 两个 TOML 示例显式配置 input.mode，默认示例为 single，动态 Header 示例按主计划设为 multiline。
- README 说明配置、single/multiline 行为、API、输出字段、缓存约束、Header 边界算法的误判/漏判限制，并给出单行和异常栈示例。
- 训练 CSV 文档说明其 single 模式前提。

### 验证

- `pytest -q`
- `ruff check src tests`

## 最终验收

主智能体在所有步骤提交后：

1. 运行 `pytest -q` 与 `ruff check src tests`；
2. 检查完整 diff/提交序列和工作区状态；
3. 使用 fresh-context Reviewer 对正确性/回归、测试覆盖与简洁性做只读审查；若发现必须修复的问题，按“一次返工”规则调用一个 Worker 修复并验证、提交；
4. 确认 `docs/multiline-log-parsing-plan.md` 第 9 节 12 条验收标准全部有实现或测试证据。
