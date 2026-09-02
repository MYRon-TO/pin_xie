# 单行与多行日志解析实施计划

## 1. 目标

为 Pin Xie 增加显式的单行、多行输入模式，同时保持 Spell 聚类器只处理已经组装完成的逻辑日志。

核心目标：

1. 单行模式下，每个非空物理行是一条逻辑日志，并允许 `header.parse_structure = '<context>'`；
2. 多行模式下，以位于物理行行首并完整匹配 Header 格式的行作为新日志起点；
3. 新日志头之后的所有非日志头行都归入当前逻辑日志，直到下一个日志头或文件结束；
4. 保留多行正文中的换行、空白行和缩进；
5. 文件 API、流式 API、JSONL 输出和模板缓存使用一致的模式及 Header 语义。

本次改造不改变 Spell 的 Trie、Jaccard、LCS、模板合并和参数提取算法。

---

## 2. 已确认的设计决策

### 2.1 输入模式

新增显式配置：

```toml
[input]
mode = 'single' # single | multiline
```

规则：

- `input.mode` 是必填字符串枚举；
- 只接受 `single` 和 `multiline`；
- 不根据 `parse_structure` 自动推断模式；
- 配置缺失或取值非法时，在创建引擎前报配置错误。

### 2.2 单行模式

- 每个非空物理行是一条逻辑日志；
- 允许纯正文结构：

  ```toml
  [header]
  parse_structure = '<context>'
  ```

- 完全由空白字符组成的物理行被跳过；
- 不修改非空行的行首、行尾空格及缩进，只移除物理行终止符；
- 一条逻辑日志的 `line_id` 与 `end_line_id` 相同。

### 2.3 多行模式

- `header.parse_structure` 必须显式配置；
- `<context>` 必须且只能出现一次，并且必须位于结构末尾；
- `<context>` 前必须存在可识别且不能匹配空字符串的 Header 前缀；
- Header 前缀可以由以下任一内容构成：
  - 非空固定字面量；
  - 一个或多个非 `context` 占位符；
  - 两者组合；
- 所有非 `context` 占位符必须在 `header.field_patterns` 中配置有效正则；
- Header 从字符位置 0 开始匹配，解析器不再隐式接受行首空白；
- 如果配置本身显式包含空白字面量或允许空白的字段正则，则按配置匹配；“位于行首”表示匹配起点固定为位置 0，而不是擅自改写用户正则；
- 第一条日志头之前出现任何非日志头物理行，包括空行或纯空白行，都立即报错；
- 当前已有日志缓冲区时，空行、纯空白行和缩进行都作为续行原样保留；
- 文件结束时必须输出缓冲区中的最后一条逻辑日志。

### 2.4 行号语义

- `line_id`：逻辑日志的起始物理行号；
- `end_line_id`：逻辑日志的结束物理行号；
- `physical_line_count = end_line_id - line_id + 1`；
- Spell 模板簇中的 `line_ids` 继续记录 `line_id`，即逻辑日志的起始物理行号。

### 2.5 API 语义

- `process_line()`：接收一条已经完整组装的逻辑日志；
- 新增 `process_log()` 作为语义更明确的主方法，`process_line()` 委托给它；
- `process_lines()`：接收物理行迭代器，根据 `input.mode` 组装并处理逻辑日志；
- `run_file()`：复用与 `process_lines()` 相同的组装逻辑，禁止维护第二套划分实现；
- 单条有状态流式输入由独立组装器的 `feed()` 和 `flush()` 支持。

### 2.6 模板缓存

- 模板缓存保存 `input.mode` 和完整 Header 配置；
- 加载缓存时，当前配置与缓存配置必须一致；
- 模式、`parse_structure`、`strict_mode` 或 `field_patterns` 任一不一致都报错；
- 缓存版本升级，不迁移旧缓存。

### 2.7 已接受的算法限制

