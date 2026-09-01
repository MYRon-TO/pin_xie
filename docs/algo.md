# Pin Xie 核心算法

## 1. 算法定位

Pin Xie 是一个面向中文及中英文混合日志的在线日志模板解析器。核心聚类过程继承 Spell 的思路：将日志正文转换为 Token 序列，通过前缀树快速匹配已有模板；快路径未命中时，先过滤候选簇，再使用最长公共子序列（Longest Common Subsequence，LCS）选择模板；最后在线更新模板并提取变量参数。

当前实现的完整处理链如下：

```text
物理行
  -> 单行/多行逻辑日志组装
  -> Header 字段与 context 分离
  -> context 分词
  -> Trie 快速匹配
  -> 候选重叠过滤
  -> LCS 精确匹配
  -> 模板合并或新建模板簇
  -> 参数提取与结果渲染
```

其中，Spell 聚类器只处理 `context`。时间、级别、线程等 Header 字段不参与模板聚类。

## 2. 核心数据模型

### 2.1 日志 Token 序列

一条逻辑日志的正文表示为：

```text
X = [x_1, x_2, ..., x_n]
```

`n` 是本条日志的 Token 数量。

### 2.2 模板与变量槽位

模板表示为 `list[str | None]`：

- 字符串：模板中的固定 Token；
- `None`：一个变量槽位；
- 连续的多个变量槽位会被压缩为一个槽位。

例如，内部模板：

```python
["用户", None, "登录", "成功"]
```

对外渲染为：

```text
用户 <VAR:var_0> 登录 成功
```

变量槽位可以人工命名，例如将 `var_0` 命名为 `username` 后，模板渲染为 `<VAR:username>`。

### 2.3 模板簇

每个模板簇 `LCSObject` 保存：

| 字段 | 含义 |
|---|---|
| `cluster_id` | 单调递增的模板簇编号 |
| `template_tokens` | 当前模板 Token 序列 |
| `line_ids` | 学习阶段归入该簇的逻辑日志起始行号 |
| `size` | 已归入该簇的日志数量 |
| `token_set` | 模板中不重复的固定 Token 集合，不包含变量槽位 |
| `variable_names` | 变量槽位序号到业务名称的映射 |

`constant_token_count` 在当前代码中等于 `len(token_set)`，因此它统计的是不重复固定 Token 数量，不是模板中固定 Token 的位置数量。

## 3. 输入预处理

### 3.1 逻辑日志组装

输入模式由 `[input].mode` 明确指定。

#### 单行模式

- 每个非空物理行构成一条逻辑日志；
- 纯空白行被跳过；
- 仅移除行终止符，保留非空行的首尾空白；
- `line_id` 与 `end_line_id` 相同。

#### 多行模式

- 完整匹配 Header 格式的物理行开始一条新日志；
- 后续非 Header 行均作为当前日志的续行；
- 空行和缩进原样保留；
- 遇到下一个 Header 或文件结束时输出当前逻辑日志；
- 第一条 Header 前出现任何物理行都会导致组装错误；
- 组装后的行统一使用 `\n` 连接。

多行边界仅由 Header 完整匹配决定，不分析缩进、异常栈语法或续行特征。因此，损坏的 Header 可能被归入上一条日志，正文中符合 Header 格式的行也可能被误判为新日志。

### 3.2 Header 与正文分离

`RegexHeaderParser` 根据 `header.parse_structure` 解析完整逻辑日志。例如：

```toml
[header]
parse_structure = '<time> <level> <context>'

[header.field_patterns]
time = '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
level = 'DEBUG|INFO|WARN|ERROR|FATAL'
```

输入：

```text
2026-03-20 10:00:00 ERROR 用户张三登录失败
```

解析结果：

```text
time    = 2026-03-20 10:00:00
level   = ERROR
context = 用户张三登录失败
```

只有 `context` 进入 Spell 聚类过程。这样可以避免时间、级别等高变化字段干扰模板相似度计算。

## 4. 中文增强分词

`LogTokenizer` 按以下顺序处理正文。

### 4.1 Mask 优先保留

配置的 `mask_patterns` 先在原文中匹配。命中的完整文本直接作为一个 Token，不再被普通分隔符或中文分词拆开。该机制适合保护时间、IP 地址等结构化值。

多个 Mask 正则按配置顺序组合。当不同规则可以从同一位置匹配时，靠前规则优先。

### 4.2 分隔符粗切分

未被 Mask 覆盖的文本先按以下规则切分：

