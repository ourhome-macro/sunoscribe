import type { AgentDiagnoseResponse, ApplyAgentScorePatchRequest, ApplyAgentScorePatchResponse } from '@/types/agents'
import type { PublicArtifactResponse } from '@/types/artifact'
import type { AudioAnalysisReportResponse } from '@/types/audio-analysis'
import type { DiagnosticsResponse } from '@/types/diagnostics'
import type { ProjectDetail, ProjectStatus, ProjectSummary, StageProgressItem } from '@/types/project'
import type { ScoreRevisionSummary } from '@/types/revision'

import { mockArtifacts, mockAudioAnalysisReport, mockDashboard, mockDiagnosis, mockDiagnostics, mockProjectDetail, mockProjects, mockRevision } from './mock-data'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''
const apiMode = (import.meta.env.VITE_API_MODE ?? 'backend').toLowerCase()
const useMockFallback = apiMode !== 'backend'
const accessTokenStorageKey = 'sunoscribe-access-token'

type BackendEnvelope<T> =
  | { success: true; data: T; message?: string; pagination?: BackendPagination }
  | { success: false; error?: { code?: string; message?: string; details?: Record<string, unknown> } }

type BackendPagination = {
  page: number
  page_size: number
  total: number
  total_pages: number
}

type BackendProject = {
  id: string
  user_id?: string
  name: string
  source_type?: string | null
  source_url?: string | null
  audio_path?: string | null
  status: string
  progress: number
  created_at: string
  updated_at?: string
}

type BackendTask = {
  task_id: string
  project_id: string
  task_type: string
  status: string
  progress: number
  retry_count: number
  max_retries: number
  can_retry: boolean
  error_message: string | null
  result_payload?: Record<string, unknown>
  queued_at: string | null
  started_at: string | null
  finished_at: string | null
}

type BackendScore = {
  id: string
  project_id: string
  score_type: string
  key: string
  score_data: Record<string, unknown>
  current_revision_id: string | null
  current_revision: BackendRevision | null
  revisions: BackendRevision[]
  created_at: string | null
  updated_at: string | null
}

type BackendRevision = Omit<ScoreRevisionSummary, 'artifact_ids' | 'diff_summary'> & {
  artifact_ids?: Record<string, string>
  diff_summary?: Record<string, unknown>
  created_by_user_id?: string | null
}

type BackendUpload = {
  file_path: string
  project_id: string
  filename: string
  size: number
  artifact_id: string | null
}

type CreateProjectInput = { name: string; file: File | null; media_kind: 'audio' | 'video' }

type CreateProjectResult = {
  project_id: string
  task_id: string | null
  name: string
  media_kind: 'audio' | 'video'
  upload?: BackendUpload
}

type DashboardResponse = typeof mockDashboard

class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly details?: Record<string, unknown>

  constructor(message: string, options: { status: number; code?: string; details?: Record<string, unknown> }) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.details = options.details
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function isApiConfigured() {
  return !useMockFallback
}

function authHeaders(): HeadersInit {
  const token = window.localStorage.getItem(accessTokenStorageKey) ?? import.meta.env.VITE_API_ACCESS_TOKEN
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const hasBody = init.body !== undefined && init.body !== null
  const isForm = typeof FormData !== 'undefined' && init.body instanceof FormData

  if (hasBody && !isForm && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  for (const [key, value] of Object.entries(authHeaders())) {
    headers.set(key, value)
  }

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers,
  })
  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('application/json') ? ((await response.json()) as BackendEnvelope<T>) : null

  if (!response.ok || payload?.success === false) {
    const error = payload && 'error' in payload ? payload.error : undefined
    throw new ApiError(error?.message ?? `API request failed: ${response.status}`, {
      status: response.status,
      code: error?.code,
      details: error?.details,
    })
  }

  if (payload && 'data' in payload) {
    return payload.data
  }
  return undefined as T
}

async function requestPage<T>(path: string): Promise<{ data: T[]; pagination?: BackendPagination }> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: authHeaders(),
  })
  const payload = (await response.json()) as BackendEnvelope<T[]> & { pagination?: BackendPagination }
  if (!response.ok || payload.success === false) {
    const error = 'error' in payload ? payload.error : undefined
    throw new ApiError(error?.message ?? `API request failed: ${response.status}`, {
      status: response.status,
      code: error?.code,
      details: error?.details,
    })
  }
  return { data: payload.data, pagination: payload.pagination }
}

function mapProjectStatus(status: string): ProjectStatus {
  if (status === 'completed') return 'ready'
  if (status === 'pending') return 'queued'
  if (status === 'failed') return 'failed'
  if (status === 'processing') return 'processing'
  return 'draft'
}

