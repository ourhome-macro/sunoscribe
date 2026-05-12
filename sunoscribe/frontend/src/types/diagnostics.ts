export interface DerivedDiagnosticsSummary {
  summary: string
  f0_track_available: boolean
  note_candidates_available: boolean
  rhythm_grid_available: boolean
  score_revision_id: string
}

export interface QuantizationDiagnostics {
  fallback_used: boolean
  fallback_reason: string | null
  mean_error_beats: number | null
  p95_error_beats: number | null
  max_error_beats: number | null
  fragmentation: number
  overmerge: number
}

export interface ShortNoteDiagnostics {
  too_short_count: number
  low_voiced_ratio_count: number
  suspected_vibrato_count: number
  suspected_glide_count: number
}


export interface ContinuityDiagnostics {
  note_count: number
  gap50_ratio: number | null
  big_gap_count: number
  short_note_ratio: number | null
  large_jump_ratio: number | null
  local_adjacent_pair_count: number
  local_large_jump_count: number
  local_large_jump_ratio: number | null
  cross_phrase_adjacent_pair_count: number
  cross_phrase_large_jump_count: number
  cross_phrase_large_jump_ratio: number | null
  median_pitch: number | null
  pitch_range: [number | null, number | null]
}

export interface ReferenceAlignmentDiagnostics {
  available: boolean
  diagnostic_only: boolean
  reference_suspect: boolean
  reason_codes: string[]
  expected_first_note_time_sec: number | null
  predicted_first_note_time_sec: number | null
  first_note_delay_sec: number | null
  possible_global_time_offset_sec: number | null
  best_time_shift_note_recall: number | null
  smart_onset_shift_sec: number | null
  smart_onset_shift_recall: number | null
  best_octave_shift_semitones: number | null
  best_octave_shift_note_recall: number | null
  median_pitch_delta_raw: number | null
  octave_normalized_recall_lift: number | null
  dtw_recall_lift: number | null
  raw_match_rate_vs_expected: number | null
  expected_predicted_time_overlap_ratio: number | null
}
export interface PhrasePostprocessAction {
  action: string
  reason_code: string
  note_ids: string[]
  output_note_id: string | null
  start_time_sec: number | null
  end_time_sec: number | null
  pitch_before_midi: number | null
  pitch_after_midi: number | null
  details: Record<string, unknown>
}

export interface PhrasePostprocessDiagnostics {
  available: boolean
  enabled: boolean
  input_note_count: number | null
  output_note_count: number | null
  iteration_count: number | null
  action_count: number
  action_counts: Record<string, number>
  reason_code_counts: Record<string, number>
  actions: PhrasePostprocessAction[]
}

export interface SelectedMelodyDiagnostics {
  available: boolean
  input_candidate_count: number
  pre_postprocess_selected_count: number | null
  selected_count: number
  rejected_count: number
  rejection_reason_counts: Record<string, number>
  selected_reason_counts: Record<string, number>
  postprocess: PhrasePostprocessDiagnostics
  mean_selected_confidence: number | null
  mean_rejected_confidence: number | null
}


export interface StageFailureReason {
  stage: string
  error_code: string
  error_message: string
  retryable: boolean
}

export interface DiagnosticsResponse {
  derived_diagnostics: DerivedDiagnosticsSummary
  quantization: QuantizationDiagnostics
  short_notes: ShortNoteDiagnostics
  continuity: ContinuityDiagnostics
  reference_alignment: ReferenceAlignmentDiagnostics
  selected_melody: SelectedMelodyDiagnostics
  stage_failure_reason: StageFailureReason | null
}
