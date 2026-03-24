# Vocal Separator 模块
## 概述
本模块基于 Demucs 模型提供音轨分离功能（如人声与伴奏分离）。核心功能包括：
- **模型管理**：自动检测设备（CPU/GPU）、管理模型缓存与下载。
- **音频分离**：支持将音频文件分离为人声和伴奏，自动处理音频格式转换与标准化。
模块通过封装 Demucs 推理流程，提供统一的 Python API，并处理常见错误（如缺少依赖、格式不支持等）。
## 依赖
- Python 3.10+
- PyTorch
- Demucs
- Torchaudio
- SoundFile (作为 Torchaudio 的后端备选方案)
- Numpy
## 安装
将模块目录添加到 Python 路径，或通过包管理工具安装。
```bash
# 安装核心依赖
pip install torch torchaudio demucs soundfile numpy
```
## 模块结构
```
vocal/
├── __init__.py           # 模块初始化
├── model_manager.py      # 模型加载与设备管理
├── separator.py          # 核心分离逻辑
├── seprarator.py         # 向后兼容的拼写错误别名
└── test.py               # 测试用例
```
## 快速开始
### 1. 导入模块
```python
from app.modules.vocal.separator import VocalSeparator
from app.modules.vocal.model_manager import DemucsModelManager
```
### 2. 创建分离器实例
```python
# 使用默认配置（自动检测 GPU/CPU，加载 htdemucs 模型）
separator = VocalSeparator()
```
### 3. 执行分离
```python
result = separator.separate(
    input_audio_path="input_song.wav",
    output_dir="output/",
    stem_prefix="song_001"
)
print(f"人声路径: {result.vocal_path}")
print(f"伴奏路径: {result.accompaniment_path}")
```
## 配置说明
### `DemucsModelManager` 参数
控制模型加载行为：
| 参数          | 类型           | 默认值       | 说明             |
| ------------- | -------------- | ------------ | ---------------- |
| `model_name`  | str            | `"htdemucs"` | Demucs 模型名称  |
| `cache_root`  | Optional[Path] | `~/.cache`   | 模型缓存根目录   |
| `prefer_cuda` | bool           | True         | 是否优先使用 GPU |
### `VocalSeparator` 参数
控制分离器初始化：
| 参数                  | 类型                         | 默认值 | 说明                             |
| --------------------- | ---------------------------- | ------ | -------------------------------- |
| `model_manager`       | Optional[DemucsModelManager] | None   | 自定义模型管理器，为空则自动创建 |
| `cpu_max_concurrency` | int                          | 1      | CPU 模式下的最大并发数，防止过载 |
### `separate` 方法参数
控制具体的分离任务：
| 参数               | 类型 | 默认值        | 说明             |
| ------------------ | ---- | ------------- | ---------------- |
| `input_audio_path` | str  | 必填          | 输入音频文件路径 |
| `output_dir`       | str  | 必填          | 输出目录         |
| `stem_prefix`      | str  | `"separated"` | 输出文件名前缀   |
| `sample_rate`      | int  | 44100         | 输出音频采样率   |
## API 参考
### `DemucsModelManager.__init__(...)`
初始化模型管理器，自动检测运行设备。
### `DemucsModelManager.load_model() -> torch.nn.Module`
加载 Demucs 预训练模型。
- **行为**：
  - 若本地缓存存在，直接加载。
  - 若不存在，尝试从网络下载（需要网络连接）。
- **异常**：
  - `ModelManagerError`: Demucs 未安装或模型下载/加载失败。
### `VocalSeparator.__init__(...)`
初始化分离器，内部会调用 `load_model()` 预加载模型。
### `VocalSeparator.separate(...) -> SeparationResult`
执行音轨分离。
- **返回**：`SeparationResult` 对象，包含 `vocal_path` 和 `accompaniment_path` 属性。
- **异常**：
  - `SeparationError`: 输入文件不存在、格式不支持或推理过程失败。
## 异常处理
模块自定义了以下异常：
| 异常类                 | 说明                                 |
| ---------------------- | ------------------------------------ |
| `ModelManagerError`    | 模型加载失败或缓存验证失败           |
| `SeparationError`      | 分离过程中的错误（IO、推理、格式等） |
| 推荐在调用时捕获异常： |                                      |
```python
from app.modules.vocal.separator import SeparationError
from app.modules.vocal.model_manager import ModelManagerError
try:
    separator = VocalSeparator()
    result = separator.separate("input.mp3", "output")
except ModelManagerError as e:
    print(f"模型加载失败，请检查网络或安装 demucs: {e}")
except SeparationError as e:
    print(f"分离失败: {e}")
```
## 底层实现细节
### 音频后端策略
为了兼容性，模块采用了多级回退策略处理音频读写：
1. **首选 Torchaudio**: 尝试使用 `torchaudio.load` / `torchaudio.save`。
2. **自动回退 Soundfile**:
   - 如果 Torchaudio 报错提示缺少 `torchcodec`（常见于新版本环境），模块会自动捕获该异常。
   - 自动回退到 `soundfile` 库进行读写。
   - 数据格式转换：Soundfile 返回 `[time, channels]`，模块会自动转换为 Torchaudio 标准的 `[channels, time]` 格式。
### 推理与并发控制
- **GPU 模式**: 默认不限制并发，充分利用 GPU 算力。
- **CPU 模式**: 使用 `threading.Semaphore` 限制并发数（默认为 1），防止多任务同时运行导致系统资源耗尽。
### 模型缓存
- 模型文件默认缓存在 `~/.cache/torch/hub/checkpoints`。
- 首次运行需要联网下载，下载完成后可离线运行。
## 注意事项
- **输入格式**: 推荐使用 WAV 格式以确保兼容性。MP4 等视频容器格式需要系统安装 FFmpeg，且部分后端（如 pure soundfile）可能不支持。
- **内存消耗**: Demucs 模型对内存需求较高，CPU 模式下建议预留 8GB+ 内存。
- **首次运行**: 请确保网络畅通以便下载预训练模型。
