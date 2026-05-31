# `build_sequence_training_csv.py` 逻辑解释与使用说明

## 1. 这个脚本做什么

`scripts/build_sequence_training_csv.py` 用于把带攻击标签的结构化日志 CSV 转换成序列级训练数据 CSV。

它的核心目标是：

1. 按 `host` 将连续日志划分为一条日志序列；
2. 使用 Pin Xie 解析日志内容并生成 `cluster_id`，作为输出的 `event_col`；
3. 根据序列中是否存在攻击日志，生成三分类 `label`；
4. 跳过 `technique == "T1070" 以及 "T1550"` 的日志输出，但保留其对序列异常判断、攻击名收集、模板训练的影响；
5. 训练后保存日志模板，后续可直接加载模板解析，避免重新训练。

---

## 2. 输入与输出格式

### 2.1 输入 CSV 默认字段

默认输入字段如下：

```csv
host,content,is_attack,attack_type,technique,tactic,attack_name
```

脚本实际依赖的字段是：

| 字段 | 作用 |
|---|---|
| `host` | 序列实体，同一个连续 `host` 视为一条序列 |
| `content` | 日志正文，送入 Pin Xie 生成 `cluster_id` |
| `is_attack` | 是否攻击日志，支持 `true/false`、`1/0`、`yes/no` 等 |
| `technique` | MITRE technique；值为 `T1070` 时不输出该行 |
| `attack_name` | 攻击名称，用于异常序列的 `attack_name` 输出 |

> 注意：脚本假设同一条序列在输入文件中是连续出现的。如果同一个 `host` 分散在文件不同位置，脚本会把它们当作多条不同序列。别让数据像没拴绳的哈士奇一样到处乱跑。

### 2.2 输出 CSV 字段

默认输出字段如下：

```csv
entity_col,event_col,content,label,attack_name
```

| 输出字段 | 来源或规则 |
|---|---|
| `entity_col` | 输入的 `host` |
| `event_col` | Pin Xie 生成的 `cluster_id` |
| `content` | 输入的 `content` 原样输出 |
| `label` | 根据序列级异常规则生成 |
| `attack_name` | 异常序列中的攻击名 JSON 数组；正常序列为空 |

---

## 3. 核心逻辑

### 3.1 序列划分

脚本按输入文件中的连续 `host` 划分序列。

例如：

```csv
host,content,...
A,日志1,...
A,日志2,...
B,日志3,...
B,日志4,...
A,日志5,...
```

会被划分为三条序列：

1. `A`: 日志1、日志2
2. `B`: 日志3、日志4
3. `A`: 日志5

脚本不会把第一段 `A` 和最后一段 `A` 合并。

### 3.2 事件 ID 生成

每一行日志都会调用：

```python
engine.process_line(content, line_id=row_number, update_model=...)
```

返回结果中的：

```python
record.cluster_id
```

会作为输出的 `event_col`。

默认配置使用：

```text
config/Config.toml
```

其中 `parse_structure = '<context>'`，因此脚本只把 `content` 传给 Pin Xie，不额外拼接时间或实体字段。

### 3.3 label 生成规则

脚本先判断整条序列是否异常：

- 如果序列中至少存在一条 `is_attack == true` 的日志，则该序列是异常序列；
- 否则是正常序列。

然后逐行生成 label：

| 场景 | label |
|---|---:|
| 正常序列中的正常日志 | `0` |
| 异常序列中的攻击日志 | `1` |
| 异常序列中的正常日志 | `2` |

### 3.4 attack_name 生成规则

如果是正常序列：

```csv
attack_name

```

即输出为空。

如果是异常序列，脚本会收集序列中所有攻击日志的 `attack_name`，去重并保留首次出现顺序，然后写成 JSON 数组字符串。

例如同一序列中出现：

```text
Multiple repeated login attempts
Clear logs
Multiple repeated login attempts
```

输出为：

```json
["Multiple repeated login attempts", "Clear logs"]
```

写入 CSV 后通常会显示为：

```csv
"[""Multiple repeated login attempts"", ""Clear logs""]"
```

这是 CSV 对引号的正常转义，不是脚本抽风。

### 3.5 `T1070` 特殊处理

当某行日志满足：

```text
technique == "T1070"
```

该行不会写入输出 CSV。

但是它仍然会参与：

1. Pin Xie 模板训练或模板匹配；
2. 判断该序列是否异常；
3. 收集异常序列的 `attack_name`；
4. 影响同序列其他日志的 label。

也就是说，`T1070` 只是“不输出”，不是“不存在”。

---

## 4. 模板保存与复用逻辑

### 4.1 默认训练并保存模板

默认情况下，脚本会在处理日志时更新 Pin Xie 模型。

处理结束后会保存模板缓存：

```text
cache/sequence_training/templates.json
```

同时保存一份可读模板摘要：

```text
output/key_logs_sequence_templates.txt
```

模板缓存用于后续 `--parse-only` 调用；模板摘要主要给人查看。

### 4.2 直接加载模板，不重新训练

使用 `--parse-only` 后，脚本会：

