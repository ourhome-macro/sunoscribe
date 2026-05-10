import type { ExportStatus } from './project'

export interface ScoreNoteClientSummary {
  note_id: string
  pitch: string
  onset_tick: number | null
  duration_tick: number | null
  measure: number | null
  beat: number | null
  confidence: number | null
  uncertain: boolean
  reason_codes: string[]
  source_candidate_id: string | null
  quantized_note_id: string | null
}

export interface ScoreRevisionClientSummary {
  revision_id: string
  parent_revision_id: string | null
  note_count: number
  uncertain_note_count: number
  low_confidence_note_count: number
  low_confidence_regions: Array<Record<string, unknown>>
  export_status: ExportStatus
  score_notes: ScoreNoteClientSummary[]
}

export interface RevisionDiffSummary {
  operation_count?: number
  operations?: string[]
  changed_note_ids?: string[]
  added_note_ids?: string[]
  deleted_note_ids?: string[]
  note_count_before?: number
  note_count_after?: number
}

export interface ScoreRevisionSummary {
  id: string
  project_id: string
  score_id: string
  parent_revision_id: string | null
  revision_number: number
  revision_type: 'machine' | 'user' | 'agent'
  score_type: 'lead_vocal' | string
  key: string
  artifact_ids: Record<string, string>
  client_summary: ScoreRevisionClientSummary | null
  diff_summary: RevisionDiffSummary
  created_at: string | null
  updated_at: string | null
}
