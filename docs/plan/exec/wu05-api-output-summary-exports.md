# WU05：公共 API、JSONL、模板摘要与导出

## 1. 目标

完成富 Token 的对外结果组装、显式 JSONL 序列化、模板摘要和公共导出，彻底删除并行命名参数结构。

## 2. 依赖

WU04 已验收，Parser 和缓存 v4 接口已稳定。

## 3. 开始前只需阅读

1. `docs/plan/exec/rich-template-token-structure-execution.md`
2. `docs/plan/rich-template-token-structure.md` 第 4、10、12、13 节
3. `src/pin_xie/api.py`
4. `src/pin_xie/models.py`
5. `src/pin_xie/template.py` 的渲染与变量名称接口
6. `src/pin_xie/__init__.py`

## 4. 范围

### 修改

- `src/pin_xie/api.py`
- `src/pin_xie/__init__.py`
- `src/pin_xie/template.py`（仅删除 WU03 临时保留的 `build_named_parameters()`）

### 新增或更新

- `tests/test_rich_output.py`

### 排除

- 不修改聚类算法或缓存 schema；
- 不更新用户文档；WU06 负责；
- 不保留旧输出字段兼容。

## 5. 实现要求

### 5.1 结果模型和引擎

`ParsedRecord` 使用：

- 对象 `template_tokens`；
- 对象 `parameters`；
- 可选对象 `tokens`；
- 删除 `named_parameters`。

`process_log()`：

- 直接使用 `ParseResult` 的结构化对象；
- `template` 由对象模板渲染派生；
- 不再读取或组装簇级 `variable_names`；
- 保持 Header、上下文、日志、行号和物理行计数语义。

变量名称公共 API 名称保持：

- `set_template_variable_name()`；
- `set_template_variable_names()`；
- `get_template_variable_names()`。

它们按当前变量序号操作变量 Token。`set_template_variable_names()` 必须调用 WU03 已提供的簇级批量替换原语，基于最终状态一次性校验和替换；不得在 API 层逐项写入或直接绕过簇校验。批量交换两个现有名称必须成功。

### 5.2 JSONL 序列化

`_record_to_payload()` 必须逐字段构造 payload，并调用明确的模型序列化函数。不得使用 `asdict()` 或依赖 dataclass 内部字段布局。

- `template_tokens` 输出对象数组；
- `parameters` 输出对象数组；
- 删除 `named_parameters`；
- `show_tokens=true` 时输出对象 `tokens`；
- `show_tokens=false` 时完全省略 `tokens`；
- Header 动态字段继续使用现有 `header_` 前缀；
- 来源按规范顺序输出。

### 5.3 模板摘要

- 模板正文使用对象模板渲染；
- 删除独立 `variable_names` 行；
- 每个变量按模板顺序输出模板索引、`var_name` 和来源；
- tokenizer 摘要至少输出 mask 数量和按配置顺序排列的名称；
- 保持簇、字段和来源输出确定性。

### 5.4 公共导出

从 `pin_xie` 导出适合作为公共 API 的模型：

- `MaskPattern`；
- 输入 Token；
- 字面量/变量模板 Token 和联合别名；
- 参数对象；
- 来源类型。

内部比较、排序、序列化和反序列化辅助函数不得导出。

## 6. 测试要求

至少覆盖：

1. 设计文档 JSONL 示例的等价结构；
2. `named_parameters` 完全不存在；
3. `show_tokens` 两种分支；
4. `template` 与 `template_tokens` 一致；
5. 参数和模板来源的事实/累计区别；
6. Header 和行号字段不回归；
7. 摘要变量名称、来源和 mask 名称；
8. 单项变量改名、删除重置、重复拒绝和批量交换；
9. 公共导出可导入，内部辅助函数不在 `__all__`。

## 7. 验证

```bash
ruff check src/pin_xie/api.py src/pin_xie/__init__.py tests/test_rich_output.py
basedpyright src/pin_xie/api.py src/pin_xie/__init__.py
pytest -q tests/test_rich_output.py
```

现有 `test_multiline_engine.py` 若仍断言旧输出，可在本 WU 做最小必要更新，并把完整集成扩展留给 WU06。
WU04 后仍存在缓存 v3 的旧集成断言。本 WU 只更新因输出/API 改造而直接阻塞聚焦验证的断言；`test_multiline_engine.py` 不作为本 WU 验收命令，其缓存版本与完整集成迁移由 WU06 统一完成。主管已诊断联合运行仅有 4 个缓存 v3 旧断言失败。

## 8. 验收标准

- 对外结果和 JSONL 只使用设计中的结构化表示；
- `named_parameters` 和外部变量映射逻辑完全删除；
- 输出顺序稳定且 `show_tokens` 行为正确；
- 摘要和公共导出与新模型一致；
- 验证通过，无算法或缓存范围漂移。

## 9. 完成报告

报告公共类型、删除字段、输出示例摘要、验证结果和残余风险。不要提交代码。
