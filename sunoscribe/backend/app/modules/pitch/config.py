from dataclasses import dataclass
from pathlib import Path


@dataclass
class PitchDetectionConfig:
    """音高检测配置。"""

    # 基础参数
    sample_rate: int = 22050
    confidence_threshold: float = 0.5

    # 性能参数
    max_audio_length_sec: float = 600.0
    chunk_size_sec: float = 30.0

    # 量化参数（P1）
    quantize_mode: str = "adaptive"  # "strict" / "adaptive"
    quantize_precision: float = 0.0625  # 1/16 拍

    # 缓存参数（P0 先保留，不强依赖实现）
    enable_cache: bool = True
    cache_dir: str = "~/.cache/sunoscribe/pitch"

    # 分析参数
    bpm_start_bpm: float = 120.0
    key_min_confidence: float = 0.10
    downbeat_backend: str = "librosa"
    beats_per_bar: int = 4
    beat_unit: int = 4

    def resolved_cache_dir(self) -> Path:
        return Path(self.cache_dir).expanduser().resolve()