- `tokenizer.delimiters`；
- `tokenizer.extra_delimiters`。

默认基础分隔符包括空格、等号、逗号、冒号、括号、方括号、制表符和换行符。

### 4.3 中英文混合切分

粗切分后的非 ASCII 文本继续识别：

- Unicode Han 字符串；
- 英文标识符；
- 整数或点分数字；
- 其他单个非空白字符。

含 Han 字符的片段：

- `use_jieba = true`：使用 `jieba.cut(..., HMM=True)`；
- `use_jieba = false`：按单个 Han 字符切分。

纯 ASCII 粗切分片段保持为单个 Token，不再按内部标点二次切分。因此，分隔符配置会直接影响聚类粒度。

## 5. 在线聚类算法

### 5.1 匹配阈值

对长度为 `n` 的输入 Token 序列，LCS 接受阈值为：

```text
tau(n) = 0                                      , n = 0
tau(n) = max(1, floor(n * tau_ratio))           , n > 0
```

配置项为 `[spell].tau_ratio`。`SpellParser` 类的默认值是 `0.5`，项目默认配置当前使用 `0.75`。

`tau_ratio` 越大，聚类越严格，通常会产生更多模板簇；越小，模板越容易合并，也更容易把不同事件归入同一簇。

### 5.2 Trie 快速匹配

前缀树只索引模板中的固定 Token，变量槽位被忽略。例如：

```text
模板：用户 <VAR> 登录 成功
索引路径：用户 -> 登录 -> 成功
```

匹配时，输入 Token 按顺序扫描。搜索状态既可以停留在当前节点，也可以沿匹配 Token 向下移动，因此 Trie 实际判断的是：模板固定 Token 序列能否作为输入序列的一个子序列出现，而不是只匹配输入前缀。

Trie 候选还必须满足：

```text
cluster.constant_token_count >= ceil(n * tau_ratio)
```

如果有多个候选，依次使用以下规则选择：

1. 不重复固定 Token 数量更多者优先；
2. 数量相同时，模板 Token 总长度更短者优先。

选出 Trie 候选后，算法仍会计算一次 LCS。只有 `LCS长度 >= tau(n)` 才接受该候选。

Trie 命中后的当前行为是：

- 学习模式只增加模板簇的行号和计数；
- 不执行模板合并；
- 直接基于现有模板提取参数并返回。

因此，Trie 快路径是匹配路径，不是模板更新路径。若输入包含现有模板未表达的额外 Token，而现有模板又没有对应变量槽位，这些 Token 不会在该次快路径命中时被加入模板。

### 5.3 候选重叠过滤

Trie 未命中或未通过 LCS 校验时，算法遍历现有模板簇，使用固定 Token 集合过滤候选。

设：

```text
S_X = set(X)
S_C = 模板簇 C 的固定 token_set
```

当前候选条件为：

```text
|S_X ∩ S_C| > n / 2
```

需要注意：代码函数名是 `jaccard_filter`，但当前条件不是标准 Jaccard 相似度：

```text
J(A, B) = |A ∩ B| / |A ∪ B|
```

项目虽然提供了 `jaccard_similarity()`，主聚类流程并未调用它。当前实现准确地说是“固定 Token 交集过滤”。此外，条件右侧使用输入 Token 总数 `n`，而不是 `|S_X|`；重复 Token 会提高过滤阈值。

### 5.4 LCS 精确匹配

对每个过滤后的候选模板 `T`，计算：

```text
LCS(T, X)
```

变量槽位 `None` 不会与任何输入字符串 Token 相等，因此 LCS 只由固定 Token 构成。

LCS 使用标准动态规划：

```text
dp[i][j] = dp[i-1][j-1] + 1                    , T[i-1] == X[j-1]
dp[i][j] = max(dp[i-1][j], dp[i][j-1])         , 其他情况
```

算法同时回溯得到一条具体的 LCS Token 序列，供后续模板合并使用。当两个回溯方向长度相等时，当前实现优先在模板方向回退。

候选簇选择规则为：

1. LCS 长度最大者优先；
2. LCS 长度相同时，模板 Token 总长度更短者优先；
3. 最佳 LCS 长度必须不小于 `tau(n)`；
4. 若仍完全相同，保留模板簇遍历顺序中较早的簇。

### 5.5 模板合并

学习模式下，LCS 路径命中模板簇后，算法以旧模板、当前输入和两者的 LCS 为基础生成新模板。

规则如下：

