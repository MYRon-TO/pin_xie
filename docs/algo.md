# Pin Xie 核心算法

## 1. 处理链

Pin Xie 按 Spell 思路在线处理日志：物理行先按 `input.mode` 组装为逻辑日志，Header 解析器分离字段与 `context`，随后依次执行分词、Trie 快速匹配、固定 Token 交集过滤、LCS 精确匹配、模板合并或建簇，最后提取参数。只有 `context` 参与聚类。

单行模式跳过纯空白行；多行模式由完整匹配 Header 的行划分记录，续行（包括空行和缩进）原样归入当前记录。多行边界不使用异常栈或缩进启发式。

## 2. 富 Token 数据模型

模型定义位于 `src/pin_xie/models.py`：

- `InputToken(text, source)` 表示本次输入；来源是 `PlainTokenSource`，或携带具名规则 `mask_name` 的 `RegexTokenSource`。
- `LiteralTemplateToken(text, sources)` 表示固定文本。
- `VariableTemplateToken(var_name, sources)` 表示变量槽及其身份。
- `ParameterCapture(template_token_index, var_name, value, sources)` 表示一次匹配捕获的参数。

模板 Token 的 `sources` 是累计来源：构造和合并时去重，稳定顺序为 `plain` 在前、随后按 `mask_name` 字典序排列正则来源。变量名直接存储在变量模板 Token 上，并在簇内唯一；默认名称取当前簇最小可用的 `var_N`。模板变量冲突合并时生成新的可用默认名。

参数来源只取本次被捕获的输入 Token，不能用模板的累计来源代替。一个槽捕获多个 Token 时，参数值以空格拼接。

## 3. 分词与具名 Mask

`LogTokenizer` 先按 `tokenizer.mask_patterns` 的配置顺序匹配具名正则；同一位置有多个候选时前者优先，命中片段作为单个正则来源 Token，不再被分隔符或 jieba 拆分。其余文本按 `delimiters` 和 `extra_delimiters` 粗切，再按 ASCII、Unicode Han 和其他字符处理；`use_jieba=false` 时 Han 字符逐字切分。

每个输入 Token 都有且只有一个本次来源。mask 名称用于来源追踪，不用于推断值类型。

## 4. 文本匹配

算法访问富对象时只读取文本：输入 Token 比较 `text`，字面量模板 Token 比较 `text`，变量模板 Token 不与输入文本相等。**来源、来源顺序和变量名均不参与 Trie、候选过滤、LCS 或相似度计算。**

对输入长度 `n`，接受阈值为 `n=0` 时 0，否则 `max(1, floor(n * tau_ratio))`。

1. Trie 仅索引模板的字面量文本，并判断这些文本能否作为输入的子序列出现；候选仍需通过 LCS 阈值。Trie 快路径命中时学习模式只增加簇计数，不合并模板。
2. 快路径失败后，`jaccard_filter` 实际使用固定 Token 集合交集条件 `|S_X ∩ S_C| > n/2`，并非标准 Jaccard。
3. 对候选执行标准动态规划 LCS；优先 LCS 更长的簇，再优先模板更短的簇。

## 5. 模板生命周期与来源

新簇把输入 Token 转成带单一来源的字面量模板 Token。LCS 路径合并时，共同字面量保留并合并旧、新来源；差异区间变成变量 Token，其来源是该区间旧模板和本次输入来源的并集。相邻变量压缩为一个并合并来源。更新后同步 `token_set` 并重建 Trie。

模板渲染时字面量输出文本，变量输出 `<VAR:名称>`。只解析模式不更新模板；未匹配时返回 `cluster_id=-1`、空模板和空参数。

## 6. 输出与缓存

`ParsedRecord` 保留富 `template_tokens`、`parameters` 和输入 `tokens`。JSONL 使用显式对象序列化：模板 Token 包含 `kind` 与 `sources`，参数包含模板位置、名称、值和本次来源；`output.show_tokens=true` 时额外输出输入 Token 对象数组，否则省略 `tokens`。模板摘要输出渲染模板、变量位置及累计来源。

缓存格式为 v4，模板变量身份随 `VariableTemplateToken.var_name` 保存。缓存包含 input、header、learning 和完整 tokenizer 配置；加载兼容性比较 input/header 与 tokenizer 的 `delimiters`、`extra_delimiters`、具名 mask（包括顺序）和 `use_jieba`，learning 仅作为训练元数据保存。v1、v2、v3 严格拒绝且不迁移；任何校验失败都不会替换当前模型。

## 7. 学习模式

- `learn`：加载可选缓存并更新模型，不写逐条解析结果。
- `parse`：要求并加载缓存，只匹配、不更新。
- `learn_parse`：学习并输出；启用 shuffle 时先按种子打乱完整逻辑日志学习，再按原输入顺序只解析。

shuffle 的单位是已组装的逻辑日志，不改变记录内部物理行顺序。

## 8. 实现位置

| 模块 | 职责 |
|---|---|
| `models.py` | 富 Token、来源、参数及显式序列化 |
| `tokenizer.py` | 具名 mask、分隔与中文增强分词 |
| `template.py` | 创建、合并、变量压缩、参数提取与渲染 |
| `cluster.py` | 模板簇状态和变量名操作 |
| `trie.py` / `similarity.py` / `lcs.py` | 文本匹配算法 |
| `parser.py` | 聚类主流程和缓存状态校验 |
| `api.py` | 组装、Header 集成、运行模式、JSONL、摘要及缓存文件 |
| `multiline.py` / `header.py` | 逻辑日志组装与 Header 解析 |
