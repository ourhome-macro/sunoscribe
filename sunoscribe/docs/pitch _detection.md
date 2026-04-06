# pitch _detection
## 概述
本模块基于 basic-pitch 与 librosa 提供音高检测与分析功能。核心功能包括：
- **音高检测**：使用 basic-pitch 模型从音频中提取音符序列（音高、起止时间、置信度）。
- **节拍追踪**：基于 librosa 检测 BPM 与节拍时间点。
- **调式分析**：使用 chroma 特征配合 Krumhansl-Schmuckler 模板分析音频调式。
模块通过流水线架构整合三大功能，提供统一的 Python API，并处理常见错误（如依赖缺失、音频过长、置信度过低等）。
## 依赖
- Python 3.7+
- basic-pitch
- librosa
- numpy
## 安装
将模块目录添加到 Python 路径，或通过包管理工具安装。
```bash
# 安装核心依赖
pip install basic-pitch librosa numpy
```
## 模块结构
```
pitch_detection/
├── __init__.py          # 模块初始化，导出公共接口
├── config.py            # 配置类
├── exceptions.py        # 异常定义
├── types.py             # 数据结构定义
├── detector.py          # 音高检测器
├── beat_tracker.py      # 节拍追踪器
├── key_analyzer.py      # 调式分析器
├── pipeline.py          # 流水线整合
└── serializer.py        # 结果序列化
```
## 快速开始
### 1. 导入模块
```python
from pitch_detection import PitchPipeline, PitchDetectionConfig
```
### 2. 创建流水线实例
```python
pipeline = PitchPipeline()  # 使用默认配置
```
### 3. 执行分析
```python
result = pipeline.run("input_song.wav")
print(f"BPM: {result.meta.bpm}")
print(f"调式: {result.meta.key}")
print(f"音符数量: {len(result.raw_notes)}")
```
### 4. 序列化输出
```python
from pitch_detection import PitchResultSerializer
json_output = PitchResultSerializer.to_json(result)
print(json_output)
```
## 配置说明
`PitchDetectionConfig` 类控制分析行为：
| 参数                   | 类型  | 默认值                        | 说明               |
| ---------------------- | ----- | ----------------------------- | ------------------ |
| `sample_rate`          | int   | 22050                         | 音频采样率         |
| `confidence_threshold` | float | 0.5                           | 音高检测置信度阈值 |
| `max_audio_length_sec` | float | 600.0                         | 最大音频时长（秒） |
| `chunk_size_sec`       | float | 30.0                          | 分块处理时长       |
| `enable_cache`         | bool  | True                          | 是否启用缓存       |
| `cache_dir`            | str   | `"~/.cache/sunoscribe/pitch"` | 缓存目录           |
| `bpm_start_bpm`        | float | 120.0                         | BPM 检测起始猜测值 |
| `key_min_confidence`   | float | 0.10                          | 调式分析最小置信度 |
| 你可以传入自定义配置： |       |                               |                    |
```python
config = PitchDetectionConfig(
    confidence_threshold=0.7,
    max_audio_length_sec=300.0
)
pipeline = PitchPipeline(config)
```
## API 参考
### `PitchPipeline.__init__(config: Optional[PitchDetectionConfig] = None)`
初始化流水线，自动加载所有子模块。
### `PitchPipeline.run(audio_path: str) -> PitchAnalysisResult`
执行完整的音高分析流程。
- **参数**：
  - `audio_path`：输入音频文件路径
- **返回**：`PitchAnalysisResult` 对象，包含以下属性：
  - `version`：分析器版本号
  - `meta`：元信息（BPM、调式、时长等）
  - `raw_notes`：原始音符序列
  - `warnings`：警告信息列表
- **异常**：
  - `PitchDetectionFailedError`：音频文件不存在或推理失败
  - `AudioTooLongError`：音频时长超过限制
  - `PitchModelUnavailableError`：basic-pitch 未安装
  - `NoBeatsDetectedError`：无法检测到节拍
  - `KeyAnalysisLowConfidenceError`：调式分析置信度过低
