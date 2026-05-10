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
  stage_failure_reason: StageFailureReason | null
}
