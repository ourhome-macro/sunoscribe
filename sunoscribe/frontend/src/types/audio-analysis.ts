export interface AudioAnalysisPitch {
  available: boolean
  note_count: number
  voiced_frame_count: number
  pitch_class_histogram: Record<string, number>
  most_common_pitch_classes: string[]
  melodic_direction: 'ascending_bias' | 'descending_bias' | 'balanced' | null
  ascending_interval_count: number
  descending_interval_count: number
  repeated_interval_count: number
  average_note_confidence: number | null
  evidence: string
}

export interface AudioAnalysisExpression {
  available: boolean
  vibrato_segment_count: number
  slide_segment_count: number
  long_note_stability: number | null
  vibrato_segments: Array<Record<string, unknown>>
  slide_segments: Array<Record<string, unknown>>
  suspicious_pitch_note_ids: string[]
  evidence: string
}

export interface AudioAnalysisRange {
  available: boolean
  lowest_pitch: string | null
  highest_pitch: string | null
  lowest_pitch_midi: number | null
  highest_pitch_midi: number | null
  span_semitones: number | null
  tessitura_low_midi: number | null
  tessitura_high_midi: number | null
  tessitura_low: string | null
  tessitura_high: string | null
  highest_note_locations: Array<Record<string, unknown>>
  section_ranges: Array<Record<string, unknown>>
  evidence: string
}

export interface AudioAnalysisRhythm {
  available: boolean
  bpm: number | null
  bpm_confidence: number | null
  rhythm_type: string | null
  stability_score: number | null
  beat_count: number
  average_grid_offset_sec: number | null
  median_grid_offset_sec: number | null
  syncopation_note_count: number
  weak_beat_start_count: number
  average_duration_beats: number | null
  evidence: string
}

export interface AudioAnalysisLyrics {
  available: boolean
  status: 'ok' | 'missing_lyrics'
  line_count: number
  keyword_candidates: string[]
  sentiment_label: 'positive' | 'negative' | 'mixed' | 'neutral' | null
  sentiment_score: number | null
  positive_keyword_hits: string[]
  negative_keyword_hits: string[]
  emotion_curve: Array<Record<string, unknown>>
  evidence: string
}

export interface AudioAnalysisSummary {
  headline: string
  highlights: string[]
  confidence: number
  evidence_count: number
}

export interface AudioAnalysisReport {
  version: string
  project_id: string
  revision_id: string
  status: 'ok' | 'partial' | 'failed'
  pitch: AudioAnalysisPitch
  expression: AudioAnalysisExpression
  range: AudioAnalysisRange
  rhythm: AudioAnalysisRhythm
  lyrics: AudioAnalysisLyrics
  summary: AudioAnalysisSummary
  warnings: string[]
}

export interface AudioAnalysisReportResponse {
  artifact_id: string | null
  artifact_status: string | null
  artifact_created_at: string | null
  report: AudioAnalysisReport
}
