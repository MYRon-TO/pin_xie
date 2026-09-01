# Pin Xie: 中文增强版 Spell 日志解析器

`pin_xie` 是一个基于 **Spell (Streaming Parsing of System Event Logs)** 思路实现的流式日志解析项目，重点在于对中文日志场景的支持与工程化改造。

> 说明：本项目**没有直接使用** `logpai/logparser` 的源码，但采用了 Spell 的核心算法思想，并参考了其模块化设计与使用方式。

## 与 logpai/logparser 的关系

- 参考项目：`logpai/logparser`（Spell）  
  https://github.com/logpai/logparser/tree/master/logparser/Spell
- 本项目复现并扩展的核心能力：
  - 基于 LCS 的模板在线收敛
  - 前缀树（Trie）快路径匹配
  - Jaccard 候选过滤后再进行 LCS 精算
  - 模板通配符 `*` 合并与参数提取

## 主要特性

- 中文增强分词：支持 `jieba` 分词与 Unicode Han 字符识别（可开关）
- 可配置脱敏切词：支持 `mask_patterns`（例如时间、IP）优先保留
- Header/Context 解耦：通过 `parse_structure` + `field_patterns` 先解析头部字段，再对 `context` 做 Spell 聚类
- 在线流式解析：按日志输入顺序实时更新模板簇
- 双输出结果：
  - `parsed_results.jsonl`：逐行解析结果
  - `templates.txt`：最终模板簇摘要

## 项目结构

```text
pin_xie/
├── config/
│   └── Config.toml
├── src/pin_xie/
│   ├── parser.py       # 主流程（Trie -> Jaccard -> LCS）
│   ├── tokenizer.py    # 中文/混合文本切词 + mask
│   ├── header.py       # 头部结构化解析（Regex）
│   ├── template.py     # 模板更新与参数提取
│   ├── lcs.py          # LCS 动态规划
│   ├── trie.py         # Prefix Tree
│   └── similarity.py   # Jaccard 过滤
└── output/
    ├── parsed_results.jsonl
    └── templates.txt
```

## 环境要求

- Python 3.11+
- 依赖：
  - `regex`
  - `jieba`

安装依赖示例：

```bash
python -m pip install regex jieba
```

## 快速开始

1) 选择输入模式并准备 UTF-8 日志文件

默认配置 `config/Config.toml` 使用单行模式：每个非空物理行是一条逻辑日志，纯空白行跳过，非空行的首尾空白会保留。例如：

```text
service started
request completed
```

动态 Header 示例 `config/Config.dynamic_example.toml` 使用多行模式。位于位置 0 且完整匹配 Header 的物理行开始一条新日志；下一个 Header 前的空行、缩进和换行都属于当前日志。例如异常栈：

```text
2026-03-20T10:00:00Z, user1, request failed
Traceback (most recent call last):
  File "app.py", line 10
2026-03-20T10:00:01Z, user1, request completed
```

2) 运行 demo

```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --config config/Config.dynamic_example.toml
```

无独立 Header 的逐行日志可使用默认单行配置：

```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --config config/Config.toml
```

支持三种模式：

- `learn_parse`（默认）：边学习边解析，同时写出解析结果和模板摘要。若 `--template-dir` 中已有模板缓存，则先加载并增量更新。
- `learn`：只学习模板，不写解析输出。若 `--template-dir` 中已有模板缓存，则先加载并增量更新；否则从空模板开始。
- `parse`：只解析，不更新模板；要求 `--template-dir` 中存在模板缓存。

示例：

```bash
# 1) 仅学习模板；缓存不存在时创建，存在时增量更新
PYTHONPATH=src python -m pin_xie.demo /path/to/train.log --mode learn --template-dir ./cache

# 2) 仅解析（使用已有模板，不更新）
PYTHONPATH=src python -m pin_xie.demo /path/to/infer.log --mode parse --template-dir ./cache

# 3) 学习并解析；缓存存在时在已有模板基础上更新
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --mode learn_parse --template-dir ./cache
```

3) 查看输出

- 逐行解析结果：`output/parsed_results.jsonl`
- 模板聚类结果：`output/templates.txt`
- 模板缓存（JSON）：`cache/templates.json`（目录可由 `--template-dir` 指定）
- 模式差异：`learn` 读取可选缓存并只写更新后的缓存；`parse` 读取必需缓存并只写解析结果；`learn_parse` 读取可选缓存，并写解析结果、模板摘要和更新后的缓存

## 作为库使用

可以直接使用 `PinXieEngine`，不依赖 CLI：