1. LCS 中的固定 Token 保留；
2. 两个相邻 LCS Token 之间，只要旧模板或新输入存在差异，就插入一个变量槽位；
3. LCS 前后的差异同样变为变量槽位；
4. 相邻变量槽位压缩为一个；
5. 如果不存在公共 Token，模板退化为单个变量槽位。

示例：

```text
旧模板：用户 张三 登录 成功
新输入：用户 李四 登录 成功
LCS：   用户      登录 成功
新模板：用户 <VAR> 登录 成功
```

模板更新后会同步更新 `token_set`，并使用全部模板簇重建 Trie。模板合并只会保留固定部分或将差异泛化为变量，不会把已有变量重新特化为固定 Token。

### 5.6 新建模板簇

满足以下任一情况时，没有可用模板簇：

- Trie 无有效命中；
- 重叠过滤后没有候选；
- 最佳候选的 LCS 长度小于阈值。

学习模式会以当前完整 Token 序列创建新簇，并将其固定 Token 路径插入 Trie。

只解析模式不会创建模板簇，而是返回：

```text
cluster_id = -1
template_tokens = []
parameters = []
```

## 6. 参数提取

参数提取在模板匹配或更新完成后执行。算法从左到右对齐输入与模板：

- 固定 Token 用于定位；
- 变量槽位捕获当前位置到下一个固定 Token 之前的全部输入 Token；
- 尾部变量槽位捕获剩余 Token；
- 一个槽位捕获的多个 Token 使用空格连接。

示例：

```text
模板：用户 <VAR:username> 从 <VAR:ip> 登录
输入：用户 张三 从 10.0.0.8 登录
参数：["张三", "10.0.0.8"]
命名参数：{"username": "张三", "ip": "10.0.0.8"}
```

参数来自分词结果，不保留原始分隔符。若固定 Token 在输入中重复，当前实现总是从当前位置向后选择第一个可用位置。

## 7. 算法伪代码

```text
function PROCESS(context, line_id, update_model):
    X = TOKENIZE(context)
    tau = THRESHOLD(length(X), tau_ratio)

    # 快路径
    cluster = TRIE_MATCH(X, tau_ratio)
    if cluster exists:
        lcs_len = LCS_LENGTH(cluster.template, X)
        if lcs_len >= tau:
            params = EXTRACT_PARAMETERS(X, cluster.template)
            if update_model:
                cluster.add_line(line_id)
            return result(cluster, cluster.template, params, X)

    # 精确路径
    candidates = [
        C for C in all_clusters
        if size(C.token_set intersect set(X)) > length(X) / 2
    ]
    cluster = ARG_MAX_BY_LCS(candidates, X)

    if cluster exists and LCS_LENGTH(cluster.template, X) >= tau:
        if update_model:
            common = LCS_TOKENS(cluster.template, X)
            cluster.template = MERGE(cluster.template, X, common)
            cluster.add_line(line_id)
            REBUILD_TRIE(all_clusters)
        params = EXTRACT_PARAMETERS(X, cluster.template)
        return result(cluster, cluster.template, params, X)

    if not update_model:
        return unmatched_result(X)

    cluster = CREATE_CLUSTER(template=X, line_id=line_id)
    TRIE_INSERT(cluster)
    return result(cluster, X, [], X)
```

## 8. 完整示例

假设：

```text
tau_ratio = 0.75
```

并假设分词结果如下。

### 8.1 第一条日志

```text
X1 = [用户, 张三, 登录, 成功]
tau = floor(4 * 0.75) = 3
```

当前没有模板簇，因此创建：

```text
C0 = [用户, 张三, 登录, 成功]
```

### 8.2 第二条日志

```text
X2 = [用户, 李四, 登录, 成功]
```

Trie 路径因固定 Token `张三` 不匹配而无法到达终止节点。

重叠过滤：

```text
|set(X2) ∩ C0.token_set| = 3 > 4 / 2
```

LCS：

```text
[用户, 登录, 成功]
```

LCS 长度为 3，达到阈值，模板更新为：

```text
C0 = [用户, <VAR>, 登录, 成功]
```

提取参数：

```text
[李四]
```

### 8.3 第三条日志

```text
X3 = [用户, 王五, 登录, 成功]
```

Trie 索引路径为：

```text
用户 -> 登录 -> 成功
```

该路径是 `X3` 的子序列，且固定 Token 数量达到阈值，因此 Trie 快路径命中。参数为：

```text
[王五]
```

模板保持不变，只增加模板簇计数。

