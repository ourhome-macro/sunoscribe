export type ProjectStatus = 'queued' | 'processing' | 'ready' | 'failed' | 'draft'
export type ExportStatus = 'unknown' | 'available' | 'partial' | 'failed' | 'pending'

export interface ProjectSummary {
  project_id: string
  name: string
  status: ProjectStatus
  created_at: string
  latest_revision: string | null
  export_status: ExportStatus
  current_task_id?: string
}

export interface StageProgressItem {
  stage: 'Media Ingest' | 'StemService' | 'F0Track' | 'PitchContourIR' | 'MelodySelector' | 'DP Quantizer' | 'ScoreIR' | 'Exports'
  status: 'pending' | 'running' | 'success' | 'failed'
  summary?: string
}

export interface ProjectDetail extends ProjectSummary {
  description?: string
  current_task_id?: string
  current_task_status?: string
  task_progress?: number
  task_error_message?: string | null
  task_can_retry?: boolean
  task_retry_count?: number
  task_max_retries?: number
  analysis_status: 'not_started' | 'running' | 'complete' | 'failed'
  stage_progress: StageProgressItem[]
}