```python
from pin_xie import (
    InputToken, LiteralTemplateToken, LogRecordAssembler, MaskPattern,
    ParameterCapture, PinXieEngine, PlainTokenSource, RegexTokenSource,
    RunMode, VariableTemplateToken,
)

engine = PinXieEngine.from_config_path("config/Config.dynamic_example.toml")

# 文件 API 接收物理行，并按 input.mode 组装逻辑日志。
# LEARN 和 LEARN_PARSE 会在缓存存在时先加载，再增量更新。
report = engine.run_file("/path/to/train.log", mode=RunMode.LEARN, template_dir="cache")
print(report.processed_records, report.processed_physical_lines)

# process_lines 同样接收物理行迭代器，并在调用结束时 flush。
records = list(engine.process_lines(open("/path/to/infer.log", encoding="utf-8")))

# process_log 接收一条已经完整组装的逻辑日志；process_line 是兼容别名。
record = engine.process_log(
    "2026-03-20T10:00:00Z, user1, request failed\n  stack frame",
    line_id=10,
    end_line_id=11,
)

# 跨批次的有状态输入由调用方显式持有组装器。
assembler = LogRecordAssembler(engine.config.input.mode, engine.header_parser)
```

常用 API：

- `process_log(...)` / `process_line(...)`：处理一条完整逻辑日志，不负责物理行缓冲。
- `process_lines(...)` / `run_file(...)`：接收物理行，按配置组装后处理；每次调用使用独立组装器。
- `LogRecordAssembler.feed(...)` / `flush()`：支持调用方管理的跨批次流式组装。
- `save_template_cache(...)` / `load_template_cache(...)`：模板缓存读写。
- `validate_config_path(...)` / `validate_header_extraction(...)`：校验配置样本。multiline 样本可以包含换行，首个物理行必须是 Header。
- `set_template_variable_name(s)(...)` / `get_template_variable_names(...)`：管理模板变量名；名称直接存储在对应的 `VariableTemplateToken.var_name` 中，缓存不使用独立名称映射。

`read_toml_config`、`parse_config_data` 和 `from_config_data` 分别用于读取、解析和直接以 TOML 字典初始化配置。

## 配置说明（TOML）

### `[input]`

`mode` 是必填项，只接受 `single` 或 `multiline`，不会根据 Header 自动推断：

```toml
[input]
mode = 'single'
```

- `single`：每个非空物理行是一条逻辑日志，允许 `parse_structure = '<context>'`；纯空白行跳过。
- `multiline`：Header 行开始新日志，后续非 Header 行（包括空行和缩进行）原样并入正文，直到下一个 Header 或 EOF。第一条 Header 前的任何物理行都会报带行号的组装错误。

### `[learning]`

```toml
[learning]
shuffle = false
random_seed = 42
```

- `shuffle`：是否在文件学习前随机打乱完整逻辑日志，默认 `false`。
- `random_seed`：可选随机种子；相同输入、初始模板缓存和种子会产生相同学习顺序。
- 打乱只应用于 `run_file()` 的学习行为，`process_lines()` 和 `PARSE` 不打乱。
- `LEARN_PARSE` 启用打乱时，先按随机顺序学习，再按输入原序解析且不更新模型。
- 打乱发生在多行组装完成后，不改变逻辑日志内部的物理行顺序。启用后会将全部逻辑日志载入内存。

### `[spell]`

- `tau_ratio`：LCS 匹配阈值比例，默认 `0.5`（即 `tau = max(1, int(token_count * tau_ratio))`）。

### `[tokenizer]`

- `delimiters`：基础分隔符正则。
- `extra_delimiters`：额外分隔符规则。
- `use_jieba`：是否启用中文分词。
- `mask_patterns`：具名规则表数组；规则按配置顺序尝试，同一位置可匹配多条规则时前者优先。名称必须非空且唯一，正则必须有效且不能匹配空字符串。

```toml
[[tokenizer.mask_patterns]]
name = 'datetime'
pattern = '\\b\\d{4}/\\d{1,2}/\\d{1,2} [0-2]?\\d:[0-5]\\d\\b'

[[tokenizer.mask_patterns]]
name = 'ipv4'
pattern = '\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b'
```

### `[header]`

- `parse_structure`：必须显式配置且恰好包含一个 `<context>`。
- `strict_mode`：直接解析完整逻辑日志时，不匹配是否报错；不影响 multiline 的边界识别。
- `[header.field_patterns]`：每个非 `context` 占位符对应的有效正则。

multiline 模式还要求 `<context>` 位于结构末尾，且其前存在不能匹配空字符串的可识别 Header。Header 从字符位置 0 开始并按整个物理行匹配；只有配置本身包含或允许空白时才接受空白。

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