多行边界完全依赖 Header 匹配，因此存在两类不可消除的情况：

1. 一条损坏的日志头如果不匹配配置，会被当作上一条日志的续行；
2. 正文中的某一行如果完整匹配 Header 格式，会被当作下一条日志的起点。

本阶段接受并在 README 中明确说明该限制，不增加“疑似日志头”或“续行格式”配置。

---

## 3. 目标行为示例

### 3.1 单行模式

配置：

```toml
[input]
mode = 'single'

[header]
parse_structure = '<context>'
strict_mode = false

[header.field_patterns]
```

输入：

```text
service started

request completed
```

输出两条逻辑日志：

| `line_id` | `end_line_id` | `context` |
|---:|---:|---|
| 1 | 1 | `service started` |
| 3 | 3 | `request completed` |

第 2 行为空白行，因此跳过。

### 3.2 多行模式

配置：

```toml
[input]
mode = 'multiline'

[header]
parse_structure = '<time> <level> <context>'
strict_mode = true

[header.field_patterns]
time = '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
level = 'DEBUG|INFO|WARN|ERROR|FATAL'
```

输入：

```text
2026-03-20 10:00:00 ERROR request failed
Traceback (most recent call last):
  File "app.py", line 10

2026-03-20 10:00:01 INFO request completed
```

输出两条逻辑日志：

1. 起止行为 1—4，正文为：

   ```text
   request failed
   Traceback (most recent call last):
     File "app.py", line 10
   ```

   第 4 个物理行是空行，必须保留在逻辑日志末尾。

2. 起止行均为 5，正文为 `request completed`。

---

## 4. 当前实现差距

### 4.1 配置会静默回退到纯 context

`src/pin_xie/config.py` 当前在缺少 Header 配置时默认使用 `<context>`，也没有输入模式配置。多行模式无法据此判断配置缺失还是用户有意使用纯正文。

### 4.2 Header 正则隐式接受行首空白

`src/pin_xie/header.py` 当前以 `^\s*` 开始组合正则，不满足严格从位置 0 按配置匹配的要求。

### 4.3 context 默认不支持换行

当前 `<context>` 默认使用 `.*`，未启用 DOTALL 时不能匹配多行正文。

### 4.4 文件处理直接逐行解析

`src/pin_xie/api.py` 的 `run_file()` 当前把每个物理行直接交给 `process_line()`，没有逻辑日志缓冲区。

### 4.5 `strip()` 破坏原始正文

`process_lines()`、`run_file()` 和配置样本标准化当前使用 `strip()`：

- 会删除栈追踪缩进；
- 会删除有意义的尾随空格；
- 会掩盖 Header 前存在空白的问题；
- 会直接丢弃多行正文中的空白行。

### 4.6 输出只记录一个行号

`ParsedRecord` 和 JSONL 只有 `line_id`，不能表达多行逻辑日志的物理范围。

### 4.7 模板缓存没有强制校验 Header 配置

缓存虽然保存了 Header 状态，但加载时没有和当前引擎配置进行一致性校验，也没有保存输入模式。

---

## 5. 详细设计

### 5.1 配置模型

修改 `src/pin_xie/config.py`。

新增：

```python
class InputMode(str, Enum):
    SINGLE = "single"
    MULTILINE = "multiline"


@dataclass(frozen=True)
class InputConfig:
    mode: InputMode
```

在 `DemoConfig` 中增加：

```python
input: InputConfig
```

配置解析分为通用校验和模式相关校验。

通用校验：

- `[input]` 必须是 TOML table；
- `input.mode` 必须存在并属于枚举；
- `[header]` 必须是 TOML table；
- `parse_structure` 必须包含且只能包含一个 `<context>`；
- 非 context 字段必须有非空且可编译的正则。

多行模式额外校验：

- `parse_structure` 不能是纯 `<context>`；
- `<context>` 必须是最后一个占位符，且其后不能存在非空结构字面量；
- `<context>` 前必须存在 Header 结构；
- 编译后的 Header 前缀不能匹配空字符串。

