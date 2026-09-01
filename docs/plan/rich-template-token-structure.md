# 富模板 Token 数据结构重构计划

## 1. 目标

重构分词、模板、参数和输出数据结构，使系统能够：

1. 识别每个输入 Token 是否由正则 mask 提取；
2. 记录命中的具名 mask；
3. 在模板泛化和合并后保留来源信息；
4. 将变量名直接存入变量模板 Token，删除独立的 `variable_names` 映射；
5. 消除 `parameters` 与 `named_parameters` 两套并行结构；
6. 在模板缓存中完整保存新模型及影响分词的配置。

本项目处于开发初期，不迁移旧缓存和旧输出数据。

## 2. 已确定的设计

### 2.1 字段命名

- 输入 Token 和字面量模板 Token 的文本字段使用 `text`；
- 变量模板 Token 的名称字段使用 `var_name`；
- 参数捕获内容使用 `value`；
- 正则来源使用 `mask_name`；
- `kind` 用作可判别联合的类型字段。

### 2.2 具名 mask 配置

将 `tokenizer.mask_patterns` 从字符串数组改为 TOML 表数组：

```toml
[[tokenizer.mask_patterns]]
name = "datetime"
pattern = '\b(?:\d{4}/\d{1,2}/\d{1,2})\s+(?:[01]?\d|2[0-3]):[0-5]\d\b'

[[tokenizer.mask_patterns]]
name = "ipv4"
pattern = '\b(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}\b'
```

配置顺序仍表示匹配优先级。配置解析时校验：

- `name` 和 `pattern` 必须是非空字符串；
- `name` 必须唯一；
- `pattern` 必须能够编译；
- `pattern` 不得匹配空字符串。

配置模型增加不可变的 `MaskPattern`，包含 `name` 和 `pattern`。

## 3. 数据模型

### 3.1 Token 来源

来源使用可判别对象：

```json
{"kind": "plain"}
```

```json
{"kind": "regex", "mask_name": "ipv4"}
```

内部模型应具备值语义和稳定序列化能力，以便来源去重、合并和缓存。

### 3.2 输入 Token

`LogTokenizer.tokenize()` 不再返回 `list[str]`，而是返回富 Token：

```json
{
  "text": "10.0.0.1",
  "source": {
    "kind": "regex",
    "mask_name": "ipv4"
  }
}
```

普通分词结果为：

```json
{
  "text": "connect",
  "source": {
    "kind": "plain"
  }
}
```

输入 Token 的 `source` 表示本次日志分词的事实，不使用模板累计来源替代。

### 3.3 模板 Token

模板 Token 使用字面量和变量两种对象，不再使用 `str | None`。

字面量模板 Token：

```json
{
  "kind": "literal",
  "text": "connect",
  "sources": [
    {"kind": "plain"}
  ]
}
```

变量模板 Token：

```json
{
  "kind": "variable",
  "var_name": "client_ip",
  "sources": [
    {"kind": "regex", "mask_name": "ipv4"}
  ]
}
```

`sources` 表示模板学习期间观察到的来源集合，必须：

- 去重；
- 使用确定性顺序序列化；
- 在模板合并时取并集；
- 允许同时包含 `plain` 和多个 `regex` 来源。

每个变量模板 Token 始终持有非空且在簇内唯一的 `var_name`。新变量槽创建时生成 `var_N`，已有变量槽在模板位置变化时保留名称，不再根据当前序号重新绑定名称。

### 3.4 参数

删除 `named_parameters`。`parameters` 改为对象数组：

```json
{
  "template_token_index": 1,
  "var_name": "client_ip",
  "value": "10.0.0.1",
  "sources": [
    {"kind": "regex", "mask_name": "ipv4"}
  ]
}
```

字段含义：

- `template_token_index`：变量在完整 `template_tokens` 数组中的位置；
- `var_name`：对应变量模板 Token 的当前名称；
- `value`：本次日志捕获的文本；
- `sources`：本次捕获区间内输入 Token 的实际来源集合。

