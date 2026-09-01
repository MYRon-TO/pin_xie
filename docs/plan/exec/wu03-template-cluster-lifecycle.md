# WU03：模板与模板簇生命周期

## 1. 目标

实现富模板 Token 的创建、来源累计、差异泛化、相邻变量压缩、变量身份管理和结构化参数提取，并删除簇上的独立变量名映射。

## 2. 依赖

WU01 已验收。本 WU 在 WU02 之前执行，只依赖 `models.py` 和现有 LCS 返回公共文本序列的约定。对象化簇落地后，WU02 再适配算法。

## 3. 开始前只需阅读

1. `docs/plan/exec/rich-template-token-structure-execution.md`
2. `docs/plan/rich-template-token-structure.md` 第 3、7、8、9 节
3. `src/pin_xie/models.py`
4. `src/pin_xie/template.py`
5. `src/pin_xie/cluster.py`

## 4. 范围

### 修改

- `src/pin_xie/template.py`
- `src/pin_xie/cluster.py`

### 新增

- `tests/test_rich_template.py`

### 排除

- Parser 流程和缓存；
- API/JSONL/模板摘要；
- LCS、Trie、候选过滤；
- 旧 `str | None` 模板兼容。

## 5. 实现要求

### 5.1 模板创建

`create_cluster()` 接收富输入 Token。每个输入 Token 转为字面量模板 Token，`text` 原样复制，`sources` 初始化为该输入事实来源。

`LCSObject`：

- `template_tokens` 使用对象联合；
- 删除 `variable_names` 和 `_prune_variable_names()`；
- `token_set` 只含字面量文本；
- `constant_token_count` 保持“不重复字面量文本数量”语义；
- `variable_token_count` 按 `kind` 统计；
- `update_template()` 更新对象模板及 `token_set`。

### 5.2 合并规则

`merge_template(old_tpl, new_tokens, lcs_texts)` 必须按当前从左到右的 LCS 定位策略工作，并处理每个差异区间：

1. LCS 命中的旧字面量保留其对象，并合并对应新输入 Token 的来源；
2. 差异区间变为一个变量 Token，来源为区间内所有旧模板 Token 来源与新输入 Token 来源的并集；
3. 区间只有一个已有变量身份时保留其 `var_name`；
4. 区间含多个变量但名称相同则保留该名称；含多个不同名称则生成新的可用默认名；
5. 新变量使用当前簇内最小可用 `var_N`，不得与保留或自定义名称重复；
6. 无 LCS 时输出单变量；若旧模板本来只有一个变量，保留其身份，否则按上述冲突规则处理；
7. 旧模板为空时将输入转换为字面量对象，不直接复制输入对象类型。

相邻变量压缩使用同一来源和命名规则。不得静默选取两个不同名称中的任意一个。

### 5.3 变量名称 API

保留簇级和引擎将调用的语义：按当前变量序号定位，但实际修改变量 Token。

- 名称去除首尾空白；
- 非空且簇内唯一；
- `None` 或空白表示重置为可用默认 `var_N`；
- 获取接口按当前模板顺序返回每个变量的实际名称，不再返回稀疏映射。

若当前公共 API 约定必须返回 `dict[int, str]`，继续返回完整映射 `{序号: 实际名称}`，但不得在簇中存储映射。

`LCSObject` 必须提供簇级批量替换原语，例如 `replace_variable_names(mapping)`：先基于最终模板快照统一完成索引、名称规范化、非空和簇内唯一校验，再一次性替换变量 Token。单项设置与批量设置应复用同一规范化/最终状态校验逻辑。该原语必须支持两个现有名称互换，不得因中间瞬时重复而失败。WU05 的引擎批量 API 只调用此原语。

### 5.4 参数与渲染

`extract_parameters()` 返回 `list[ParameterCapture]`：

- 保持现有固定 Token 边界搜索；
- `template_token_index` 是完整模板数组索引；
- `var_name` 来自变量 Token；
- `value` 使用捕获输入 Token 的文本以空格连接；
- `sources` 只来自本次捕获输入 Token，并稳定去重，不能使用模板累计来源。

渲染函数直接读取对象模板。删除 `variable_label()` 和 `build_named_parameters()` 等基于外部映射的逻辑。

## 6. 测试要求

至少覆盖设计文档第 16.3、16.4 节全部条目，并特别加入：

- 相同字面量在不同来源下仍匹配且累计来源；
- 在已有变量之前插入新变量后，原自定义名称仍绑定原变量；
- 两个不同自定义名压缩后生成不冲突默认名；
- 参数来源是本条输入事实，而非模板累计值；
- 固定 Token 重复时仍选择当前位置后的第一个边界；
- 重置变量名后仍得到非空唯一名称。

## 7. 验证

```bash
ruff check src/pin_xie/template.py src/pin_xie/cluster.py tests/test_rich_template.py
basedpyright src/pin_xie/template.py src/pin_xie/cluster.py
pytest -q tests/test_rich_template.py
```

本 WU 会先于算法和 Parser 适配完成，全量测试可能失败。只以本节聚焦验证验收；不得越界修改算法或 Parser。

## 8. 验收标准

- 模板任何位置均不再使用 `str | None`；
- 变量身份和累计来源在合并、位移、压缩后符合规则；
- 簇不含 `variable_names`；
- 参数对象字段及事实来源准确，单项和批量变量改名均可原子校验；
- 验证通过，无范围外改动。

## 9. 完成报告

报告关键合并规则、变量 API 返回形状、验证结果和残余风险。不要提交代码。
