from __future__ import annotations

LOW_CONFIDENCE = "low_confidence"
LOW_VOICED_RATIO = "low_voiced_ratio"
TOO_SHORT = "too_short"
TOO_UNSTABLE = "too_unstable"
OUTSIDE_VOCAL_RANGE = "outside_vocal_range"
OCTAVE_OUTLIER = "octave_outlier"
LIKELY_HARMONIC = "likely_harmonic"
LIKELY_ACCOMPANIMENT_BLEED = "likely_accompaniment_bleed"
DUPLICATE_FRAGMENT = "duplicate_fragment"
OVERLAPS_STRONGER_CANDIDATE = "overlaps_stronger_candidate"
INSUFFICIENT_ONSET_EVIDENCE = "insufficient_onset_evidence"
SILENCE_OR_BREATH_REGION = "silence_or_breath_region"
UNCERTAIN = "uncertain"
SUSPECTED_VIBRATO = "suspected_vibrato"
SUSPECTED_GLIDE = "suspected_glide"
LARGE_QUANTIZE_ERROR = "large_quantize_error"
HIGH_QUANTIZE_ERROR = LARGE_QUANTIZE_ERROR
DP_FALLBACK = "dp_fallback"
RHYTHM_GRID_UNAVAILABLE = "rhythm_grid_unavailable"
DP_NO_CANDIDATE_PATH = "dp_no_candidate_path"
QUANTIZER_BACKEND_UNSUPPORTED = "quantizer_backend_unsupported"
POSSIBLE_FRAGMENTATION = "possible_fragmentation"
POSSIBLE_OVERMERGE = "possible_overmerge"
SHORT_GAP_BRIDGED = "short_gap_bridged"
SHORT_NOTE_ABSORBED = "short_note_absorbed"
OCTAVE_JUMP_CORRECTED = "octave_jump_corrected"
PHRASE_MEDIAN_SMOOTHED = "phrase_median_smoothed"
FRAGMENTATION_RISK = POSSIBLE_FRAGMENTATION
OVERMERGE_RISK = POSSIBLE_OVERMERGE

REJECTION_REASON_CODES = {
    LOW_CONFIDENCE,
    LOW_VOICED_RATIO,
    TOO_SHORT,
    TOO_UNSTABLE,
    OUTSIDE_VOCAL_RANGE,
    OCTAVE_OUTLIER,
    LIKELY_HARMONIC,
    LIKELY_ACCOMPANIMENT_BLEED,
    DUPLICATE_FRAGMENT,
    OVERLAPS_STRONGER_CANDIDATE,
    INSUFFICIENT_ONSET_EVIDENCE,
    SILENCE_OR_BREATH_REGION,
}
