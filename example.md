examples/key_logs_abnormal_labeled.csv
```csv
_time,user,content,label
2025/11/19 4:00,user16,用户 user16 请求登录系统,0
2025/11/19 4:03,user16,验证用户 user16 的凭据,0
2025/11/19 4:06,user16,为用户 user16 创建会话,0
2025/11/19 4:08,user16,用户 user16 请求下载文件 file4,0
2025/11/19 4:09,user16,验证用户 user16 对文件 file4 的访问权限,0
2025/11/19 4:11,user16,准备文件 file4 传输,0
2025/11/19 4:15,user16,开始文件 file4 下载,0
2025/11/19 4:17,user16,文件 file4 下载完成，更新下载记录,0
2025/11/19 4:22,user16,用户 user16 发起一级密钥销毁请求，目标密钥: key004,0
2025/11/19 4:25,user16,验证用户 user16 的密钥销毁权限,0
```

examples/key_logs_abnormal_labeled.log
```csv
2025/11/19 4:00,user16,用户 user16 请求登录系统
2025/11/19 4:03,user16,验证用户 user16 的凭据
2025/11/19 4:06,user16,为用户 user16 创建会话
2025/11/19 4:08,user16,用户 user16 请求下载文件 file4
2025/11/19 4:09,user16,验证用户 user16 对文件 file4 的访问权限
2025/11/19 4:11,user16,准备文件 file4 传输
2025/11/19 4:15,user16,开始文件 file4 下载
2025/11/19 4:17,user16,文件 file4 下载完成，更新下载记录
2025/11/19 4:22,user16,用户 user16 发起一级密钥销毁请求，目标密钥: key004
2025/11/19 4:25,user16,验证用户 user16 的密钥销毁权限
```

已完成脚本：`scripts/build_training_csv.py`

核心逻辑：

- 读取带标签 CSV：`examples/key_logs_abnormal_labeled.csv`
- 按 README 的 API 用法调用 `PinXieEngine`
- 使用 `config/Config.dynamic_example.toml` 的结构：`<time>,<entity>,<context>`
- 对每行日志解析出 `cluster_id` 作为 `event_col`
- 输出训练 CSV：`entity_col,event_col,label`

运行命令：

```bash
python scripts/build_training_csv.py \
  --input examples/key_logs_abnormal_labeled.csv \
  --output output/key_logs_training.csv \
  --config config/Config.dynamic_example.toml
```

如果希望事件 ID 带前缀，比如 `E0/E1/...`：

```bash
python scripts/build_training_csv.py \
  --input examples/key_logs_abnormal_labeled.csv \
  --output output/key_logs_training.csv \
  --config config/Config.dynamic_example.toml \
  --event-prefix E
```

输出格式示例：

```csv
entity_col,event_col,label
user16,0,0
user16,1,0
```

我没有直接查看大原始文件，只用临时小样例做了冒烟测试。脚本是流式逐行处理 CSV，不会一次性把大文件读进内存。