单行模式不强制存在非 context Header 字段，也允许纯 `<context>`。

`InputMode`、`InputConfig` 需要从 `pin_xie.__init__` 导出。

### 5.2 Header 正则拆分

修改 `src/pin_xie/header.py`，避免使用同一个正则同时承担物理行边界检测和完整逻辑日志解析。

`RegexHeaderParser` 内部维护：

1. `header_line_re`
   - 只匹配单个物理行；
   - 从 `\A` 开始，到 `\Z` 结束；
   - `<context>` 匹配除 `\r`、`\n` 外的字符；
   - 用于 `is_header_line()`。

2. `logical_log_re`
   - 匹配已经组装完成的完整逻辑日志；
   - 从 `\A` 开始，到 `\Z` 结束；
   - `<context>` 使用可跨行模式，例如 `[\s\S]*`；
   - 用于现有 `parse()`。

新增：

```python
def is_header_line(self, line: str) -> bool: ...
```

要求：

- 方法不受 `strict_mode` 影响；
- 不匹配时返回 `False`，不抛出普通格式异常；
- 调用方必须传入已经移除 `\r\n` 或 `\n` 的单个物理行；
- 正则构建与字段校验错误仍在初始化阶段抛出 `HeaderConfigurationError`。

`parse()` 继续遵守 `strict_mode`：直接处理调用方传入的完整逻辑日志时，如果 Header 不匹配，严格模式报错，非严格模式回退为原始 context。

### 5.3 逻辑日志组装器

新增 `src/pin_xie/multiline.py`。

建议数据结构：

```python
@dataclass(frozen=True)
class LogicalLog:
    text: str
    start_line: int
    end_line: int

    @property
    def physical_line_count(self) -> int:
        return self.end_line - self.start_line + 1
```

建议错误类型：

```python
class LogAssemblyError(ValueError):
    line_number: int
    line_preview: str
```

建议组装器接口：

```python
class LogRecordAssembler:
    def feed(self, raw_line: str, line_number: int) -> LogicalLog | None: ...

    def flush(self) -> LogicalLog | None: ...

    def assemble(
        self,
        lines: Iterable[str],
        *,
        start_line: int = 1,
    ) -> Iterator[LogicalLog]: ...
```

组装器根据 `InputMode` 工作。

#### 单行模式算法

1. 只移除一个物理行终止符：`\n`、`\r\n` 或文件末尾可能存在的单独 `\r`；
2. 使用 `line.strip() == ""` 判断是否为空白行，但不把 strip 后的内容作为日志正文；
3. 空白行不输出；
4. 非空行立即输出 `LogicalLog(text=line, start_line=n, end_line=n)`；
5. `flush()` 不产生额外记录。

#### 多行模式算法

1. 移除物理行终止符，但保留该行的其他所有字符；
2. 调用 `header_parser.is_header_line(line)`；
3. 如果匹配：
   - 先输出已有缓冲区；
   - 再以当前行建立新缓冲区；
4. 如果不匹配且已有缓冲区，将当前行追加到缓冲区；
5. 如果不匹配且缓冲区为空，抛出 `LogAssemblyError`，包含物理行号和受限长度的内容预览；
6. `flush()` 使用 `"\n".join(buffer)` 输出最后一条逻辑日志；
7. 连续空行通过缓冲区中的空字符串保留；
8. 重复调用 `flush()` 不应重复输出记录。

文件中的 CRLF 与 LF 统一规范化为逻辑日志内的 `\n`。本阶段不承诺在 JSONL 中保留原始换行编码。

### 5.4 Engine API

修改 `src/pin_xie/api.py`。

#### `process_log()`

新增：

```python
def process_log(
    self,
    log: str,
    *,
    line_id: int | None = None,
    end_line_id: int | None = None,
    update_model: bool = True,
) -> ParsedRecord: ...
```