### `PitchDetector.detect(audio_path: str) -> List[Note]`
仅执行音高检测，返回原始音符序列。
### `BeatTracker.track(audio_path: str) -> BeatTrackingResult`
仅执行节拍追踪，返回 BPM 与节拍时间点。
### `KeyAnalyzer.analyze(audio_path: str) -> KeyAnalysisResult`
仅执行调式分析，返回调式名称与置信度。
## 数据结构
### `Note`
| 字段         | 类型  | 说明                       |
| ------------ | ----- | -------------------------- |
| `pitch`      | str   | 音符名称（如 "C4", "F#5"） |
| `start_time` | float | 起始时间（秒）             |
| `end_time`   | float | 结束时间（秒）             |
| `confidence` | float | 检测置信度                 |
### `MetaInfo`
| 字段             | 类型  | 说明                            |
| ---------------- | ----- | ------------------------------- |
| `bpm`            | float | 检测到的 BPM                    |
| `bpm_confidence` | float | BPM 置信度                      |
| `key`            | str   | 调式（如 "C Major", "A Minor"） |
| `key_confidence` | float | 调式置信度                      |
| `duration_sec`   | float | 音频总时长                      |
### `PitchAnalysisResult`
完整的分析结果，包含 `version`、`meta`、`raw_notes`、`warnings` 等字段。
## 异常处理
模块自定义了以下异常（定义在 `exceptions.py`）：
| 异常类                          | 说明                         |
| ------------------------------- | ---------------------------- |
| `PitchDetectionError`           | 所有异常的基类               |
| `AudioTooLongError`             | 音频超过最大长度限制         |
| `PitchModelUnavailableError`    | basic-pitch 不可用或加载失败 |
| `PitchDetectionFailedError`     | 音高检测失败                 |
| `NoBeatsDetectedError`          | 无法检测到 BPM               |
| `KeyAnalysisLowConfidenceError` | 调式分析置信度过低           |
| 推荐在调用时捕获这些异常：      |                              |
```python
from pitch_detection.exceptions import (
    PitchDetectionFailedError,
    AudioTooLongError,
    PitchModelUnavailableError,
    NoBeatsDetectedError,
    KeyAnalysisLowConfidenceError
)
try:
    result = pipeline.run("input.wav")
except AudioTooLongError as e:
    print(f"音频过长: {e}")
except PitchModelUnavailableError as e:
    print(f"请安装 basic-pitch: {e}")
except PitchDetectionFailedError as e:
    print(f"检测失败: {e}")
except NoBeatsDetectedError as e:
    print(f"节拍检测失败: {e}")
except KeyAnalysisLowConfidenceError as e:
    print(f"调式分析置信度过低: {e}")
```
## 底层实现细节
### 音高检测
- 使用 basic-pitch 预训练模型进行推理
- 支持置信度过滤与最小音符长度控制
- 自动过滤低于阈值的结果
### 节拍追踪
- 基于 librosa 的 `beat_track` 算法
- 通过 onset 强度计算置信度
- 支持自定义起始 BPM 猜测
### 调式分析
- 提取 chroma 特征（CQT）
- 使用 Krumhansl-Schmuckl 大调/小调模板进行相关性匹配
- 通过最佳匹配与次佳匹配的差距计算置信度
## 注意事项
- **依赖安装**：确保已安装 basic-pitch 及其所有依赖（首次使用可能需要下载模型）。
- **音频格式**：推荐使用 WAV 格式，其他格式依赖 librosa 的后端支持。
- **性能考虑**：basic-pitch 推理较耗时，长音频会分块处理。
- **置信度调优**：可根据实际场景调整 `confidence_threshold`，过高可能导致漏检，过低可能产生误检。

## 实测与环境复现（2026-04-06）

### 环境结论

- Python `3.12` 下，`basic-pitch` 依赖链存在兼容问题，无法稳定安装。
- Python `3.10` 下可正常安装 `basic-pitch` 并完成完整推理（包含 `raw_notes`）。
- 推荐将 **生产/联调环境固定为 Python 3.10**。

### 清华源 + Python3.10 复现步骤

在 `backend/` 目录执行：