## 9. 学习模式与解析模式

核心算法由 `update_model` 控制：

| 行为 | `update_model = true` | `update_model = false` |
|---|---:|---:|
| 匹配已有模板 | 是 | 是 |
| 更新模板 | 是，但 Trie 快路径不合并 | 否 |
| 增加簇计数与行号 | 是 | 否 |
| 创建新模板簇 | 是 | 否 |
| 未匹配时返回 `cluster_id = -1` | 否 | 是 |

CLI 模式对应关系：

- `learn`：学习模板，不写逐条解析结果；
- `parse`：加载模板，只解析，不更新模型；
- `learn_parse`：边学习边解析。

`run_file()` 可通过 `[learning].shuffle` 随机化学习顺序。打乱单位是 Header 组装完成后的逻辑日志，不是物理行。`LEARN` 按随机顺序更新模型；`LEARN_PARSE` 先随机学习，再按原始顺序以 `update_model = false` 解析。`PARSE` 与 `process_lines()` 始终保持输入顺序。随机化使用局部随机数生成器和可选 `random_seed`，不修改全局随机状态。

## 10. 复杂度

设：

- `n`：输入 Token 数量；
- `m`：候选模板 Token 数量；
- `C`：模板簇总数；
- `K`：重叠过滤后的候选簇数量；
- `V`：Trie 节点数量。

主要复杂度如下：

| 阶段 | 时间复杂度 | 空间复杂度 | 说明 |
|---|---:|---:|---|
| 分词 | 与文本长度相关 | 与 Token 数相关 | 启用 jieba 时还取决于分词实现 |
| Trie 匹配 | 常见情况低于遍历全部簇；最坏可达 `O(nV)` | `O(V)` | 当前实现保留多个子序列匹配状态 |
| 重叠过滤 | 约 `O(C * 集合求交代价)` | `O(n + K)` | 需要检查全部模板簇 |
| 单次 LCS | `O(mn)` | `O(mn)` | 保存完整动态规划矩阵 |
| 候选 LCS | `O(Kmn)` | `O(mn)` | 各候选顺序计算 |
| 模板合并 | `O(m+n)` | `O(m+n)` | 基于已回溯的 LCS |
| Trie 重建 | 与全部模板固定 Token 总数相关 | 与 Trie 大小相关 | 每次 LCS 路径更新模板后全量重建 |

模板簇较多或日志较长时，主要成本来自候选过滤后的多次 LCS，以及模板更新后的 Trie 全量重建。

启用 `run_file()` 的学习打乱后，需要保存全部逻辑日志，额外空间复杂度为 `O(N)`；未启用时仍保持流式处理。

## 11. 与基础 Spell 思路的关系

项目保留了以下 Spell 核心特征：

- 在线、单遍处理日志；
- 基于 LCS 判断日志与模板的相似性；
- 模板随输入持续泛化；
- 使用前缀树加速常见匹配；
- 未匹配日志形成新模板簇。

当前项目的主要增强包括：

1. 使用 Unicode Han 识别和 jieba 支持中文分词；
2. 使用 Mask 规则保护时间、IP 等结构化 Token；
3. 将 Header 字段与参与聚类的 `context` 解耦；
4. 在 LCS 前增加固定 Token 交集过滤；
5. 支持单行和基于 Header 的多行逻辑日志组装；
6. 支持变量槽位命名、模板缓存及学习/解析模式分离。

本文描述的是当前代码的实际行为，不等同于 Spell 论文或其他 Spell 实现的逐项复刻。

## 12. 实现位置

| 模块 | 职责 |
|---|---|
| `src/pin_xie/api.py` | 输入组装后的整体处理、Header 解析、结果生成 |
| `src/pin_xie/multiline.py` | 单行与多行逻辑日志组装 |
| `src/pin_xie/header.py` | Header 边界识别与字段提取 |
| `src/pin_xie/tokenizer.py` | Mask、分隔符及中文增强分词 |
| `src/pin_xie/parser.py` | Trie、候选过滤、LCS、合并或新建簇的主流程 |
| `src/pin_xie/trie.py` | 固定 Token 子序列前缀树 |
| `src/pin_xie/similarity.py` | 集合相似度及当前候选交集过滤 |
| `src/pin_xie/lcs.py` | LCS 动态规划与回溯 |
| `src/pin_xie/template.py` | 模板合并、变量槽位、参数提取与渲染 |
| `src/pin_xie/cluster.py` | 模板簇状态 |