### Header 边界的已知限制

多行边界完全依赖 Header 匹配，不使用缩进、异常栈语法或“疑似 Header”启发式规则。因此：

1. 损坏而无法匹配的 Header 会被当作上一条日志的续行（漏判）；
2. 正文中完整匹配 Header 格式的行会被当作下一条日志起点（误判）。

本阶段不自动探测模式、不修复损坏 Header，也不支持续行正则或同一文件混合多种 Header。逻辑日志内部换行统一为 `\n`，不保留原始 CRLF/LF 差异。

## 算法流程

对每条日志的 `context`，解析器执行：

1. Tokenize（含中文分词与 mask）
2. Trie 快速匹配已有模板簇
3. 若未命中，做 Jaccard 候选过滤
4. 对候选做 LCS，按阈值与 tie-break 选择最佳簇
5. 命中则更新模板（差异位合并为变量槽位），否则新建簇
6. 基于模板提取参数列表

这与 Spell 论文和 `logpai/logparser` 的核心思路保持一致，但针对中文日志进行了切词和头部解析上的增强。

## 结果字段说明（JSONL）

每条逻辑日志对应一行 JSON。`line_id`、`end_line_id` 和 `physical_line_count` 描述物理行范围；`log` 是完整逻辑日志，`context` 是参与聚类的正文；`cluster_id` 标识模板簇，Header 字段以 `header_<name>` 输出。

模板和参数采用结构化对象：

```json
{"template":"connect <VAR:client>","template_tokens":[{"kind":"literal","text":"connect","sources":[{"kind":"plain"}]},{"kind":"variable","var_name":"client","sources":[{"kind":"plain"},{"kind":"regex","mask_name":"ipv4"}]}],"parameters":[{"template_token_index":1,"var_name":"client","value":"10.0.0.8","sources":[{"kind":"regex","mask_name":"ipv4"}]}],"tokens":[{"text":"connect","source":{"kind":"plain"}},{"text":"10.0.0.8","source":{"kind":"regex","mask_name":"ipv4"}}]}
```

- 输入 Token 是 `InputToken(text, source)`，其中来源为 `PlainTokenSource` 或带 `mask_name` 的 `RegexTokenSource`。
- 模板 Token 是 `LiteralTemplateToken(text, sources)` 或 `VariableTemplateToken(var_name, sources)`；`sources` 是累计、去重并稳定排序的来源。
- `ParameterCapture` 包含模板位置、变量名、捕获值及本次输入的来源；参数来源不是模板累计来源。
- `[output].show_tokens = true` 时输出 `tokens` 对象数组；为 `false` 时完全省略该字段。
- `templates.txt` 包含渲染模板、变量位置与累计来源，以及 tokenizer 摘要。

`RunReport.processed_records` 统计交给 Spell 的逻辑日志数；`processed_physical_lines` 统计读取的全部物理行（包括 single 模式跳过的空白行）。

模板缓存版本为 4，保存 `[input]`、`[header]`、`[learning]` 和完整 `[tokenizer]` 配置。加载兼容性校验 input/header，以及 tokenizer 的 `delimiters`、`extra_delimiters`、具名 mask（含顺序）和 `use_jieba`；learning 元数据只保存、不参与兼容性判断。v1、v2、v3 缓存均严格拒绝，不提供迁移，需以当前配置重新 learn。

## 致谢与参考文献

如果你在研究或工程中使用本项目，请同时关注 Spell 和 logparser 相关工作：

1. Min Du, Feifei Li.  
   **Spell: Streaming Parsing of System Event Logs**.  
   IEEE International Conference on Data Mining (ICDM), 2016.  
   https://www.cs.utah.edu/~lifeifei/papers/spell.pdf

2. Jieming Zhu, Shilin He, Jinyang Liu, Pinjia He, Qi Xie, Zibin Zheng, Michael R. Lyu.  
   **Tools and Benchmarks for Automated Log Parsing**.  
   International Conference on Software Engineering (ICSE), 2019.  
   https://arxiv.org/pdf/1811.03509.pdf

3. Pinjia He, Jieming Zhu, Shilin He, Jian Li, Michael R. Lyu.  
   **An Evaluation Study on Log Parsing and Its Use in Log Mining**.  
   IEEE/IFIP International Conference on Dependable Systems and Networks (DSN), 2016.  
   https://jiemingzhu.github.io/pub/pjhe_dsn2016.pdf

相关开源项目主页：

- LogPAI / LogParser: https://github.com/logpai/logparser

## License

Apache-2.0（见 `LICENSE`）。