规则：

- 输入必须是一条完整逻辑日志；
- `end_line_id` 未提供时等于有效 `line_id`；
- `end_line_id < line_id` 时抛出 `ValueError`；
- Header 提取后只把 `context` 交给 `SpellParser.process()`；
- `ParsedRecord.log` 保存完整逻辑日志，而不是仅保存第一行。

保留：

```python
process_line(...)
```

作为 `process_log()` 的兼容名称和简单调用入口，不承担物理行缓冲职责。

#### `process_lines()`

改为：

1. 接收物理行迭代器；
2. 创建新的组装器；
3. 对每个 `LogicalLog` 调用 `process_log()`；
4. 调用结束时自动 `flush()`；
5. 返回一个 `ParsedRecord` 迭代器。

为了避免跨调用残留状态，普通 `process_lines()` 每次调用使用独立组装器。需要跨批次流式输入时，由调用方显式创建并持有 `LogRecordAssembler`。

#### `run_file()`

- 复用组装器或 `process_lines()` 的同一内部迭代逻辑；
- 不再对输入行调用 `strip()`；
- 学习、解析、学习并解析三种 RunMode 必须使用完全相同的逻辑日志边界；
- JSONL 每条逻辑日志写一行；
- 即使不写 parsed output，学习模式也必须经过相同组装流程。

### 5.5 输出模型

修改 `ParsedRecord`：

```python
@dataclass
class ParsedRecord:
    line_id: int
    end_line_id: int
    physical_line_count: int
    ...
```

JSONL 增加：

```json
{
  "line_id": 10,
  "end_line_id": 14,
  "physical_line_count": 5
}
```

修改 `RunReport`：

```python
processed_records: int
processed_physical_lines: int
```

删除含义已经不准确的 `processed_lines`，不保留双重计数字段。项目仍处开发早期，不为该字段提供迁移兼容层。

CLI 输出调整为：

```text
Processed records: N
Processed physical lines: M
```

其中：

- `processed_records` 是实际交给 Spell 的逻辑日志数量；
- `processed_physical_lines` 是文件中读取的物理行数量，包括单行模式跳过的空白行，以及多行模式正文中的空白行；
- 空文件两个计数均为 0。

### 5.6 配置样本验证

当前 `_normalize_samples()` 使用 `strip()`，需要改为只移除物理行终止符，保留行首空白。

单行模式：

- 纯 `<context>` 继续直接通过 Header 提取校验；
- 配置了 Header 时，继续验证样本的完整结构。

多行模式：

- 每个样本视为一条完整逻辑日志，可以包含换行；
- 样本第一物理行必须通过 `is_header_line()`；
- 完整样本必须通过 `logical_log_re` 并正确提取字段；
- 前导空白不能被标准化逻辑偷偷删除。

失败报告继续只保留每个样本的第一个问题点，并增加适用于多行模式的 reason，例如：

- `multiline_context_not_last`；
- `multiline_header_missing`；
- `multiline_header_matches_empty`；
- `sample_first_line_not_header`。

### 5.7 模板缓存

模板状态版本从 `1` 升级到 `2`，目标结构包含：

```json
{
  "version": 2,
  "input": {
    "mode": "multiline"
  },
  "header": {
    "parse_structure": "<time> <level> <context>",
    "strict_mode": true,
    "field_patterns": {
      "time": "...",
      "level": "..."
    }
  },
  "clusters": []
}
```

加载顺序：

1. 验证根对象及版本；
2. 验证缓存中的 input/Header 结构；
3. 对字段映射进行规范化后，与当前 Engine 配置做精确比较；
4. 不一致时抛出包含差异项的 `ValueError`；
5. 一致后再恢复 Spell 模板和 Trie。

版本 1 缓存直接报“不支持的缓存版本”，提示重新执行 learn，不做自动迁移。

---

## 6. 文件级改动清单