参数的 `sources` 是单条日志的事实；变量模板 Token 的 `sources` 是模板簇的累计信息，两者不能混用。

## 4. JSONL 输出结构

示例：

```json
{
  "cluster_id": 3,
  "template": "connect <VAR:client_ip>",
  "template_tokens": [
    {
      "kind": "literal",
      "text": "connect",
      "sources": [{"kind": "plain"}]
    },
    {
      "kind": "variable",
      "var_name": "client_ip",
      "sources": [{"kind": "regex", "mask_name": "ipv4"}]
    }
  ],
  "parameters": [
    {
      "template_token_index": 1,
      "var_name": "client_ip",
      "value": "10.0.0.1",
      "sources": [{"kind": "regex", "mask_name": "ipv4"}]
    }
  ],
  "tokens": [
    {
      "text": "connect",
      "source": {"kind": "plain"}
    },
    {
      "text": "10.0.0.1",
      "source": {"kind": "regex", "mask_name": "ipv4"}
    }
  ]
}
```

约束：

- `template` 继续作为展示字段，由结构化模板 Token 派生；
- `template_tokens` 是结构化模板的权威表示；
- `named_parameters` 删除；
- `tokens` 仍受 `output.show_tokens` 控制，但出现时必须是对象数组；
- Header、行号、原始日志等无关字段保持现有语义。

## 5. 分词器改动

修改 `src/pin_xie/tokenizer.py`：

1. 接收 `MaskPattern` 序列；
2. 保留规则配置顺序；
3. 在组合匹配时识别具体命中的规则；
4. mask 命中返回 `regex` 来源；
5. 普通切分和 jieba 切分返回 `plain` 来源；
6. 顶层便利函数 `tokenize()` 同步返回富 Token。

组合正则使用内部生成的分支标识，不能依赖用户正则中的捕获组名称。内部标识不得暴露到输出。

## 6. 聚类与算法边界

LCS、Trie 和 Jaccard 的匹配语义保持不变，只比较 Token 文本：

- 输入 Token 使用 `text`；
- 字面量模板 Token 使用 `text`；
- 变量模板 Token 保持通配语义；
- 来源、变量名不得参与相似度计算。

需要调整：

- `src/pin_xie/lcs.py`；
- `src/pin_xie/similarity.py`；
- `src/pin_xie/trie.py`；
- `src/pin_xie/template.py`；
- `src/pin_xie/cluster.py`；
- `src/pin_xie/parser.py`。

优先通过小型访问函数统一取得可比较文本和判断变量 Token，避免各算法自行检查对象字段。

## 7. 模板创建与合并规则

### 7.1 新建模板簇

- 每个输入 Token 转换为字面量模板 Token；
- `text` 复制输入文本；
- `sources` 初始化为该输入 Token 的单一来源。

### 7.2 相同字面量继续匹配

- 文本相同时保持字面量；
- 将新输入 Token 的来源加入字面量模板 Token 的 `sources`；
- 来源变化不影响文本匹配结果。

### 7.3 差异区间泛化为变量

- 使用差异区间内旧模板 Token 和新输入 Token 的来源并集创建变量；
- 新变量生成簇内唯一的 `var_N`；
- 一个变量可以记录普通来源和多个正则来源。

### 7.4 已有变量吸收新内容

- 保留已有 `var_name`；
- 合并已有来源和本次捕获来源；
- 不因变量在模板中的序号变化而改名。

### 7.5 相邻变量槽压缩

相邻变量槽合并时：

- `sources` 取并集；
- 名称相同则保留；
- 名称不同则生成新的簇内唯一默认名称；
- 不静默选择其中一个不同名称。

### 7.6 变量名称管理

保留公共 API 名称：

- `set_template_variable_name()`；
- `set_template_variable_names()`；
- `get_template_variable_names()`。

API 仍可按当前变量序号定位，但修改目标是变量 Token 自身。名称必须：

- 去除首尾空白；
- 非空；
- 在簇内唯一。

删除名称时，为变量生成可用的默认 `var_N`，而不是维护缺失映射。

## 8. 参数提取

