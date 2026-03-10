# AGENTS.md
本文件面向在本仓库中工作的 agentic coding agents。
目标是快速上手和正确使用 `pin_xie`，并在修改配置时保持行为可预期。

## 1) 仓库概览
- 语言：Python 3.11+
- 包管理：`setuptools`（见 `pyproject.toml`）
- 源码目录：`src/pin_xie/`
- 关键模块：
  - `api.py`：统一入口 `PinXieEngine`
  - `demo.py`：CLI 运行入口
  - `parser.py`：核心解析流程
  - `tokenizer.py`：中英文切词 + 掩码保留
  - `header.py`：基于 `parse_structure` 的头部解析
  - `template.py`：模板合并和参数提取

## 2) 如何运行（CLI）
在仓库根目录执行：

```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --config config/Config.toml
```

常用模式：

```bash
# 1) 只学习模板（不写逐行解析结果）
PYTHONPATH=src python -m pin_xie.demo /path/to/train.log --mode learn --template-dir ./cache

# 2) 只解析（读取已有模板，不更新模板）
PYTHONPATH=src python -m pin_xie.demo /path/to/infer.log --mode parse --template-dir ./cache

# 3) 学习 + 解析（默认）
PYTHONPATH=src python -m pin_xie.demo /path/to/your.log --mode learn_parse
```

如果已安装脚本入口，也可使用：

```bash
pin-xie-demo /path/to/your.log --config config/Config.toml
```

## 4) 如何运行（Python API）
推荐统一使用 `PinXieEngine`：

```python
from pin_xie import PinXieEngine, RunMode

engine = PinXieEngine.from_config_path("config/Config.toml")

# 学习模板
engine.run_file("/path/to/train.log", mode=RunMode.LEARN, template_dir="cache")

# 仅解析
report = engine.run_file("/path/to/infer.log", mode=RunMode.PARSE, template_dir="cache")
print(report.processed_lines)

# 单行流式处理
record = engine.process_line("2025/11/26 0:51,user1,文件 file9 下载成功", line_id=1)
print(record.cluster_id, record.template)
```

建议：
- 线上稳定解析场景优先用 `parse`，避免模型被新噪声污染。
- 数据迭代阶段可先 `learn` 再 `parse` 做离线验证。

## 5) 输出与缓存说明
- 逐行结果：`output/parsed_results.jsonl`
- 模板摘要：`output/templates.txt`
- 模板缓存：`cache/templates.json`（目录可改）

模式差异：
- `learn`：更新模板并写缓存，不写逐行解析输出
- `parse`：只读取缓存并解析，不更新模板
- `learn_parse`：一边学习一边解析，同时产出摘要与缓存

## 6) 配置文件编写说明（重点）
配置文件为 TOML，典型分区：
- `[spell]`
- `[tokenizer]`
- `[header]`
- `[header.field_patterns]`
- `[output]`

### 6.1 最小可用配置
如果日志没有独立头部，只保留 `<context>`：

```toml
[spell]
tau_ratio = 0.5

[tokenizer]
delimiters = '[ =,:()\[\]\t\n\r]+'
extra_delimiters = []
mask_patterns = []
use_jieba = true

[header]
parse_structure = '<context>'
strict_mode = false

[output]
dir = 'output'
parsed_file = 'parsed_results.jsonl'
template_file = 'templates.txt'
show_tokens = false
```

### 6.2 含头部字段的配置
示例日志：`2025/11/26 0:48,user1,验证用户 user1 对文件 file9 的访问权限`

```toml
[spell]
tau_ratio = 0.5

[tokenizer]
delimiters = '[ =,:()\[\]\t\n\r]+'
extra_delimiters = []
mask_patterns = [
  '\\d{4}/\\d{1,2}/\\d{1,2}\\s+(?:[01]?\\d|2[0-3]):[0-5]\\d',
  '(?:\\d{1,3}\\.){3}\\d{1,3}'
]
use_jieba = true

[header]
parse_structure = '<time>,<entity>,<context>'
strict_mode = false

[header.field_patterns]
time = '\\d{4}/\\d{1,2}/\\d{1,2}\\s+(?:[01]?\\d|2[0-3]):[0-5]\\d'
entity = '[\\p{L}\\p{N}_.@-]+'

[output]
dir = 'output'
parsed_file = 'parsed_results.jsonl'
template_file = 'templates.txt'
show_tokens = false
```

### 6.3 字段约束与行为
- `header.parse_structure` 必须包含 `<context>`，否则会报错。
- `header.field_patterns` 必须是 TOML table（键值映射）。
- `strict_mode = true`：日志不匹配结构时直接抛异常。
- `strict_mode = false`：不匹配时回退为整行作为 `context`。
- `tau_ratio` 越大，模板匹配越严格；越小，聚类更容易合并。
- `mask_patterns` 按给定顺序应用，建议“更具体”写在前面。

### 6.4 配置设计建议
- 若日志存在稳定头部字段（时间、实例、用户），优先拆到 `header`。
- `context` 保留语义正文，能提升模板聚类稳定性。
- 若 IP/时间戳被切碎，优先加入 `mask_patterns`。
- 先在小样本上调 `tau_ratio`，再跑全量日志。

## 7) 常用正则表达式备忘
以下模式可直接用于 `mask_patterns` 或 `header.field_patterns`。

- 日期（`YYYY/MM/DD`）：
  - `\\d{4}/\\d{1,2}/\\d{1,2}`
- 时间（`HH:MM`，24小时）：
  - `(?:[01]?\\d|2[0-3]):[0-5]\\d`
- 日期时间（到分钟）：
  - `\\d{4}/\\d{1,2}/\\d{1,2}\\s+(?:[01]?\\d|2[0-3]):[0-5]\\d`
- 日期时间（到秒）：
  - `\\d{4}[-/]\\d{1,2}[-/]\\d{1,2}\\s+(?:[01]?\\d|2[0-3]):[0-5]\\d:[0-5]\\d`
- IPv4：
  - `(?:\\d{1,3}\\.){3}\\d{1,3}`
- 用户/实体标识（字母数字下划线点@横杠）：
  - `[\\p{L}\\p{N}_.@-]+`
- UUID（v1-v5 宽松）：
  - `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}`
- 整数或小数：
  - `-?\\d+(?:\\.\\d+)?`
- 文件路径（宽松）：
  - `(?:[A-Za-z]:\\\\|/)?(?:[^\\s/]+/)*[^\\s/]+`
- 日志级别：
  - `(?:DEBUG|INFO|WARN|WARNING|ERROR|FATAL|TRACE)`

使用注意：
- TOML 字符串建议用单引号包裹正则，减少转义噪音。
- 若写在 Python 字符串中，反斜杠需要再次转义。
- 正则过宽会导致误匹配，优先从严格版本开始。

## 8) 维护和改动原则
- 优先保持 `PinXieEngine` API 稳定。
- 保持模式字符串兼容：`learn_parse`、`learn`、`parse`。
- 非必要不改 `templates.json` 结构；若改动需同步文档说明。
- 修改解析策略时，优先给出迁移建议和配置示例。