### 新增

- `src/pin_xie/multiline.py`
  - `LogicalLog`
  - `LogAssemblyError`
  - `LogRecordAssembler`
- `tests/test_multiline_assembly.py`
- `tests/test_multiline_engine.py`

### 修改

- `src/pin_xie/config.py`
  - 新增 `InputMode`、`InputConfig`
  - 增加模式相关配置校验
- `src/pin_xie/header.py`
  - 去除隐式 `^\s*`
  - 拆分物理行和完整逻辑日志正则
  - 新增 `is_header_line()`
  - 支持多行 context
- `src/pin_xie/api.py`
  - 新增 `process_log()`
  - 改造 `process_line()`、`process_lines()`、`run_file()`
  - 扩展 `ParsedRecord`、`RunReport` 和 JSONL payload
  - 加载缓存时校验模式及 Header
- `src/pin_xie/parser.py`
  - 模板缓存状态升级到版本 2
  - 保存输入模式及 Header 状态，或将这部分状态统一交由 Engine 组装
- `src/pin_xie/demo.py`
  - 更新运行统计输出
- `src/pin_xie/__init__.py`
  - 导出新增公共类型
- `config/Config.toml`
  - 显式设置 `input.mode = 'single'`
- `config/Config.dynamic_example.toml`
  - 根据示例用途设置 `input.mode = 'multiline'`
- `tests/test_header_validation.py`
  - 增加模式相关配置与行首校验
- `README.md`
  - 增加单行、多行配置和行为说明
- `docs/build_sequence_training_csv.md`
  - 说明该脚本使用单行模式，并更新配置前提

---

## 7. 测试计划

以下测试均为本地纯单元或文件测试，不涉及数据库和大语言模型。

### 7.1 配置测试

1. 缺少 `[input]` 报错；
2. 缺少 `input.mode` 报错；
3. 非法模式值报错；
4. 单行模式允许纯 `<context>`；
5. 多行模式拒绝纯 `<context>`；
6. 多行模式拒绝 `<context>` 位于中间；
7. 多行模式拒绝 `<context>` 后存在非空字面量；
8. 多行模式拒绝可匹配空字符串的 Header 前缀；
9. 固定字面量 Header 前缀可用；
10. 非 context 字段缺少 pattern 时报告字段名；
11. Header 字段正则非法时在初始化阶段报错。

### 7.2 Header 测试

1. 正常 Header 在位置 0 匹配；
2. Header 前增加未配置空格后不匹配；
3. 配置显式包含空格时按配置匹配；
4. `is_header_line()` 不匹配时返回 `False`；
5. `parse()` 能提取包含换行的 context；
6. Header-only 行可以得到空 context；
7. 字段正则和固定字面量仍按完整结构匹配。

### 7.3 单行组装测试

1. 每个非空物理行输出一条记录；
2. 空行与纯空白行跳过；
3. 非空行的首尾空格保留；
4. CRLF 和 LF 均正确移除物理行终止符；
5. 行号与输入物理行一致；
6. 空输入输出空迭代器。

### 7.4 多行组装测试

1. 两条多行日志正确划分；
2. 单条单行日志也能在多行模式输出；
3. EOF 输出最后一条记录；
4. 空白续行保留；
5. 栈追踪缩进保留；
6. 第一条 Header 前出现普通文本时报物理行号；
7. 第一条 Header 前出现空白行也报错；
8. Header-only 行允许后续追加正文；
9. 正文行完整匹配 Header 时开始新记录；
10. 损坏 Header 不匹配时归入上一条正文；
11. `flush()` 重复调用不会重复输出；
12. 分批 `feed()` 与一次性 `assemble()` 结果一致。

### 7.5 Engine 和输出测试