重写 `extract_parameters()`：

1. 输入富 Token 和对象模板；
2. 按现有固定 Token 边界捕获变量区间；
3. `value` 继续使用空格连接捕获 Token 文本；
4. 记录完整模板数组中的 `template_token_index`；
5. `var_name` 直接读取变量模板 Token；
6. `sources` 取本次捕获输入 Token 的来源并集。

删除：

- `build_named_parameters()`；
- 基于 `variable_names` 序号映射生成名称的逻辑。

模板字符串渲染函数改为直接处理对象模板 Token。

## 9. 聚类模型

修改 `LCSObject`：

- `template_tokens` 改为对象模板 Token 数组；
- 删除 `variable_names`；
- `token_set` 只包含字面量模板 Token 的文本；
- `constant_token_count` 和 `variable_token_count` 按 `kind` 统计；
- `update_template()` 不再调用 `_prune_variable_names()`；
- 删除 `_prune_variable_names()`。

模板合并必须尽可能复用已有变量 Token 的名称和元数据，不能退化为重新生成无身份的占位对象。

## 10. 解析结果和公共 API

修改：

- `ParseResult.template_tokens`；
- `ParseResult.parameters`；
- `ParseResult.tokens`；
- `ParsedRecord.template_tokens`；
- `ParsedRecord.parameters`；
- `ParsedRecord.tokens`。

删除：

- `ParsedRecord.named_parameters`；
- JSONL 中的 `named_parameters`。

`PinXieEngine.process_log()` 负责组装对象结果和派生的 `template` 字符串，不再构造独立变量名映射。

`_record_to_payload()` 应通过明确的序列化函数输出数据类，不依赖隐式 `asdict()`，以保证联合类型字段和来源顺序稳定。

## 11. 模板缓存 v4

模板缓存版本从 `3` 升级为 `4`。旧版本直接拒绝并提示重新学习，不提供迁移逻辑。

簇缓存示例：

```json
{
  "cluster_id": 3,
  "template_tokens": [
    {
      "kind": "literal",
      "text": "connect",
      "sources": [{"kind": "plain"}]
    },
    {
      "kind": "variable",
      "var_name": "client_ip",
      "sources": [{"kind": "regex", "mask_name": "ipv4"}]
    }
  ]
}
```

删除缓存中的 `variable_names`。

缓存增加完整 tokenizer 配置：

```json
{
  "tokenizer": {
    "delimiters": "...",
    "extra_delimiters": [],
    "use_jieba": true,
    "mask_patterns": [
      {"name": "datetime", "pattern": "..."},
      {"name": "ipv4", "pattern": "..."}
    ]
  }
}
```

加载缓存时，以下 tokenizer 字段全部参与兼容性比较：

- `delimiters`；
- `extra_delimiters`；
- `use_jieba`；
- 具名 `mask_patterns` 的名称、表达式和顺序。

## 12. 模板摘要

修改 `write_template_summary()`：

- 模板正文继续使用渲染字符串；
- 删除独立的 `variable_names` 行；
- 为每个变量输出 `var_name` 和来源；
- mask 配置摘要至少包含规则数量和规则名称；
- 输出顺序保持确定性。

## 13. 公共导出

检查并按需更新 `src/pin_xie/__init__.py`，导出适合作为公共 API 的模型：

- `MaskPattern`；
- 输入 Token 类型；
- 模板 Token 类型；
- 参数类型；
- 来源类型。

内部序列化辅助函数和算法访问函数不导出。

## 14. 文件级改动清单

核心代码：

- `src/pin_xie/config.py`
- `src/pin_xie/tokenizer.py`
- `src/pin_xie/template.py`
- `src/pin_xie/cluster.py`
- `src/pin_xie/lcs.py`
- `src/pin_xie/similarity.py`
- `src/pin_xie/trie.py`
- `src/pin_xie/parser.py`
- `src/pin_xie/api.py`
- `src/pin_xie/__init__.py`

配置与文档：

- `config/Config.toml`
- `config/Config.dynamic_example.toml`
- `README.md`
- `docs/algo.md`

