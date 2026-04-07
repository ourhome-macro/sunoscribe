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
    quantize_min_duration_beats: float = 0.125  # 过滤极短噪声音符（默认 1/32）
    quantize_jitter_tolerance_beats: float = 0.05  # 最小时值附近抖动收敛窗口
    adaptive_dotted_tolerance_beats: float = 0.12  # 附点音符容差
    adaptive_triplet_tolerance_beats: float = 0.08  # 三连音容差
    quantize_noise_confidence_floor: float = 0.35  # 过滤低置信噪声
    quantize_merge_same_pitch_enabled: bool = True  # 启用相邻同音符合并
    quantize_merge_same_pitch_gap_sec: float = 0.06  # 同音符合并最大间隙（秒）
    quantize_merge_min_confidence: float = 0.5  # 参与同音符合并的最低置信度
    quantize_merge_near_pitch_enabled: bool = False  # 可选：启用近音（半音邻近）合并
    quantize_merge_near_pitch_max_semitone: int = 1  # 近音合并最大半音差
    quantize_overlap_resolution_enabled: bool = True  # 启用重叠音符冲突消解
    quantize_overlap_min_gap_sec: float = 0.005  # 冲突消解后最小间隙

    # 缓存参数（P0 先保留，不强依赖实现）
    enable_cache: bool = True
    cache_dir: str = "~/.cache/sunoscribe/pitch"

    # 分析参数
    bpm_start_bpm: float = 120.0
    key_min_confidence: float = 0.10
    key_backend: str = "librosa"  # "librosa" / "music21" / "auto"
    key_enable_music21_fallback: bool = True
    downbeat_backend: str = "librosa"
    beats_per_bar: int = 4
    beat_unit: int = 4

    def resolved_cache_dir(self) -> Path:
        return Path(self.cache_dir).expanduser().resolve()