1. `process_log()` 正确解析多行 context；
2. `process_line()` 与 `process_log()` 结果一致；
3. `process_lines()` 在两种输入模式下行为正确；
4. `line_id`、`end_line_id`、`physical_line_count` 正确；
5. JSONL 一条逻辑日志只写一行；
6. JSON 中的 `log` 与 `context` 保留 `\n`；
7. learn、parse、learn_parse 使用一致边界；
8. `processed_records` 与 `processed_physical_lines` 正确；
9. 不写 parsed output 时仍按逻辑日志学习；
10. 多行日志参数提取与模板更新不发生回归。

### 7.6 缓存测试

1. 缓存写入版本 2、input 和 Header；
2. 相同配置可以加载；
3. single/multiline 不一致时拒绝加载；
4. `parse_structure` 不一致时拒绝加载；
5. `strict_mode` 不一致时拒绝加载；
6. `field_patterns` 不一致时拒绝加载；
7. 版本 1 缓存提示重新学习；
8. 配置校验失败时不部分加载模板。

---

## 8. 实施步骤

### 阶段一：配置与 Header 基础能力

1. 增加 `InputMode`、`InputConfig`；
2. 完成单行、多行条件校验；
3. 拆分 Header 物理行正则与逻辑日志正则；
4. 增加配置和 Header 单元测试。

完成标准：Header 能严格判断物理行起点，并能解析包含换行的完整逻辑日志。

### 阶段二：日志组装器

1. 新增 `LogicalLog` 和 `LogRecordAssembler`；
2. 实现 single/multiline 两套确定性状态转换；
3. 实现 `feed()`、`flush()`、`assemble()`；
4. 完成空白、EOF、行号和错误测试。

完成标准：组装器不依赖 Spell，给定同一物理行序列始终产生相同逻辑日志序列。

### 阶段三：Engine、文件处理和输出

1. 新增 `process_log()`；
2. 改造 `process_lines()` 和 `run_file()`；
3. 扩展 `ParsedRecord`、`RunReport` 和 JSONL；
4. 确保三种 RunMode 共用边界逻辑；
5. 完成端到端文件测试。

完成标准：单行和多行文件均可通过 CLI/API 学习与解析，且输出行号范围正确。

### 阶段四：缓存约束

1. 升级缓存版本；
2. 保存 input/Header；
3. 加载前执行精确一致性校验；
4. 增加缓存不一致测试。

完成标准：不同输入模式或 Header 配置不能误用同一模板缓存。

### 阶段五：配置样例与文档

1. 更新两个 TOML 示例；
2. 更新 README 的 API、配置、输出字段和限制；
3. 更新训练 CSV 文档；
4. 增加单行和异常栈多行示例。

---

## 9. 验收标准

实现完成后必须满足：

1. 用户必须通过 `[input].mode` 明确选择单行或多行模式；
2. 单行模式可使用纯 `<context>`，并保持当前逐行聚类用途；
3. 多行模式不能使用纯 `<context>`，且只能根据位置 0 的完整 Header 匹配切分；
4. 多行正文中的换行、空行和缩进不会被 `strip()` 破坏；
5. 第一条 Header 前的任何内容产生可定位到物理行的错误；
6. 文件结束不会丢失最后一条日志；
7. `process_lines()` 与 `run_file()` 的边界结果一致；
8. 输出包含逻辑日志起止行和物理行数量；
9. 三种 RunMode 对同一输入使用相同逻辑日志边界；
10. 模板缓存不能跨输入模式或 Header 配置误用；
11. 现有 Spell 聚类核心测试及新增测试全部通过；
12. README 明确记录基于 Header 划分的误判与漏判边界。

---

## 10. 非目标

本阶段不实现：

- 根据缩进、括号平衡或异常栈语法推断多行边界；
- “疑似日志头”告警；
- 可配置续行正则；
- 同一个文件中混合多种 Header 格式；
- 自动探测 single/multiline 模式；
- 保留原始 CRLF/LF 编码差异；
- 旧版模板缓存迁移；
- 对损坏 Header 的自动修复。
