from dataclasses import dataclass
from pathlib import Path


@dataclass
class PitchDetectionConfig:
    """Configuration for pitch detection and note quantization."""

    # Base settings
    sample_rate: int = 22050
    confidence_threshold: float = 0.5
    pitch_backend: str = "crepe"  # "crepe" / "basic-pitch"

    # Runtime limits
    max_audio_length_sec: float = 600.0
    chunk_size_sec: float = 30.0

    # CREPE settings
    crepe_model_capacity: str = "full"  # tiny/small/medium/large/full
    crepe_step_size_ms: int = 10
    crepe_vuv_confidence_threshold: float = 0.45
    crepe_min_note_duration_sec: float = 0.08
    crepe_min_voiced_frames: int = 3
    crepe_pitch_jump_semitones: float = 1.2
    crepe_max_unvoiced_gap_sec: float = 0.03
    crepe_smoothing_window: int = 7

    # Quantization settings (P1)
    quantize_mode: str = "adaptive"  # "strict" / "adaptive"
    quantize_precision: float = 0.0625  # 1/16 beat
    quantize_min_duration_beats: float = 0.125  # filter too-short notes (default 1/32)
    quantize_jitter_tolerance_beats: float = 0.05
    adaptive_dotted_tolerance_beats: float = 0.12
    adaptive_triplet_tolerance_beats: float = 0.08
    quantize_noise_confidence_floor: float = 0.35
    quantize_merge_same_pitch_enabled: bool = True
    quantize_merge_same_pitch_gap_sec: float = 0.06
    quantize_merge_min_confidence: float = 0.5
    quantize_merge_near_pitch_enabled: bool = False
    quantize_merge_near_pitch_max_semitone: int = 1
    quantize_overlap_resolution_enabled: bool = True
    quantize_overlap_min_gap_sec: float = 0.005

    # Cache settings
    enable_cache: bool = True
    cache_dir: str = "~/.cache/sunoscribe/pitch"

    # Analysis settings
    bpm_start_bpm: float = 120.0
    key_min_confidence: float = 0.10
    key_backend: str = "librosa"  # "librosa" / "music21" / "auto"
    key_enable_music21_fallback: bool = True
    downbeat_backend: str = "librosa"
    beats_per_bar: int = 4
    beat_unit: int = 4

    def resolved_cache_dir(self) -> Path:
        return Path(self.cache_dir).expanduser().resolve()