function mapProjectSummary(project: BackendProject, revisions: ScoreRevisionSummary[] = []): ProjectSummary {
  const latestRevision = revisions[0] ?? null
  return {
    project_id: project.id,
    name: project.name,
    status: mapProjectStatus(project.status),
    created_at: project.created_at,
    latest_revision: latestRevision?.id ?? null,
    export_status: latestRevision?.client_summary?.export_status ?? 'unknown',
  }
}

function buildStageProgress(project: BackendProject, task?: BackendTask | null, revisions: ScoreRevisionSummary[] = []): StageProgressItem[] {
  const status = mapProjectStatus(project.status)
  const hasSource = Boolean(project.audio_path)
  const hasRevision = revisions.length > 0
  const taskFailed = task?.status === 'failed'
  const taskRunning = task?.status === 'running' || task?.status === 'queued' || task?.status === 'retrying' || status === 'processing'

  return [
    {
      stage: 'Media Ingest',
      status: hasSource ? 'success' : taskRunning ? 'running' : status === 'failed' ? 'failed' : 'pending',
      summary: hasSource ? 'Source media has been registered by the backend.' : undefined,
    },
    {
      stage: 'StemService',
      status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending',
      summary: taskFailed ? task?.error_message ?? undefined : undefined,
    },
    { stage: 'F0Track', status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending' },
    { stage: 'PitchContourIR', status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending' },
    { stage: 'MelodySelector', status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending' },
    { stage: 'DP Quantizer', status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending' },
    { stage: 'ScoreIR', status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending' },
    { stage: 'Exports', status: hasRevision ? 'success' : taskFailed ? 'failed' : taskRunning ? 'running' : 'pending' },
  ]
}

function mapRevision(revision: BackendRevision): ScoreRevisionSummary {
  return {
    id: String(revision.id),
    project_id: String(revision.project_id),
    score_id: String(revision.score_id),
    parent_revision_id: revision.parent_revision_id ? String(revision.parent_revision_id) : null,
    revision_number: Number(revision.revision_number),
    revision_type: revision.revision_type === 'user' ? 'user' : revision.revision_type === 'agent' ? 'agent' : 'machine',
    score_type: String(revision.score_type),
    key: String(revision.key),
    artifact_ids: revision.artifact_ids ?? {},
    client_summary: revision.client_summary,
    diff_summary: revision.diff_summary ?? {},
    created_at: revision.created_at,
    updated_at: revision.updated_at,
  }
}

function mapScoreRevisions(score: BackendScore): ScoreRevisionSummary[] {
  return [...(score.revisions ?? [])]
    .map(mapRevision)
    .sort((left, right) => right.revision_number - left.revision_number)
}

function artifactsFromRevisions(revisions: ScoreRevisionSummary[]): PublicArtifactResponse[] {
  return revisions.flatMap((revision) =>
    Object.entries(revision.artifact_ids ?? {}).map(([artifact_type, id]) => ({
      id,
      artifact_type,
      status: revision.client_summary?.export_status ?? 'available',
      filename: null,
      mime_type: null,
      file_size_bytes: null,
      checksum: null,
      created_at: revision.updated_at ?? revision.created_at,
      metadata: {
        export_scope: revision.client_summary?.export_status ?? null,
      },
    })),
  )
}

function buildDiagnostics(projectId: string, task: BackendTask | null, revisions: ScoreRevisionSummary[]): DiagnosticsResponse {
  const revision = revisions[0]
  const scoreSummary = revision?.client_summary
  const failed = task?.status === 'failed'
  return {
    derived_diagnostics: {
      summary: failed ? task?.error_message ?? 'Backend task failed.' : revision ? 'Score revision diagnostics are available.' : 'No score revision is available yet.',
      f0_track_available: Boolean(revision?.artifact_ids.f0_track),
      note_candidates_available: Boolean(revision?.artifact_ids.note_candidates),
      rhythm_grid_available: Boolean(revision?.artifact_ids.rhythm_grid),
      score_revision_id: revision?.id ?? '',
    },
    quantization: {
      fallback_used: false,
      fallback_reason: null,
      mean_error_beats: null,
      p95_error_beats: null,
      max_error_beats: null,
      fragmentation: 0,
      overmerge: 0,
    },
    short_notes: {
      too_short_count: 0,
      low_voiced_ratio_count: scoreSummary?.low_confidence_note_count ?? 0,
      suspected_vibrato_count: 0,
      suspected_glide_count: 0,
    },
    continuity: {
      note_count: scoreSummary?.note_count ?? 0,
      gap50_ratio: null,
      big_gap_count: 0,
      short_note_ratio: null,
      large_jump_ratio: null,
      local_adjacent_pair_count: 0,
      local_large_jump_count: 0,
      local_large_jump_ratio: null,
      cross_phrase_adjacent_pair_count: 0,
      cross_phrase_large_jump_count: 0,
      cross_phrase_large_jump_ratio: null,
      median_pitch: null,
      pitch_range: [null, null],
    },
    reference_alignment: {
      available: false,
      diagnostic_only: true,
      reference_suspect: false,
      reason_codes: [],
      expected_first_note_time_sec: null,
      predicted_first_note_time_sec: null,
      first_note_delay_sec: null,
      possible_global_time_offset_sec: null,
      best_time_shift_note_recall: null,
      smart_onset_shift_sec: null,
      smart_onset_shift_recall: null,
      best_octave_shift_semitones: null,
      best_octave_shift_note_recall: null,
      median_pitch_delta_raw: null,
      octave_normalized_recall_lift: null,
      dtw_recall_lift: null,
      raw_match_rate_vs_expected: null,
      expected_predicted_time_overlap_ratio: null,
    },
    selected_melody: {
      available: Boolean(scoreSummary),
      input_candidate_count: scoreSummary?.note_count ?? 0,
      pre_postprocess_selected_count: null,
      selected_count: scoreSummary?.note_count ?? 0,
      rejected_count: 0,
      rejection_reason_counts: {},
      selected_reason_counts: {},
      postprocess: {
        available: false,
        enabled: false,
        input_note_count: null,
        output_note_count: null,
        iteration_count: null,
        action_count: 0,
        action_counts: {},
        reason_code_counts: {},
        actions: [],
      },
      mean_selected_confidence: null,
      mean_rejected_confidence: null,
    },
    stage_failure_reason: failed
      ? {
          stage: task?.task_type ?? 'score_generation',
          error_code: 'BACKEND_TASK_FAILED',
          error_message: task?.error_message ?? 'Backend task failed.',
          retryable: Boolean(task?.can_retry),
        }
      : null,
  }
}

async function getProjectScore(projectId: string): Promise<BackendScore | null> {
  try {
    return await request<BackendScore>(`/api/projects/${projectId}/score`)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

async function getLatestProjectTask(projectId: string): Promise<BackendTask | null> {
  void projectId
  return null
}

async function createBackendProject(input: CreateProjectInput): Promise<CreateProjectResult> {
  const project = await request<BackendProject>('/api/projects', {
    method: 'POST',
    body: JSON.stringify({ name: input.name, source_type: 'upload' }),
  })

  let upload: BackendUpload | undefined
  if (input.file) {
    const form = new FormData()
    form.append('project_id', project.id)
    form.append('file', input.file)
    upload = await request<BackendUpload>(`/api/upload/${input.media_kind}`, {
      method: 'POST',
      body: form,
    })
  }

  let taskId: string | null = null
  if (input.file) {
    const task = await request<BackendTask>(`/api/projects/${project.id}/score`, {
      method: 'POST',
      body: JSON.stringify({ score_type: 'staff', key: 'C Major' }),
    })
    taskId = task.task_id
  }

  return {
    project_id: project.id,
    task_id: taskId,
    name: project.name,
    media_kind: input.media_kind,
    upload,
  }
}

function mockClient() {
  return {
    getDashboard: async () => clone(mockDashboard),
    listProjects: async () => clone(mockProjects),
    getProject: async (projectId: string) => {
      const summary = mockProjects.find((project) => project.project_id === projectId) ?? mockProjects[0]
      return clone({ ...mockProjectDetail, ...summary })
    },
    createProject: async (input: CreateProjectInput): Promise<CreateProjectResult> => ({
      project_id: 'mock-created-project',
      task_id: 'mock-analysis-task',
      name: input.name,
      media_kind: input.media_kind,
    }),
    listProjectRevisions: async () => clone([mockRevision]),
    getRevision: async () => clone(mockRevision),
    listArtifacts: async () => clone(mockArtifacts),
    diagnoseRevision: async () => clone(mockDiagnosis),
    getAudioAnalysisReport: async () => clone(mockAudioAnalysisReport),
    generateAudioAnalysisReport: async () => clone(mockAudioAnalysisReport),
    getDiagnostics: async () => clone(mockDiagnostics),
    applyScorePatch: async (_revisionId: string, request: ApplyAgentScorePatchRequest): Promise<ApplyAgentScorePatchResponse> => {
      const operationNames = request.operations.map((operation) => operation.op)
      const changedIds = request.operations
        .map((operation) => ('note_id' in operation ? operation.note_id : null))
        .filter((noteId): noteId is string => Boolean(noteId))
      const nextRevision = clone(mockRevision)
      nextRevision.id = 'b5bb97f7-dc61-4d83-958a-08996d80f9f0'
      nextRevision.parent_revision_id = request.base_revision_id
      nextRevision.revision_number = mockRevision.revision_number + 1
      nextRevision.revision_type = 'agent'
      nextRevision.created_at = new Date().toISOString()
      nextRevision.updated_at = nextRevision.created_at
      nextRevision.diff_summary = {
        operation_count: request.operations.length,
        operations: operationNames,
        changed_note_ids: operationNames.includes('delete_note') ? [] : changedIds,
        added_note_ids: [],
        deleted_note_ids: operationNames.includes('delete_note') ? changedIds : [],
        note_count_before: mockRevision.client_summary?.note_count ?? 0,
        note_count_after: (mockRevision.client_summary?.note_count ?? 0) - (operationNames.includes('delete_note') ? 1 : 0),
      }
      if (nextRevision.client_summary) {
        nextRevision.client_summary.revision_id = nextRevision.id
        nextRevision.client_summary.parent_revision_id = request.base_revision_id
      }
      return nextRevision
    },
  }
}

const backendClient = {
  async getDashboard(): Promise<DashboardResponse> {
    const projects = await this.listProjects()
    const revisions = (await Promise.all(projects.slice(0, 5).map((project) => this.listProjectRevisions(project.project_id).catch(() => [])))).flat()
    return {
      stats: {
        project_count: projects.length,
        ready_count: projects.filter((project) => project.status === 'ready').length,
        failed_task_count: projects.filter((project) => project.status === 'failed').length,
        revision_count: revisions.length,
      },
      recent_projects: projects.slice(0, 5),
      recent_revisions: revisions.slice(0, 5),
      recent_failed_tasks: [],
    }
  },

  async listProjects(): Promise<ProjectSummary[]> {
    const page = await requestPage<BackendProject>('/api/projects?page=1&page_size=100')
    return Promise.all(
      page.data.map(async (project) => {
        const score = await getProjectScore(project.id)
        const revisions = score ? mapScoreRevisions(score) : []
        return mapProjectSummary(project, revisions)
      }),
    )
  },

  async getProject(projectId: string): Promise<ProjectDetail> {
    const project = await request<BackendProject>(`/api/projects/${projectId}`)
    const score = await getProjectScore(projectId)
    const revisions = score ? mapScoreRevisions(score) : []
    const task = await getLatestProjectTask(projectId)
    return {
      ...mapProjectSummary(project, revisions),
      description: project.source_url ?? undefined,
      current_task_id: task?.task_id,
      analysis_status: project.status === 'failed' ? 'failed' : revisions.length > 0 ? 'complete' : project.status === 'processing' || task ? 'running' : 'not_started',
      stage_progress: buildStageProgress(project, task, revisions),
    }
  },

  createProject: createBackendProject,

  async listProjectRevisions(projectId: string): Promise<ScoreRevisionSummary[]> {
    const score = await getProjectScore(projectId)
    return score ? mapScoreRevisions(score) : []
  },

  async getRevision(revisionId: string): Promise<ScoreRevisionSummary> {
    const projects = await requestPage<BackendProject>('/api/projects?page=1&page_size=100')
    for (const project of projects.data) {
      const score = await getProjectScore(project.id)
      const revision = score ? mapScoreRevisions(score).find((candidate) => candidate.id === revisionId) : null
      if (revision) return revision
    }
    throw new ApiError('Score revision not found', { status: 404, code: 'NOT_FOUND' })
  },

  async listArtifacts(projectId: string): Promise<PublicArtifactResponse[]> {
    const score = await getProjectScore(projectId)
    return score ? artifactsFromRevisions(mapScoreRevisions(score)) : []
  },

  async diagnoseRevision(revisionId: string): Promise<AgentDiagnoseResponse> {
    return request<AgentDiagnoseResponse>(`/api/score-revisions/${revisionId}/agent/diagnose`, { method: 'POST' })
  },

  async getAudioAnalysisReport(revisionId: string): Promise<AudioAnalysisReportResponse | null> {
    try {
      return await request<AudioAnalysisReportResponse>(`/api/score-revisions/${revisionId}/audio-analysis`)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },

  async generateAudioAnalysisReport(revisionId: string): Promise<AudioAnalysisReportResponse> {
    return request<AudioAnalysisReportResponse>(`/api/score-revisions/${revisionId}/audio-analysis`, { method: 'POST' })
  },

  async getDiagnostics(projectId: string): Promise<DiagnosticsResponse> {
    const score = await getProjectScore(projectId)
    const revisions = score ? mapScoreRevisions(score) : []
    return buildDiagnostics(projectId, null, revisions)
  },

  async applyScorePatch(revisionId: string, requestBody: ApplyAgentScorePatchRequest): Promise<ApplyAgentScorePatchResponse> {
    const response = await request<BackendRevision>(`/api/score-revisions/${revisionId}/agent/patch/apply`, {
      method: 'POST',
      body: JSON.stringify(requestBody),
    })
    return mapRevision(response)
  },
}

export const apiClient = isApiConfigured() ? backendClient : mockClient()
export { ApiError, accessTokenStorageKey }
