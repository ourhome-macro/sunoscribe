from __future__ import annotations

LOW_CONFIDENCE = "low_confidence"
LOW_VOICED_RATIO = "low_voiced_ratio"
TOO_SHORT = "too_short"
TOO_UNSTABLE = "too_unstable"
OUTSIDE_VOCAL_RANGE = "outside_vocal_range"
OCTAVE_OUTLIER = "octave_outlier"
PRESELECTOR_LOW_OCTAVE_CORRECTED = "preselector_low_octave_corrected"
LIKELY_HARMONIC = "likely_harmonic"
LIKELY_ACCOMPANIMENT_BLEED = "likely_accompaniment_bleed"
DUPLICATE_FRAGMENT = "duplicate_fragment"
OVERLAPS_STRONGER_CANDIDATE = "overlaps_stronger_candidate"
INSUFFICIENT_ONSET_EVIDENCE = "insufficient_onset_evidence"
SILENCE_OR_BREATH_REGION = "silence_or_breath_region"
UNCERTAIN = "uncertain"
SUSPECTED_VIBRATO = "suspected_vibrato"
SUSPECTED_GLIDE = "suspected_glide"
POST_F0_CONTOUR_BRIDGE = "post_f0_contour_bridge"
CONTOUR_TO_CANDIDATE_BRIDGE = "contour_to_candidate_bridge"
BRIDGE_FROM_F0_CONTOUR = "bridge_from_f0_contour"
BRIDGE_FROM_VOICED_CONTOUR = "bridge_from_voiced_contour"
BRIDGE_CONFIDENCE_GUARDED = "bridge_confidence_guarded"
CONTOUR_CANDIDATE_CONTEXT_GUARDED = "contour_candidate_context_guarded"
CONTOUR_CANDIDATE_NO_RAW_GAP = "contour_candidate_no_raw_gap"
CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT = "contour_candidate_no_local_context"
CONTOUR_CANDIDATE_SPLITS_BIG_GAP = "contour_candidate_splits_big_gap"
BRIDGE_UNSTABLE_CONTOUR_GUARDED = "bridge_unstable_contour_guarded"
BRIDGE_LOW_CONFIDENCE_LONG_CONTOUR = "bridge_low_confidence_long_contour"
BRIDGE_NO_SELECTED_GAP = "bridge_no_selected_gap"
BRIDGE_VOCAL_ACTIVITY_UNSUPPORTED = "bridge_vocal_activity_unsupported"
BRIDGE_OVERLAPS_RAW_CANDIDATE = "bridge_overlaps_raw_candidate"
BRIDGE_OVERLAPS_SELECTED_NOTE = "bridge_overlaps_selected_note"
LARGE_QUANTIZE_ERROR = "large_quantize_error"
HIGH_QUANTIZE_ERROR = LARGE_QUANTIZE_ERROR
QUANTIZED_DURATION_TOO_SHORT = "quantized_duration_too_short"
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
ISOLATED_FRAGMENT_REMOVED = "isolated_fragment_removed"
PHRASE_GAP_SUSTAINED = "phrase_gap_sustained"
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
    BRIDGE_NO_SELECTED_GAP,
    BRIDGE_LOW_CONFIDENCE_LONG_CONTOUR,
    CONTOUR_CANDIDATE_NO_RAW_GAP,
    CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT,
    CONTOUR_CANDIDATE_SPLITS_BIG_GAP,
    BRIDGE_VOCAL_ACTIVITY_UNSUPPORTED,
    BRIDGE_OVERLAPS_RAW_CANDIDATE,
    BRIDGE_OVERLAPS_SELECTED_NOTE,
}
