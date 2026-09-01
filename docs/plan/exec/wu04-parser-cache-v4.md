# WU04：Parser 集成与模板缓存 v4

## 1. 目标

将富 Token 贯穿 Spell 主流程，并实现严格、完整、原子加载的模板缓存 v4。

## 2. 依赖

WU01、WU03、WU02 及 CP1 已验收。实现前确认核心模块中不存在两套并行 Token 模型。

## 3. 开始前只需阅读

1. `docs/plan/exec/rich-template-token-structure-execution.md`
2. 本文件
3. `src/pin_xie/parser.py`
4. `src/pin_xie/models.py`
5. `src/pin_xie/cluster.py`
6. `src/pin_xie/config.py` 中 `TokenizerConfig`
7. `src/pin_xie/api.py` 中 `save_template_cache()`、`load_template_cache()` 的调用方式

## 4. 范围

### 修改

- `src/pin_xie/parser.py`
- 仅在签名适配必需时小幅修改 `src/pin_xie/api.py` 的缓存保存/加载调用；输出改造留给 WU05

### 新增

- `tests/test_template_cache_v4.py`

### 排除

- JSONL payload、`ParsedRecord` 和模板摘要；
- README、算法文档和示例配置；
- 旧缓存迁移或兼容加载。

## 5. 实现要求

### 5.1 Parser 主流程

- `ParseResult.template_tokens`、`parameters`、`tokens` 改为富对象类型；
- Trie 快路径、候选过滤、LCS、合并、新簇创建和参数提取使用 WU01-WU03 的正式接口；
- 无匹配且 `update_model=false` 时返回 `cluster_id=-1`、空模板、空参数以及本次富输入 Token；
- 保持阈值、快路径不合并、簇顺序、计数、行号和 Trie 重建语义不变。

### 5.2 缓存 v4 写出

状态版本固定为 `4`。每个簇只保存 `cluster_id` 和显式序列化的 `template_tokens`，不得包含 `variable_names`。

在现有状态上新增：

```json
"tokenizer": {
  "delimiters": "...",
  "extra_delimiters": [],
  "use_jieba": true,
  "mask_patterns": [{"name": "...", "pattern": "..."}]
}
```

名称、表达式和数组顺序必须保持配置原样。继续保存并规范化现有 input、header、learning 和 tau 信息。

`SpellParser.to_template_state()` 新增当前 tokenizer 配置映射参数，并通过 `_normalize_tokenizer_config()` 形成上述结构。`PinXieEngine.save_template_cache()` 只负责把 `DemoConfig.tokenizer` 转为该映射并透传。

### 5.3 缓存验证和加载

- 只接受版本 4；v1、v2、v3 均明确提示重新学习；
- 完整比较 tokenizer 的四个字段；mask 名称、表达式和顺序任一变化均拒绝；
  比较逻辑归属 `SpellParser._validate_template_cache_config()`：`from_template_state()` 新增当前 tokenizer 配置映射参数，统一规范化后逐字段比较；`PinXieEngine.load_template_cache()` 只透传当前配置，不重复实现比较。
- 严格校验来源对象和模板 Token 联合：kind、必需字段、字段类型、非空文本/名称、sources 数组、已知来源类型；
- 对 sources 规范化后应等于缓存顺序，拒绝重复或非确定顺序，避免接受非规范状态；
- 每个变量名去除首尾空白后必须非空，并在单簇内唯一；
- 拒绝重复 `cluster_id`；校验 `next_cluster_id` 不与已加载簇冲突；
- 拒绝未知或旧字段结构，不从 `variable_names` 恢复任何数据。

加载必须先构造完整候选 Parser，全部验证和 Trie 重建成功后，`PinXieEngine.load_template_cache()` 才替换当前 parser；任何失败都保留原模型。

## 6. 测试要求

至少覆盖：

1. v4 保存/加载往返；
2. 结构化模板和多来源顺序；
3. 缓存无 `variable_names`；
4. v1/v2/v3 拒绝；
5. tokenizer 每个字段及 mask 顺序变化；
6. 非法 kind、字段类型、空名称、重复变量名、重复/乱序来源；
7. 重复簇 ID 和冲突的 `next_cluster_id`；
8. 任一失败不替换已有模型；
9. 加载后 Trie 匹配与保存前一致。

## 7. 验证

```bash
ruff check src/pin_xie/parser.py src/pin_xie/api.py tests/test_template_cache_v4.py
basedpyright src/pin_xie/parser.py src/pin_xie/api.py
pytest -q tests/test_template_cache_v4.py
```

WU04 完成后生产主流程应重新一致，但 `test_multiline_engine.py` 仍含 v3 断言，可能导致全量测试失败。不要在本 WU 修改该文件；WU06 统一迁移旧集成断言。

## 8. 验收标准

- Parser 全流程使用富 Token；
- v4 完整、稳定地保存新模型及 tokenizer 配置；
- 非法或不兼容缓存失败关闭且不污染当前模型；
- 旧版本无迁移路径；
- 验证通过，无输出层范围漂移。

## 9. 完成报告

报告缓存 schema、严格校验范围、原子替换证据、验证结果和残余风险。不要提交代码。
