# SunoScribe Backend

## Pitch 模块（P0）

当前已实现 `app/modules/pitch` 的 P0 能力：

- 音高检测：`basic-pitch`
- BPM 检测：`librosa`
- 调式分析：`librosa chroma + Krumhansl-Schmuckler`
- 输出：原始音符序列 + BPM + 调式（不做小节划分，不做量化）

## 主要文件

- `app/modules/pitch/config.py`
- `app/modules/pitch/exceptions.py`
- `app/modules/pitch/types.py`
- `app/modules/pitch/detector.py`
- `app/modules/pitch/beat_tracker.py`
- `app/modules/pitch/key_analyzer.py`
- `app/modules/pitch/serializer.py`
- `app/modules/pitch/pipeline.py`
- `tests/test_pitch_pipeline.py`

## 测试

当前提供了一个最小单测，使用 mock 避免依赖实际模型下载与真实音频：

- `tests/test_pitch_pipeline.py`