测试：

- 新增独立的 tokenizer、模板结构和序列化测试文件；
- 更新 `tests/test_multiline_engine.py` 中缓存版本和 JSONL 断言；
- 必要时更新其他依赖输出结构的测试。

## 15. 实施顺序

1. 定义来源、输入 Token、模板 Token、参数和 `MaskPattern` 模型；
2. 修改配置解析和示例配置；
3. 修改分词器并补充分词单元测试；
4. 修改模板创建、合并、压缩和参数提取；
5. 修改 LCS、Trie、Jaccard 的文本访问逻辑；
6. 修改 `LCSObject` 和变量名称 API；
7. 修改 `SpellParser`、`ParseResult` 和缓存 v4；
8. 修改 `ParsedRecord`、JSONL 序列化和模板摘要；
9. 更新公共导出；
10. 更新现有测试并增加端到端测试；
11. 更新 README 和算法文档；
12. 运行 Ruff、basedpyright 和不涉及数据库或大语言模型的测试。

## 16. 测试范围

### 16.1 配置

- 正确解析具名 mask；
- 拒绝缺失或空的名称、表达式；
- 拒绝重复名称；
- 拒绝非法正则；
- 拒绝可匹配空字符串的 mask；
- 保持规则顺序。

### 16.2 分词

- 普通 Token 标记为 `plain`；
- mask Token 标记为 `regex` 并包含正确 `mask_name`；
- 同一位置多规则可匹配时选择靠前规则；
- mask 内容不再被普通分隔或 jieba 拆开；
- 用户正则中的捕获组不影响 mask 身份识别；
- 空文本和多行文本行为正确。

### 16.3 模板

- 新簇保留输入来源；
- 相同字面量累计来源；
- 正则差异值泛化为变量并保留 mask 来源；
- 普通与正则 Token 可形成混合来源变量；
- 多种 mask 可形成多来源变量；
- 变量前插入新变量后，原变量名仍绑定原变量；
- 相邻变量合并时来源正确；
- 不同变量名合并时生成新默认名；
- 变量默认名和自定义名在簇内唯一。

### 16.4 参数

- 参数对象包含正确模板索引、名称和值；
- 参数来源使用本次捕获 Token，而不是模板累计来源；
- 多 Token 参数的文本拼接保持现有行为；
- 无匹配簇时返回空模板和空参数。

### 16.5 输出

- `template_tokens` 为对象数组；
- `parameters` 为对象数组；
- `named_parameters` 不再出现；
- `tokens` 在 `show_tokens=true` 时为对象数组；
- `show_tokens=false` 时不输出 `tokens`；
- `template` 与结构化模板一致；
- JSON 字段和来源顺序稳定。

### 16.6 缓存

- v4 保存和加载往返一致；
- 缓存不包含 `variable_names`；
- v1、v2、v3 均被拒绝；
- tokenizer 任一兼容性字段变化时拒绝加载；
- 非法 Token 对象、来源、变量名和重复名称被拒绝；
- 加载失败不替换当前模型。

## 17. 验收标准

完成后必须满足：

1. 分词阶段产生的每个 Token 都有明确来源；
2. 正则来源能稳定关联到配置中的 `mask_name`；
3. 模板泛化不会丢失或伪造来源信息；
4. 变量名随变量模板 Token 保存，不再通过独立序号映射关联；
5. JSONL 不再包含 `named_parameters`；
6. `template_tokens`、`parameters` 和可选 `tokens` 均使用约定的对象结构；
7. 模板缓存为 v4，并校验完整 tokenizer 配置；
8. 算法匹配结果不受来源元数据影响；
9. Ruff、basedpyright 和相关测试通过；
10. README、算法文档、示例配置与实现一致。

## 18. 非目标

本次不处理：

- 旧模板缓存迁移；
- 旧 JSONL 输出兼容；
- Header 字段来源追踪；
- 正则类别自动推断；
- 参数值类型转换；
- 跨模板簇统一变量名称；
- 基于来源信息调整 LCS、Trie 或 Jaccard 权重。
