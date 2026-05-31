### 原始脚本

脚本：`scripts/build_training_csv.py`

核心逻辑：

- 读取带标签 CSV：`examples/key_logs_abnormal_labeled.csv`
- 按 README 的 API 用法调用 `PinXieEngine`
- 使用 `config/Config.dynamic_example.toml` 的结构：`<time>,<entity>,<context>`
- 对每行日志解析出 `cluster_id` 作为 `event_col`
- 输出训练 CSV：`entity_col,event_col,label`

### 新数据格式样本
```csv
host,content,is_attack,attack_type,technique,tactic,attack_name
user-host-01,用户 purplecat0 请求登录系统,false,,,,
user-host-01,验证用户 purplecat0 的凭据,false,,,,
user-host-01,为用户 purplecat0 创建会话,false,,,,
user-host-09,用户 muscularfox15 发生重复登录尝试,true,multiple_login_attempts,T1110,credential_access,Multiple repeated login attempts
user-host-09,用户 muscularfox15 发生重复登录尝试,true,multiple_login_attempts,T1110,credential_access,Multiple repeated login attempts
user-host-09,用户 muscularfox15 发生重复登录尝试,true,multiple_login_attempts,T1110,credential_access,Multiple repeated login attempts
user-host-09,用户 muscularfox15 发生重复登录尝试,true,multiple_login_attempts,T1110,credential_access,Multiple repeated login attempts
user-host-09,验证用户 muscularfox15 的凭据,false,,,,
```

### 新的输出要求

形如：
```csv
entity_col,event_col,content,label,atack_name
user-host-01,2,验证用户 purplecat0 的凭据,0,
user-host-09,1,用户 muscularfox15 发生重复登录尝试,1,Multiple repeated login attempts
user-host-09,2,验证用户 muscularfox15 的凭据,2,Multiple repeated login attempts
```

相同的 host 为一条序列，
目前可以保证：同一序列在文件中的位置是连续的。
序列中日志的先后顺序不应当被改变。

序列中存在一个异常日志，整个序列都记作异常序列

字段 label 可能的取值为:
- 0: 正常序列中的正常日志
- 1: 异常序列中的异常日志
- 2: 异常序列中的正常日志

entity_col 照搬 host 列
content 列直接照搬

异常日志序列中所有日志的 attack_name 都为异常日志的 attack_name。
请注意，一个日志序列中可能发生多次不同的攻击，attack_name 应该采取列表的方式存储

请注意 technique 字段值为 "T1070" 的日志不应当输出，
但需要正常的干涉序列，如标记为异常序列，为其他日志添加 attack_name , 设置 label 之类的行为
