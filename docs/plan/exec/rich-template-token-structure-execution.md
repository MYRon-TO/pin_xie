# 富模板 Token 数据结构重构：执行总计划

## 1. 计划依据

- 设计文档：`docs/plan/rich-template-token-structure.md`
- 架构说明：`docs/algo.md`
- 本计划只覆盖设计文档已确定的范围，不提供旧缓存或旧 JSONL 兼容。

## 2. 已批准的实现决策

1. 新增 `src/pin_xie/models.py`，集中定义来源、输入 Token、模板 Token、参数对象及其内部访问、规范化和显式序列化函数，避免 `config.py`、`tokenizer.py`、`template.py`、`parser.py` 之间形成循环依赖。
2. 数据模型使用 dataclass，并以 `kind` 构成可判别联合。来源和 `MaskPattern` 使用不可变值语义；模板 Token 的 `sources` 使用不可变 tuple。
3. 来源规范顺序为 `plain` 在前，随后按 `mask_name` 字典序排列 `regex` 来源。所有构造、合并、缓存和 JSONL 输出都先去重并采用该顺序。
4. 算法访问统一通过 `models.py` 内部辅助函数完成：输入 Token 比较 `text`，字面量模板 Token 比较 `text`，变量模板 Token不参与文本相等匹配。
5. 默认变量名采用当前簇内最小可用的 `var_N`。变量槽合并时优先保留唯一已有变量身份；存在多个不同名称时生成新的可用默认名。
6. 缓存 v4 保留现有 `input`、`header`、`learning` 和 Spell 配置语义，并新增完整 `tokenizer` 配置。兼容性比较新增 tokenizer 的四个字段；`learning` 继续只保存，不作为解析兼容条件。
7. 不引入迁移层、兼容别名或双写字段。删除 `variable_names`、`named_parameters` 和 `build_named_parameters()`。

## 3. 工作单元

| WU | 文件 | 目标 | 依赖 | 执行关系 |
|---|---|---|---|---|
| WU01 | `wu01-models-config-tokenizer.md` | 建立富 Token 模型、具名 mask 配置和分词来源 | 无 | 首先执行 |
| WU03 | `wu03-template-cluster-lifecycle.md` | 实现模板创建、合并、变量身份、参数提取和簇模型 | WU01 | WU01 后顺序执行 |
| WU02 | `wu02-text-matching-algorithms.md` | 让 LCS、Trie、候选过滤只比较文本 | WU03 | WU03 后顺序执行，以对象化 `LCSObject` 为准 |
| WU04 | `wu04-parser-cache-v4.md` | 集成解析主流程和严格缓存 v4 | WU02、WU03 | 顺序执行 |
| WU05 | `wu05-api-output-summary-exports.md` | 更新公共 API、JSONL、摘要和公共导出 | WU04 | 顺序执行 |
| WU06 | `wu06-integration-tests-and-docs.md` | 完成端到端覆盖、示例配置和文档 | WU05 | 最后执行 |

### 3.1 中间状态验证规则

这是跨模块破坏式重构。WU01 完成后至 WU04 完成前，尚未适配的 Parser 和旧集成断言可能导致全量测试失败；WU04 完成后至 WU06 完成前，缓存版本和旧输出断言也可能失败。各 WU 只以本计划列出的聚焦验证为验收依据，不得为了恢复中间态全量测试而修改范围外文件。所有中间失败必须在完成报告中列明，并在 WU06 的项目级验证中清零。

## 4. 检查点

### CP1：核心模型与算法检查点

在 WU01、WU02、WU03 完成后，审查：

- 模型依赖方向和联合类型是否一致；
- 来源是否在创建、匹配、合并和压缩中正确累计；
- 算法是否只使用文本，未让来源或变量名影响匹配；
- 变量名是否随变量 Token 保留且保持簇内唯一；
- 是否存在旧 `str | None` 模板或 `variable_names` 残留。

未解决的实质问题不得进入 WU04。

### CP2：最终集成检查点

在 WU06 后审查全部尚未深审的改动，重点检查缓存原子加载、输出结构、公共 API、文档与测试覆盖。

## 5. 项目级验收

执行以下不涉及数据库或大语言模型的检查：

```bash
ruff check src tests
basedpyright src tests
pytest -q
```

忽略 `jieba/pkg_resources` 弃用提示。若发现任何测试会访问数据库或大语言模型，停止并先征求用户同意。

最终必须满足设计文档第 17 节全部验收标准，并确认：

- `git diff` 不包含无关改动；
- 没有未解决的 Reviewer 实质发现；
- `docs/plan/exec/` 中各 WU 状态与实际结果一致。

## 6. 状态

| WU/检查点 | 状态 |
|---|---|
| WU01 | 待执行 |
| WU03 | 待执行 |
| WU02 | 待执行 |
| CP1 | 待执行 |
| WU04 | 待执行 |
| WU05 | 待执行 |
| WU06 | 待执行 |
| CP2 | 待执行 |
