# WU02：文本匹配算法适配

## 1. 目标

将 LCS、Trie 和候选过滤适配到富 Token，同时严格保持现有匹配、阈值和决胜语义；来源和变量名不得影响结果。

## 2. 依赖

WU01、WU03 已验收。以 WU03 落地后的对象化 `LCSObject` 为唯一接口，不得复制另一套模型或增加旧 `str | None` 兼容分支。

## 3. 开始前只需阅读

1. `docs/plan/exec/rich-template-token-structure-execution.md`
2. 本文件
3. `src/pin_xie/models.py`
4. `src/pin_xie/lcs.py`
5. `src/pin_xie/similarity.py`
6. `src/pin_xie/trie.py`
7. `src/pin_xie/cluster.py` 中 `LCSObject` 的当前接口

## 4. 范围

### 修改

- `src/pin_xie/lcs.py`
- `src/pin_xie/similarity.py`
- `src/pin_xie/trie.py`

### 新增或更新

- `tests/test_rich_token_algorithms.py`

### 排除

- 不修改模板合并和簇字段；WU03 负责；
- 不修改 Parser 主流程；WU04 负责；
- 不调整任何算法阈值、复杂度策略或候选决胜规则；
- 不保留 `str` 输入兼容分支。

## 5. 实现要求

1. 使用 `models.py` 的统一访问函数，不在三个算法模块中重复检查 `kind` 或直接读取联合对象字段。
2. `lcs()` 接收模板 Token 序列和输入 Token 序列：
   - 只允许字面量模板 Token 与相同 `text` 的输入 Token 匹配；
   - 变量 Token 保持通配槽语义，但不直接与任何输入 Token 相等；
   - 返回的公共子序列继续是文本序列，供模板合并按文本定位；
   - 保持当前动态规划和相等时模板方向优先的回溯行为。
3. `jaccard_filter()` 从输入 Token 的 `text` 构造集合，继续使用 `|intersection| > len(tokens) / 2`。不要把它改成标准 Jaccard。
4. Trie 插入只索引字面量模板 Token 的 `text`；匹配只扫描输入 Token 的 `text`。
5. Trie 的最小常量数、候选优先级和较短模板决胜规则保持不变。

## 6. 测试要求

使用相同文本、不同来源和变量名构造对照测试，至少证明：

- LCS 长度和回溯文本不变；
- 变量 Token 不匹配输入 Token；
- Trie 插入和命中忽略来源；
- 候选过滤忽略来源；
- 重复 Token 阈值仍使用输入 Token 总数；
- Trie 候选决胜规则未改变。

测试直接使用 WU03 已落地的对象化 `LCSObject`，不得扩写或绕过 cluster 接口。

## 7. 验证

```bash
ruff check src/pin_xie/lcs.py src/pin_xie/similarity.py src/pin_xie/trie.py tests/test_rich_token_algorithms.py
basedpyright src/pin_xie/lcs.py src/pin_xie/similarity.py src/pin_xie/trie.py
pytest -q tests/test_rich_token_algorithms.py
```

此时 `parser.py` 尚未适配新的算法签名，全量测试可能失败。只运行上述聚焦验证，记录已知中间失败，不得修改 Parser；WU04 负责恢复主流程。

## 8. 验收标准

- 三种算法仅依据文本和变量类型工作；
- 来源、mask 名称、变量名称不改变匹配结果；
- 未改变设计文档明确要求保持的算法语义；
- 验证通过且无范围外改动。

## 9. 完成报告

报告签名变化、保持不变的算法语义、测试与验证结果。不要提交代码。
