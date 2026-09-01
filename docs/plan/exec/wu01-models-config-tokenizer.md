# WU01：富 Token 模型、具名 Mask 配置与分词

## 1. 目标

建立后续 WU 唯一使用的数据模型；将 mask 配置改为具名对象；使分词器返回带事实来源的输入 Token。

## 2. 开始前只需阅读

1. `docs/plan/exec/rich-template-token-structure-execution.md`
2. `docs/plan/rich-template-token-structure.md` 第 2、3、5、13 节
3. `src/pin_xie/config.py`
4. `src/pin_xie/tokenizer.py`
5. `config/Config.toml`
6. `config/Config.dynamic_example.toml`

无需阅读聚类、缓存或输出实现。

## 3. 范围

### 修改

- `src/pin_xie/config.py`
- `src/pin_xie/tokenizer.py`
- `config/Config.toml`
- `config/Config.dynamic_example.toml`

仓库中未跟踪的 `config/pin_xie-user_system.toml` 属于本地用户配置，不修改、不纳入验收；使用者需在实现落地后自行改为具名 mask 表数组。

### 新增

- `src/pin_xie/models.py`
- `tests/test_rich_tokenizer.py`
- 可新增独立配置测试文件；不要把大量单元测试塞入 `test_multiline_engine.py`

### 排除

- 模板合并、变量命名、参数提取；
- LCS、Trie、候选过滤；
- 缓存和 JSONL 输出；
- 公共导出，由 WU05 处理。

## 4. 实现要求

### 4.1 数据模型

在 `models.py` 定义并准确标注类型：

- `MaskPattern(name, pattern)`：不可变；
- `PlainTokenSource(kind="plain")`；
- `RegexTokenSource(mask_name, kind="regex")`；
- `TokenSource` 联合；
- `InputToken(text, source)`；
- `LiteralTemplateToken(text, sources, kind="literal")`；
- `VariableTemplateToken(var_name, sources, kind="variable")`；
- `TemplateToken` 联合；
- `ParameterCapture(template_token_index, var_name, value, sources)`。

来源和 mask 应具备值相等及可哈希语义。模板 Token 的 `sources` 与参数的 `sources` 使用 tuple，并在构造入口规范化。

提供内部辅助函数：

- 来源去重和稳定排序：`plain` 在前，`regex` 按 `mask_name` 排序；
- 输入 Token 文本访问；
- 模板 Token 是否为变量及字面量文本访问；
- 上述模型到普通 JSON 对象的显式序列化。

不要在本 WU 实现缓存反序列化；WU04 会在加载边界做严格校验。

### 4.2 配置解析

`TokenizerConfig.mask_patterns` 改为 `tuple[MaskPattern, ...]`。解析 `[[tokenizer.mask_patterns]]` 表数组，并保持顺序。

逐项拒绝：

- mask 项不是 TOML 表；
- `name` 或 `pattern` 缺失、不是字符串或去除首尾空白后为空；
- 名称重复；
- 正则无法由 `regex.compile()` 编译；
- 正则可匹配空字符串。

名称使用去除首尾空白后的值；正则正文不得静默改写。错误信息应包含 `tokenizer.mask_patterns` 和失败原因。

不要接受旧字符串数组；项目明确不要求兼容。

### 4.3 分词器

`LogTokenizer` 接收 `Iterable[MaskPattern]`，`tokenize()` 和顶层便利函数返回 `list[InputToken]`。

组合正则为每个分支生成内部唯一组名。初始化时先收集用户正则中的全部具名组，再选择不冲突的内部名称；不得要求用户避让固定前缀。匹配后按配置顺序检查 `match.group(内部组名) is not None` 来确定命中规则，不得使用 `lastgroup`，因为用户内部具名组可能成为最后匹配组。内部组名不得进入输出。

- mask 命中：`RegexTokenSource(mask_name=...)`；
- 普通分隔和 jieba 结果：`PlainTokenSource()`；
- 保持原先空文本、多行、分隔符、配置优先级和 mask 不被二次切分的行为。

## 5. 测试要求

至少覆盖：

1. 完整具名配置的解析和顺序；
2. 缺失、空值、错误类型、重复名、非法正则、空字符串匹配；
3. 普通 Token 来源；
4. 正确 mask 名称；
5. 同位置规则优先级；
6. 用户正则含捕获组和具名组；
   该测试必须包含与候选内部前缀相似的用户组名，并证明身份识别不依赖 `lastgroup`。
7. mask 内容不被分隔符或 jieba 拆分；
8. 空文本和多行文本；
9. 来源去重与序列化顺序。

## 6. 验证

```bash
ruff check src/pin_xie/models.py src/pin_xie/config.py src/pin_xie/tokenizer.py tests/test_rich_tokenizer.py
basedpyright src/pin_xie/models.py src/pin_xie/config.py src/pin_xie/tokenizer.py
pytest -q tests/test_rich_tokenizer.py
```

可补充运行独立配置测试。忽略 `jieba/pkg_resources` 弃用提示。

## 7. 验收标准

- 富 Token 基础模型可供其他模块直接导入；
- mask 配置只接受具名表数组并完成全部设计校验；
- 每个分词结果都有准确来源；
- 相同输入和配置的模型及序列化顺序稳定；
- 未修改本 WU 排除范围；
- 验证命令通过。

## 8. 完成报告

报告修改文件、模型/辅助函数清单、验证结果、任何偏差和残余风险。不要提交代码。
