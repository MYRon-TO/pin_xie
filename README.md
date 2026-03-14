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

1) 准备日志文件（UTF-8 编码）

```text
2025/11/26 0:48,user1,验证用户 user1 对文件 file9 的访问权限
2025/11/26 0:50,user1,权限验证结果: 有权限
2025/11/26 0:51,user1,文件 file9 下载成功
```

2) 运行 demo

```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --config config/Config.dynamic_example.toml
```

如果你的日志没有独立 header，可使用默认配置：

```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --config config/Config.toml
```

支持三种模式：

- `learn_parse`（默认）：边学习边解析（保留原有行为），同时写出解析结果和模板摘要。
- `learn`：只学习模板，不写解析输出；模板会保存到 `--template-dir`（默认 `./cache/`）。
- `parse`：只解析，不更新模板；会从 `--template-dir` 读取模板缓存。

示例：

```bash
# 1) 仅学习模板（不输出 parsed_results/templates.txt）
PYTHONPATH=src python -m pin_xie.demo /path/to/train.log --mode learn --template-dir ./cache

# 2) 仅解析（使用已有模板，不更新）
PYTHONPATH=src python -m pin_xie.demo /path/to/infer.log --mode parse --template-dir ./cache

# 3) 维持原有模式（学习 + 解析）
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --mode learn_parse
```

3) 查看输出

- 逐行解析结果：`output/parsed_results.jsonl`
- 模板聚类结果：`output/templates.txt`
- 模板缓存（JSON）：`cache/templates.json`（目录可由 `--template-dir` 指定）
- 模式差异：`learn` 仅写缓存；`parse` 仅写解析结果；`learn_parse` 同时写解析结果、模板摘要和缓存

## 作为库使用

你可以直接使用 `PinXieEngine` 以 API 方式集成，不依赖 CLI。

```python
from pin_xie import PinXieEngine, RunMode

engine = PinXieEngine.from_config_path("config/Config.dynamic_example.toml")

# 1) 学习模板（只更新模板并写缓存）
engine.run_file("/path/to/train.log", mode=RunMode.LEARN, template_dir="cache")

# 2) 解析日志（只解析，不更新模板）
report = engine.run_file("/path/to/infer.log", mode=RunMode.PARSE, template_dir="cache")
print(report.processed_lines)

# 3) 流式逐行处理
record = engine.process_line("2025/11/26 0:51,user1,文件 file9 下载成功", line_id=1)
print(record.cluster_id, record.template)
```

常用 API：

- `PinXieEngine.from_config_path(config_path)`：从 TOML 配置初始化
- `PinXieEngine.read_toml_config(config_path)`：只读取 TOML 文件并返回原始字典
- `PinXieEngine.parse_config_data(data)`：将 TOML 字典解析为 `DemoConfig`
- `PinXieEngine.from_config_data(data)`：从 TOML 字典初始化引擎
- `run_file(...)`：按 `learn/parse/learn_parse` 模式处理文件
- `process_line(...)` / `process_lines(...)`：逐行或流式处理
- `save_template_cache(...)` / `load_template_cache(...)`：模板缓存读写
- `set_template_variable_name(cluster_id, var_index, var_name)`：为模板变量设置/清空名称（`var_name=None` 或空串表示清空）
- `set_template_variable_names(cluster_id, variable_names)`：批量更新变量名称，支持部分命名
- `get_template_variable_names(cluster_id)`：获取模板当前已命名变量

额外配置校验 API：

- `PinXieEngine.validate_config_path(config_path, samples)`：给定样本日志列表，校验 header 结构提取是否对全部样本成功
- `PinXieEngine.validate_header_extraction(config, samples)`：对已解析配置执行同样校验

说明：仅当 `parse_structure` 中包含 `<context>` 之外的 header 字段时才会执行该校验；如果配置为纯 `<context>`，会直接返回通过。

## 配置说明（TOML）

### `[spell]`

- `tau_ratio`：LCS 匹配阈值比例，默认 `0.5`（即 `tau = max(1, int(token_count * tau_ratio))`）

### `[tokenizer]`

- `delimiters`：基础分隔符正则
- `extra_delimiters`：额外分隔符规则
- `use_jieba`：是否启用中文分词
- `mask_patterns`：优先保留的模式（如时间/IP），避免被切碎

### `[header]`

- `parse_structure`：头部解析结构，必须包含 `<context>`
- `strict_mode`：不匹配时是否报错
- `[header.field_patterns]`：每个占位符对应的正则

示例（三段式日志）：

```toml
[header]
parse_structure = '<time>,<entity>,<context>'
strict_mode = false

[header.field_patterns]
time = '\d{4}/\d{1,2}/\d{1,2}\s+(?:[01]?\d|2[0-3]):[0-5]\d'
entity = '[\p{L}\p{N}_.@-]+'
```

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

典型字段包括：

- `line_id`：日志行号
- `cluster_id`：模板簇 ID
- `context`：参与 Spell 聚类的正文
- `template` / `template_tokens`：当前模板（变量位渲染为 `<VAR:var_0>` 或 `<VAR:变量名>`）
- `parameters`：按变量位顺序提取的参数列表
- `named_parameters`：变量名（未命名回退为 `var_N`）到参数值的映射
- `header_*`：从 header 解析出的结构化字段（若配置）

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
