from dataclasses import dataclass
from pathlib import Path


@dataclass
class PitchDetectionConfig:
    """P0 音高检测配置。"""

    # 基础参数
    sample_rate: int = 22050
    confidence_threshold: float = 0.5

    # 性能参数
    max_audio_length_sec: float = 600.0
    chunk_size_sec: float = 30.0

    # 缓存参数（P0 先保留，不强依赖实现）
    enable_cache: bool = True
    cache_dir: str = "~/.cache/sunoscribe/pitch"

    # 分析参数
    bpm_start_bpm: float = 120.0
    key_min_confidence: float = 0.10

    def resolved_cache_dir(self) -> Path:
        return Path(self.cache_dir).expanduser().resolve()
