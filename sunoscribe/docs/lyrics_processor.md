# Lyrics 模块（Whisper 本地识别）

该模块负责：

- 本地 Whisper 推理（segment 级时间戳）
- 提取歌词文本 + 时间轴
- 对结果做轻量清洗与格式化

该模块**不负责**：

- 与音高序列对齐（交由下游 LLM 处理）

## 输出结构

统一返回 `List[Dict]`：

- `start`: `float`，片段起始时间（秒）
- `end`: `float`，片段结束时间（秒）
- `text`: `str`，歌词文本（已清洗）

## 说明

- 默认模型：`medium`
- 语言：自动检测（`language=None`）
- 为节省耗时，默认关闭 `word_timestamps`
