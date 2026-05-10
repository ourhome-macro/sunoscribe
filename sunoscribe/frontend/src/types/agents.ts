import type { ScoreRevisionSummary } from './revision'

export interface DiagnosisIssue {
  code: string
  severity: 'low' | 'medium' | 'high'
  summary: string
  note_ids: string[]
  evidence: Record<string, unknown>
}

export interface DiagnosisAction {
  action: string
  rationale: string
}

export interface UncertainNoteDiagnosis {
  note_id: string
  pitch: string
  measure: number | null
  beat: number | null
  onset_tick: number | null
  duration_tick: number | null
  confidence: number | null
  reason_codes: string[]
  suggested_patch_types: string[]
}

export interface AgentDiagnoseResponse {
  summary: string
  section_findings: Array<Record<string, unknown>>
  suspected_issues: DiagnosisIssue[]
  uncertain_notes: UncertainNoteDiagnosis[]
  recommended_actions: DiagnosisAction[]
}

export type AgentPatchOperation =
  | { op: 'shift_octave'; note_id: string; octaves: -3 | -2 | -1 | 1 | 2 | 3; reason?: string | null }
  | { op: 'mark_uncertain'; note_id: string; reason?: string | null }
  | { op: 'delete_note'; note_id: string; reason?: string | null }
  | { op: 'adjust_duration'; note_id: string; duration_beats?: number; duration_sec?: number; reason?: string | null }

export interface ApplyAgentScorePatchRequest {
  base_revision_id: string
  operations: AgentPatchOperation[]
  rationale: string | null
  confidence: number
}

export type ApplyAgentScorePatchResponse = ScoreRevisionSummary
