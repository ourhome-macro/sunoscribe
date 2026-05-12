import type { ApplyAgentScorePatchRequest, ApplyAgentScorePatchResponse } from '@/types/agents'

import { mockArtifacts, mockDashboard, mockDiagnosis, mockDiagnostics, mockProjectDetail, mockProjects, mockRevision } from './mock-data'

const latency = 180

function wait<T>(value: T): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(value), latency))
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export const apiClient = {
  getDashboard() {
    return wait(clone(mockDashboard))
  },

  listProjects() {
    return wait(clone(mockProjects))
  },

  getProject(projectId: string) {
    const summary = mockProjects.find((project) => project.project_id === projectId) ?? mockProjects[0]
    return wait(clone({ ...mockProjectDetail, ...summary }))
  },

  createProject(input: { name: string; file: File | null; media_kind: 'audio' | 'video' }) {
    return wait({
      project_id: 'mock-created-project',
      task_id: 'mock-analysis-task',
      name: input.name,
      media_kind: input.media_kind,
    })
  },

  listProjectRevisions(projectId: string) {
    void projectId
    return wait(clone([mockRevision]))
  },

  getRevision(revisionId: string) {
    void revisionId
    return wait(clone(mockRevision))
  },

  listArtifacts(projectId: string) {
    void projectId
    return wait(clone(mockArtifacts))
  },

  diagnoseRevision(revisionId: string) {
    void revisionId
    return wait(clone(mockDiagnosis))
  },

  getDiagnostics(projectId: string) {
    void projectId
    return wait(clone(mockDiagnostics))
  },

  applyScorePatch(revisionId: string, request: ApplyAgentScorePatchRequest): Promise<ApplyAgentScorePatchResponse> {
    void revisionId
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
    return wait(nextRevision)
  },
}
