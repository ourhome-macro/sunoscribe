# Audio Processor 模块

## 概述
本模块基于 FFmpeg 提供音频格式标准化与切片功能。核心功能包括：
- **音频转换**：将任意媒体文件（视频、音频）转换为指定采样率、声道数的标准音频文件。
- **音频切片**：按时间区间从音频文件中截取片段。

模块通过封装 FFmpeg 命令行，提供统一的 Python API，并处理常见错误（如 FFmpeg 缺失、时间范围非法等）。

## 依赖
- Python 3.7+
- FFmpeg 可执行文件（需在系统路径中或通过配置指定）

## 安装
将模块目录添加到 Python 路径，或通过包管理工具安装（如 `pip install -e .`）。

## 模块结构
```
audio_processor/
├── __init__.py          # 可选，导出公共接口
├── config.py            # 配置类
├── exceptions.py        # 异常定义
├── processor.py         # 核心处理类
└── utils.py             # 底层工具函数
```

## 快速开始

### 1. 导入模块
```python
from audio_processor.processor import AudioProcessor
from audio_processor.config import AudioConfig
```

### 2. 创建处理器实例
```python
processor = AudioProcessor()  # 使用默认配置
```

### 3. 转换音频
```python
output = processor.convert(
    input_path="input.m4a",
    output_path="output.wav"
)
```

### 4. 切片音频
```python
output = processor.slice(
    input_path="audio.wav",
    output_path="slice.wav",
    start_sec=10.5,
    end_sec=20.0
)
```

## 配置说明
`AudioConfig` 类控制音频处理行为：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sample_rate` | int | 16000 | 输出音频采样率（Hz） |
| `output_format` | str | `"wav"` | 输出文件格式（扩展名） |
| `ffmpeg_path` | str | `"ffmpeg"` | FFmpeg 可执行文件路径或命令名 |
| `channels` | int | 1 | 输出音频声道数（1 = 单声道） |
| `overwrite` | bool | True | 是否覆盖已有输出文件 |
| `timeout_sec` | Optional[float] | 600.0 | FFmpeg 执行超时时间（秒） |
| `extra_args` | list[str] | [] | 附加 FFmpeg 参数（如 `["-b:a", "192k"]`） |

你可以为每次调用传入自定义配置：
```python
config = AudioConfig(sample_rate=44100, output_format="mp3", extra_args=["-b:a", "192k"])
output = processor.convert("input.wav", "output.mp3", options=config)
```

## API 参考

### `AudioProcessor.__init__(default_config: Optional[AudioConfig] = None)`
初始化处理器，可设置默认配置。

### `AudioProcessor.convert(input_path: str, output_path: str, options: Optional[AudioConfig] = None) -> str`
将输入媒体文件转换为标准化音频。
- **参数**：
  - `input_path`：输入文件路径（支持任何 FFmpeg 可读格式）
  - `output_path`：输出文件路径（若缺少扩展名，自动使用 `output_format` 补充）
  - `options`：本次调用使用的配置，若为 `None` 则使用默认配置
- **返回**：规范化后的输出文件路径
- **异常**：
  - `AudioProcessingError`：输入文件不存在或 FFmpeg 执行失败
  - `FFmpegNotFoundError`：未找到 FFmpeg

### `AudioProcessor.slice(input_path: str, output_path: str, start_sec: float, end_sec: float, options: Optional[AudioConfig] = None, fast_seek: bool = True) -> str`
从音频中截取指定时间区间。
- **参数**：
  - `input_path`：输入音频文件路径
  - `output_path`：输出文件路径
  - `start_sec`：起始时间（秒）
  - `end_sec`：结束时间（秒）
  - `options`：本次调用使用的配置
  - `fast_seek`：是否使用快速定位（`-ss` 放在输入前，速度更快但精度可能稍低）
- **返回**：输出文件路径
- **异常**：
  - `InvalidTimeRangeError`：时间范围非法（起始 < 0 或结束 <= 起始）
  - `AudioProcessingError`：输入文件不存在或 FFmpeg 执行失败
  - `FFmpegNotFoundError`：未找到 FFmpeg

## 异常处理
模块自定义了以下异常（定义在 `exceptions.py`）：

| 异常类 | 说明 |
|--------|------|
| `AudioProcessorError` | 所有异常的基类 |
| `FFmpegNotFoundError` | FFmpeg 不可用 |
| `AudioProcessingError` | FFmpeg 执行失败或输入文件无效 |
| `InvalidTimeRangeError` | 切片时间范围无效 |

推荐在调用时捕获这些异常以提供友好的反馈：
```python
from audio_processor.exceptions import AudioProcessingError, FFmpegNotFoundError, InvalidTimeRangeError

try:
    processor.slice(...)
except InvalidTimeRangeError as e:
    print(f"时间范围错误: {e}")
except FFmpegNotFoundError as e:
    print(f"请安装 FFmpeg: {e}")
except AudioProcessingError as e:
    print(f"处理失败: {e}")
```

## 日志
模块使用 Python 标准 `logging` 记录处理进度和调试信息。可通过配置日志级别（如 `logging.basicConfig(level=logging.INFO)`）查看执行详情。

## 注意事项
- 确保 FFmpeg 已正确安装，可通过 `ffmpeg -version` 验证。
- 切片时，`fast_seek` 选项会牺牲一定精度（通常可接受），若需要精确切片可设为 `False`。
- 输出目录会自动创建（包括父目录）。

## 贡献与扩展
如需添加新的音频处理功能，可在 `utils.py` 中构建新的 FFmpeg 命令，并在 `AudioProcessor` 中暴露高层方法。保持 `config.py` 与 `exceptions.py` 的独立性。
