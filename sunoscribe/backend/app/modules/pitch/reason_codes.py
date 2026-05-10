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
HIGH_QUANTIZE_ERROR = "high_quantize_error"
DP_FALLBACK = "dp_fallback"
RHYTHM_GRID_UNAVAILABLE = "rhythm_grid_unavailable"
DP_NO_CANDIDATE_PATH = "dp_no_candidate_path"
QUANTIZER_BACKEND_UNSUPPORTED = "quantizer_backend_unsupported"
FRAGMENTATION_RISK = "fragmentation_risk"
OVERMERGE_RISK = "overmerge_risk"

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
