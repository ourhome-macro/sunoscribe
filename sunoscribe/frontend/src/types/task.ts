export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'retrying'

export interface TaskStatusResponse {
  task_id: string
  project_id: string
  task_type: string
  status: TaskStatus | string
  progress: number
  retry_count: number
  max_retries: number
  can_retry: boolean
  error_message: string | null
  result_payload: Record<string, unknown>
  queued_at: string | null
  started_at: string | null
  finished_at: string | null
}