```powershell
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip setuptools wheel
.\.venv310\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.\.venv310\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple basic-pitch
.\.venv310\Scripts\python.exe tests/run_pitch_samples.py
```

### 样本文件

- `backend/app/modules/pitch/samples/song_001_vocals.wav`
- `backend/app/modules/pitch/samples/song_001_accompaniment.wav`

### 终端实测结果摘要

#### 纯人声 `song_001_vocals.wav`

- mode: `full_pipeline`
- bpm: `117.45383522727273`
- key: `A Major`
- key_confidence: `0.7018047707611877`
- duration_sec: `246.2506575963719`
- raw_notes_count: `525`

#### 纯伴奏 `song_001_accompaniment.wav`

- mode: `full_pipeline`
- bpm: `117.45383522727273`
- key: `A Major`
- key_confidence: `0.7299437602123495`
- duration_sec: `246.2506575963719`
- raw_notes_count: `543`

### 已修复兼容点

- `beat_tracker.py` 已兼容 `librosa.beat.beat_track` 在不同版本返回 `tempo` 标量/数组两种形式，避免 `TypeError: only 0-dimensional arrays can be converted to Python scalars`。
## 开发规划
### 当前状态：P0 - 最小可用版本（MVP）
| 版本 | 状态                       |
| ---- | -------------------------- |
| P0   | ✅ 代码完成，待真实推理验证 |
| P1   | ⏳ 设计阶段                 |
| P2   | 📋 规划阶段                 |
### P0 - 最小可用版本（当前）
**目标**：快速出结果，让产品能跑起来。
**输出内容**：
| 输出项         | 示例                                         |
| -------------- | -------------------------------------------- |
| 音符序列       | `[{pitch: "C4", start: 0.5, end: 0.8}, ...]` |
| BPM            | 120                                          |
| 调式           | C Major                                      |
| **功能边界**： |                                              |
- ✅ 原始音符序列提取
- ✅ BPM 检测
- ✅ 调式分析
- ❌ 小节划分
- ❌ 音符量化
- ❌ MIDI 导出
- ❌ 歌词对齐
### P1 - 乐谱化处理
**目标**：将原始音符序列转化为可编辑的乐谱数据。
**新增输出**：
| 输出项         | 说明                           |
| -------------- | ------------------------------ |
| 量化音符       | 把秒转换为四分/八分/十六分音符 |
| 小节划分       | 按 BPM 切分小节                |
| MIDI 导出      | 生成标准 MIDI 文件             |
| **计划模块**： |                                |
- `quantizer.py` - 音符时值量化
- `measure_splitter.py` - 小节切分
- `midi_exporter.py` - MIDI 文件生成
- `rhythm_analyzer.py` - 节奏稳定性分析
**量化逻辑示例**：
```
原始: start=0.52s, end=0.78s
量化: start=八分音符, duration=八分音符
```
### P2 - 高级分析
**目标**：增强产品竞争力，提供深度音乐分析。
**新增输出**：
| 输出项         | 说明             |
| -------------- | ---------------- |
| 和弦进行       | C → Am → F → G   |
| 旋律轮廓       | 上行/下行/波浪形 |
| 难度评估       | 初级/中级/高级   |
| 演奏建议       | 指法推荐、换气点 |
| **计划模块**： |                  |
- `chord_analyzer.py` - 和弦识别
- `melody_analyzer.py` - 旋律轮廓分析
- `difficulty_evaluator.py` - 难度评估
- `fingering_advisor.py` - 指法建议
**可选扩展**：
- 歌词对齐（需要 ASR 模块）
- 多乐器分离
- 风格分类（流行/古典/爵士）
### 版本依赖关系
```
P0 (原始数据)
└── 验证通过
    └── P1 (乐谱化)
        └── 验证通过
            └── P2 (高级分析)
```
## 贡献与扩展
如需扩展功能（如添加量化、小节切分等），可在 `pipeline.py` 中扩展 `PitchAnalysisResult` 的 `analysis_info` 字段，或添加新的处理模块。保持配置、异常与数据结构的独立性。