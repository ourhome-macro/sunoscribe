from dataclasses import dataclass
from pathlib import Path


@dataclass
class PitchDetectionConfig:
    """Configuration for pitch detection and note quantization."""

    # Base settings
    sample_rate: int = 22050
    confidence_threshold: float = 0.5
    pitch_backend: str = "rmvpe"  # "rmvpe" / "crepe" / "basic-pitch"
    pitch_backend_fallbacks: tuple[str, ...] = ()
    pitch_profile: str = "production"
    allow_backend_fallbacks: bool = False

    # Runtime limits
    max_audio_length_sec: float = 600.0
    chunk_size_sec: float = 30.0

    # RMVPE settings
    rmvpe_model_path: str | None = None
    rmvpe_sample_rate: int = 16000
    rmvpe_step_size_ms: int = 10
    rmvpe_vuv_threshold: float = 0.03

    # CREPE settings
    crepe_model_capacity: str = "full"  # tiny/small/medium/large/full
    crepe_step_size_ms: int = 10
    crepe_vuv_confidence_threshold: float = 0.45
    crepe_min_note_duration_sec: float = 0.08
    crepe_min_voiced_frames: int = 3
    crepe_pitch_jump_semitones: float = 1.2
    crepe_max_unvoiced_gap_sec: float = 0.03
    crepe_smoothing_window: int = 7
    crepe_note_mad_good_semitones: float = 0.18
    crepe_note_mad_bad_semitones: float = 0.75
    crepe_note_span_soft_semitones: float = 0.8
    crepe_note_span_hard_semitones: float = 3.0

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

    # Melody selection settings
    melody_selector_enabled: bool = True
    melody_pitch_min_midi: int = 48
    melody_pitch_max_midi: int = 84
    melody_min_confidence: float = 0.52
    melody_min_duration_sec: float = 0.12
    melody_short_note_sec: float = 0.18
    melody_short_note_min_confidence: float = 0.62
    melody_merge_gap_sec: float = 0.08
    melody_merge_pitch_tolerance_semitones: int = 1
    melody_conflict_window_sec: float = 0.10
    melody_large_jump_semitones: int = 12
    melody_isolated_note_max_duration_sec: float = 0.25
    melody_isolated_note_min_confidence: float = 0.62

    # Source arbitration settings
    melody_arbitrator_enabled: bool = True
    basic_pitch_support_enabled: bool = True
    arrangement_transition_window_bars: float = 1.0
    arrangement_min_transition_window_sec: float = 0.5
    arrangement_max_transition_window_sec: float = 4.0
    arrangement_lead_conflict_window_sec: float = 0.12
    arrangement_support_conflict_window_sec: float = 0.08
    arrangement_lead_max_polyphony: int = 1
    arrangement_vocal_support_max_polyphony: int = 1
    arrangement_climax_support_max_polyphony: int = 2
    arrangement_instrumental_max_polyphony: int = 3
    arrangement_climax_support_density_per_sec: float = 1.2

    # Analysis settings
    bpm_start_bpm: float = 120.0
    bpm_refine_enabled: bool = True
    bpm_refine_ioi_weight: float = 0.85
    bpm_refine_raw_weight: float = 0.15
    bpm_refine_trim_percent: float = 10.0
    bpm_refine_min_beats: int = 4
    bpm_refine_min_intervals: int = 3
    bpm_refine_min_intervals_for_trim: int = 12
    bpm_refine_stability_mad_good: float = 0.08
    bpm_refine_stability_mad_bad: float = 0.18
    bpm_refine_disagreement_soft: float = 0.10
    bpm_refine_disagreement_hard: float = 0.35
    bpm_refine_min_coverage: float = 0.25
    bpm_candidate_min: float = 35.0
    bpm_candidate_max: float = 260.0
    bpm_preferred_min: float = 60.0
    bpm_preferred_max: float = 200.0
    bpm_window_size_intervals: int = 4
    key_min_confidence: float = 0.10
    key_backend: str = "librosa"  # "librosa" / "music21" / "auto"
    key_enable_music21_fallback: bool = True
    downbeat_backend: str = "librosa"
    beats_per_bar: int = 4
    beat_unit: int = 4

    def resolved_cache_dir(self) -> Path:
        return Path(self.cache_dir).expanduser().resolve()