1. 从 `--template-dir` 加载 `templates.json`；
2. 调用 Pin Xie 时设置 `update_model=False`；
3. 不新增模板；
4. 不更新已有模板；
5. 不重新保存模板缓存。

这适合训练集先生成模板，然后验证集、测试集或线上数据复用同一套模板。

---

## 5. 常用命令

### 5.1 基本运行

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/your_input.csv \
  --output output/key_logs_sequence_training.csv
```

默认会：

- 使用 `config/Config.toml`；
- 训练 Pin Xie 模板；
- 输出训练 CSV；
- 保存模板缓存到 `cache/sequence_training/templates.json`；
- 保存模板摘要到 `output/key_logs_sequence_templates.txt`。

### 5.2 指定模板目录

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/train.csv \
  --output output/train.csv \
  --template-dir cache/my_templates
```

模板缓存会保存到：

```text
cache/my_templates/templates.json
```

### 5.3 使用已有模板解析，不重新训练

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/test.csv \
  --output output/test.csv \
  --template-dir cache/my_templates \
  --parse-only
```

要求：

```text
cache/my_templates/templates.json
```

必须已经存在。

### 5.4 训练但不保存模板缓存

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/train.csv \
  --output output/train.csv \
  --no-save-template-cache
```

### 5.5 关闭模板摘要输出

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/train.csv \
  --output output/train.csv \
  --template-summary ''
```

### 5.6 指定模板摘要路径

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/train.csv \
  --output output/train.csv \
  --template-summary output/my_templates.txt
```

### 5.7 只处理前 N 行

```bash
python scripts/build_sequence_training_csv.py \
  --input examples/train.csv \
  --output output/sample.csv \
  --max-rows 100
```

---

## 6. 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--input` | `examples/key_logs_sequence_labeled.csv` | 输入 CSV 路径 |
| `--output` | `output/key_logs_sequence_training.csv` | 输出 CSV 路径 |
| `--config` | `config/Config.toml` | Pin Xie 配置路径 |
| `--host-col` | `host` | 输入实体列名 |
| `--content-col` | `content` | 输入日志正文列名 |
| `--is-attack-col` | `is_attack` | 输入攻击标记列名 |
| `--technique-col` | `technique` | 输入 technique 列名 |
| `--attack-name-col` | `attack_name` | 输入攻击名称列名 |
| `--output-entity-col` | `entity_col` | 输出实体列名 |
| `--output-event-col` | `event_col` | 输出事件列名 |
| `--output-content-col` | `content` | 输出正文列名 |
| `--output-label-col` | `label` | 输出标签列名 |
| `--output-attack-name-col` | `attack_name` | 输出攻击名称列名 |
| `--event-prefix` | 空字符串 | 给 `event_col` 增加前缀，例如 `E` |
| `--template-dir` | `cache/sequence_training` | 模板缓存保存或加载目录 |
| `--template-summary` | `output/key_logs_sequence_templates.txt` | 模板摘要路径；传入 `''` 可关闭 |
| `--parse-only` | `False` | 加载已有模板，不重新训练 |
| `--no-save-template-cache` | `False` | 训练后不保存模板缓存 |
| `--max-rows` | `None` | 只处理前 N 行 |

---

## 7. 示例

### 7.1 输入示例

```csv
host,content,is_attack,attack_type,technique,tactic,attack_name
user-host-01,用户 purplecat0 请求登录系统,false,,,,
user-host-01,验证用户 purplecat0 的凭据,false,,,,
user-host-09,用户 muscularfox15 发生重复登录尝试,true,multiple_login_attempts,T1110,credential_access,Multiple repeated login attempts
user-host-09,清除登录痕迹,true,clear_logs,T1070,defense_evasion,Clear logs
user-host-09,验证用户 muscularfox15 的凭据,false,,,,
```

### 7.2 输出示例

实际 `event_col` 取决于 Pin Xie 聚类结果，下面只展示形式：

```csv
entity_col,event_col,content,label,attack_name
user-host-01,0,用户 purplecat0 请求登录系统,0,
user-host-01,1,验证用户 purplecat0 的凭据,0,
user-host-09,2,用户 muscularfox15 发生重复登录尝试,1,"[""Multiple repeated login attempts"", ""Clear logs""]"
user-host-09,1,验证用户 muscularfox15 的凭据,2,"[""Multiple repeated login attempts"", ""Clear logs""]"
```

其中：

- `清除登录痕迹` 对应 `T1070`，因此没有输出；
- 但它的 `attack_name = Clear logs` 被收集进同序列其他日志的 `attack_name`；
- `user-host-09` 序列中存在攻击日志，因此正常日志 `验证用户 muscularfox15 的凭据` 被标记为 `label = 2`。

---

## 8. 注意事项

1. 输入必须有表头。
2. 同一序列必须在文件中连续出现。
3. `is_attack` 字段如果不是可识别的布尔值，脚本会报错。
4. `--parse-only` 要求模板缓存已存在，否则会报错。
5. 若训练集和测试集使用不同的 Pin Xie 配置，模板匹配结果可能不可靠。
6. `event_col` 是模板聚类 ID，不是原始日志行号，也不是序列内编号。
