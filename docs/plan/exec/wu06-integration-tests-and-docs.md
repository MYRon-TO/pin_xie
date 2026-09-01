# WU06：集成测试、示例配置与文档

## 1. 目标

补齐跨模块端到端覆盖，更新示例配置和用户/算法文档，并完成项目级验证。

## 2. 依赖

WU05 已验收；核心接口、缓存和输出结构不得再由本 WU重新设计。

## 3. 开始前只需阅读

1. `docs/plan/exec/rich-template-token-structure-execution.md`
2. `docs/plan/rich-template-token-structure.md` 第 14-18 节
3. `tests/test_multiline_engine.py`
4. `README.md` 中配置、库 API、输出和缓存章节
5. `docs/algo.md`
6. `config/Config.toml`
7. `config/Config.dynamic_example.toml`

遇到接口细节时再读取相应实现文件，不要重新设计已验收接口。

## 4. 范围

### 修改

- `tests/test_multiline_engine.py`
- 其他现有测试中依赖旧 Token/输出结构的断言
- `README.md`
- `docs/algo.md`

### 可新增

- `tests/test_rich_template_end_to_end.py`

### 排除

- 不改变生产代码架构或公共接口；发现缺陷时停止并报告给主代理，由原 WU进行 focused rework；
- 不迁移旧缓存或保留旧 JSONL；
- 不添加数据库或大语言模型测试。

## 5. 集成测试要求

至少形成一条端到端场景：

1. 使用两个以上具名 mask；
2. 学习多条日志，使字面量来源累计并形成变量；
3. 自定义变量名；
4. 保存并加载缓存 v4；
5. 仅解析新日志；
6. 验证模板变量身份、模板累计来源、参数本次来源；
7. 写出 JSONL 和模板摘要；
8. 验证 `named_parameters` 不存在，结构化数组和来源顺序稳定；
9. 验证加载前后模板渲染和匹配结果一致。

更新 `test_multiline_engine.py`：

- 缓存版本改为 4；
- 加入 tokenizer 完整配置断言；
- 旧版本参数扩展为 v1/v2/v3；
- JSONL 断言使用对象 `template_tokens`、`parameters`、可选 `tokens`；
- 删除所有 `variable_names`/`named_parameters` 预期；
- 保留多行组装、Header、运行模式、shuffle 和原子加载的原有语义覆盖。

## 6. 文档要求

### README

更新：

- `[[tokenizer.mask_patterns]]` 具名表数组配置与顺序优先级；
- 富输入 Token、模板 Token、参数对象和来源字段；
- JSONL 示例及 `show_tokens`；
- 变量名 API 实际存储于变量模板 Token；
- 缓存版本 4、完整 tokenizer 兼容条件和旧缓存拒绝；
- 公共模型导入示例。

删除所有 `list[str | None]`、独立 `variable_names`、`named_parameters` 和字符串 mask 数组描述。

### docs/algo.md

更新数据模型、分词、LCS/Trie/过滤访问方式、模板合并来源规则、变量身份、参数对象、缓存和实现位置。明确来源不参与相似度。

文档描述实际实现，不复制大段设计文档。

### 示例配置

核验 WU01 已转换的两个受跟踪 TOML 文件均使用合法具名 mask 表数组，名称明确、唯一并保持原规则顺序；本 WU 不重复修改。未跟踪的 `config/pin_xie-user_system.toml` 是本地用户配置，不纳入改动或验收。

## 7. 验证

先运行聚焦集成测试：

```bash
pytest -q tests/test_multiline_engine.py tests/test_rich_template_end_to_end.py
```

若没有新增端到端文件，移除命令中的该路径。随后执行：

```bash
ruff check src tests
basedpyright src tests
pytest -q
```

忽略 `jieba/pkg_resources` 弃用提示。若发现任何命令会访问数据库或大语言模型，停止并先征求用户同意。

## 8. 验收标准

- 设计文档第 16 节测试范围有对应覆盖；
- 第 17 节全部验收标准通过；
- README、算法文档、示例配置和实现一致；
- 全量 Ruff、basedpyright 和不涉及数据库/大语言模型的测试通过；
- 未以测试或文档名义引入生产代码设计变更。

## 9. 完成报告

报告新增/更新覆盖、文档变化、完整验证结果、跳过项和残余风险。不要提交代码。
