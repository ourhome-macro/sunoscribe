import type { AgentDiagnoseResponse } from '@/types/agents'
import type { PublicArtifactResponse } from '@/types/artifact'
import type { DiagnosticsResponse } from '@/types/diagnostics'
import type { ProjectDetail, ProjectSummary, StageProgressItem } from '@/types/project'
import type { ScoreRevisionSummary } from '@/types/revision'

const now = new Date('2026-05-10T09:20:00+08:00')

const stageProgress: StageProgressItem[] = [
  { stage: 'Media Ingest', status: 'success', summary: 'canonical audio ready' },
  { stage: 'StemService', status: 'success', summary: 'vocals/accompaniment registered' },
  { stage: 'F0Track', status: 'success', summary: 'RMVPE summary artifact available' },
  { stage: 'PitchContourIR', status: 'success', summary: 'voiced contour normalized' },
  { stage: 'MelodySelector', status: 'success', summary: 'lead vocal candidates selected' },
  { stage: 'DP Quantizer', status: 'success', summary: 'grid-aligned candidate path selected' },
  { stage: 'ScoreIR', status: 'success', summary: 'machine revision created' },
  { stage: 'Exports', status: 'success', summary: 'MIDI / MusicXML / view JSON derived from revision' },
]

export const mockProjects: ProjectSummary[] = [
  {
    project_id: '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101',
    name: 'Mojito lead vocal transcription',
    status: 'ready',
    created_at: '2026-05-08T20:24:00+08:00',
    latest_revision: '72a86fb1-7ba9-4ee3-91cb-0a3f63e63f10',
    export_status: 'available',
  },
  {
    project_id: '3b4a9ea4-4472-48af-8774-6baf2fb1a002',
    name: 'Acoustic cover smoke sample',
    status: 'processing',
    created_at: '2026-05-09T15:42:00+08:00',
    latest_revision: null,
    export_status: 'pending',
  },
  {
    project_id: '7b1f6c71-1a0e-4e70-9385-6b972f8aa333',
    name: 'Noisy live vocal test',
    status: 'failed',
    created_at: '2026-05-09T18:11:00+08:00',
    latest_revision: null,
    export_status: 'failed',
  },
]

export const mockRevision: ScoreRevisionSummary = {
  id: '72a86fb1-7ba9-4ee3-91cb-0a3f63e63f10',
  project_id: '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101',
  score_id: 'e80a31e3-6f27-4535-bbea-2c6bc11b76fe',
  parent_revision_id: null,
  revision_number: 1,
  revision_type: 'machine',
  score_type: 'lead_vocal',
  key: 'C major',
  artifact_ids: {
    midi: 'ef9b383f-e07a-4d7d-9c94-6a404a8ac111',
    musicxml: '348c34cc-1375-45cd-9d8c-07dd5dcac222',
    view_json: '8cc1e553-d0db-4afb-9b34-4f5a85e5c333',
  },
  client_summary: {
    revision_id: '72a86fb1-7ba9-4ee3-91cb-0a3f63e63f10',
    parent_revision_id: null,
    note_count: 128,
    uncertain_note_count: 4,
    low_confidence_note_count: 3,
    low_confidence_regions: [
      { start_note_id: 'n-018', end_note_id: 'n-023', measure_start: 5, measure_end: 6, note_count: 3 },
    ],
    export_status: 'available',
    score_notes: [
      {
        note_id: 'n-018',
        pitch: 'A4',
        onset_tick: 3840,
        duration_tick: 360,
        measure: 5,
        beat: 2.5,
        confidence: 0.42,
        uncertain: true,
        reason_codes: ['low_confidence', 'octave_outlier', 'uncertain'],
        source_candidate_id: 'cand-018-a',
        quantized_note_id: 'q-018',
      },
      {
        note_id: 'n-021',
        pitch: 'E5',
        onset_tick: 4560,
        duration_tick: 180,
        measure: 6,
        beat: 1.25,
        confidence: 0.51,
        uncertain: true,
        reason_codes: ['too_short', 'possible_fragmentation', 'uncertain'],
        source_candidate_id: 'cand-021-b',
        quantized_note_id: 'q-021',
      },
      {
        note_id: 'n-044',
        pitch: 'G4',
        onset_tick: 9600,
        duration_tick: 720,
        measure: 12,
        beat: 3,
        confidence: 0.58,
        uncertain: true,
        reason_codes: ['large_quantize_error', 'uncertain'],
        source_candidate_id: 'cand-044-c',
        quantized_note_id: 'q-044',
      },
      {
        note_id: 'n-077',
        pitch: 'D5',
        onset_tick: 16800,
        duration_tick: 1440,
        measure: 21,
        beat: 1,
        confidence: 0.47,
        uncertain: true,
        reason_codes: ['possible_overmerge', 'too_unstable', 'uncertain'],
        source_candidate_id: 'cand-077-d',
        quantized_note_id: 'q-077',
      },
    ],
  },
  diff_summary: {},
  created_at: '2026-05-08T20:29:00+08:00',
  updated_at: '2026-05-08T20:31:00+08:00',
}

export const mockArtifacts: PublicArtifactResponse[] = [
  {
    id: '1d1d47b1-e58a-4c73-8b46-c68dbf4a8001',
    artifact_type: 'source_media',
    status: 'available',
    filename: 'mojito.mp4',
    mime_type: 'video/mp4',
    file_size_bytes: 38420000,
    checksum: 'sha256:mock-source',
    created_at: '2026-05-08T20:24:00+08:00',
  },
  {
    id: '7e2df29a-0ce2-46ce-8dfb-c68dbf4a8002',
    artifact_type: 'canonical_audio',
    status: 'available',
    filename: 'source.wav',
    mime_type: 'audio/wav',
    file_size_bytes: 52511774,
    checksum: 'sha256:mock-canonical',
    created_at: '2026-05-08T20:25:00+08:00',
  },
  {
    id: '891adf19-5f4f-4c68-b13d-c68dbf4a8003',
    artifact_type: 'vocals_stem',
    status: 'available',
    filename: 'vocals.wav',
    mime_type: 'audio/wav',
    file_size_bytes: 26255887,
    checksum: 'sha256:mock-vocals',
    created_at: '2026-05-08T20:26:00+08:00',
  },
  {
    id: '348c34cc-1375-45cd-9d8c-07dd5dcac222',
    artifact_type: 'musicxml',
    status: 'available',
    filename: 'revision-1.musicxml',
    mime_type: 'application/vnd.recordare.musicxml+xml',
    file_size_bytes: 51800,
    checksum: 'sha256:mock-musicxml',
    created_at: '2026-05-08T20:31:00+08:00',
  },
  {
    id: 'ef9b383f-e07a-4d7d-9c94-6a404a8ac111',
    artifact_type: 'midi',
    status: 'available',
    filename: 'revision-1.mid',
    mime_type: 'audio/midi',
    file_size_bytes: 8200,
    checksum: 'sha256:mock-midi',
    created_at: '2026-05-08T20:31:00+08:00',
  },
]

export const mockProjectDetail: ProjectDetail = {
  ...mockProjects[0],
  description: 'Lead-vocal transcription workspace. Exports are derived from the selected ScoreRevision.',
  current_task_id: 'task-20260508-mojito',
  analysis_status: 'complete',
  stage_progress: stageProgress,
}

export const mockDiagnosis: AgentDiagnoseResponse = {
  summary: '4 notes are marked uncertain or low-confidence in ScoreIR.',
  section_findings: [],
  suspected_issues: [
    {
      code: 'low_confidence_cluster',
      severity: 'medium',
      summary: 'Measures 5-6 contain clustered low-confidence notes.',
      note_ids: ['n-018', 'n-021'],
      evidence: { region_count: 1 },
    },
  ],
  uncertain_notes: mockRevision.client_summary?.score_notes.map((note) => ({
    note_id: note.note_id,
    pitch: note.pitch,
    measure: note.measure,
    beat: note.beat,
    onset_tick: note.onset_tick,
    duration_tick: note.duration_tick,
    confidence: note.confidence,
    reason_codes: note.reason_codes,
    suggested_patch_types: suggestedPatchTypes(note.reason_codes),
  })) ?? [],
  recommended_actions: [
    {
      action: 'Inspect uncertain notes before regenerating exports',
      rationale: 'Patch operations create a new ScoreRevision and keep machine revision traceable.',
    },
  ],
}

export const mockDiagnostics: DiagnosticsResponse = {
  derived_diagnostics: {
    summary: 'Artifacts are available for ScoreIR-level diagnosis. Full F0Track is intentionally not requested by the UI.',
    f0_track_available: true,
    note_candidates_available: true,
    rhythm_grid_available: true,
    score_revision_id: mockRevision.id,
  },
  quantization: {
    fallback_used: false,
    fallback_reason: null,
    mean_error_beats: 0.08,
    p95_error_beats: 0.21,
    max_error_beats: 0.34,
    fragmentation: 3,
    overmerge: 1,
  },
  short_notes: {
    too_short_count: 6,
    low_voiced_ratio_count: 2,
    suspected_vibrato_count: 4,
    suspected_glide_count: 3,
  },
  stage_failure_reason: null,
}

export const mockDashboard = {
  stats: {
    project_count: mockProjects.length,
    ready_count: mockProjects.filter((project) => project.status === 'ready').length,
    failed_task_count: mockProjects.filter((project) => project.status === 'failed').length,
    revision_count: 3,
  },
  recent_projects: mockProjects,
  recent_failed_tasks: [
    {
      task_id: 'task-20260509-live-noisy',
      project_id: '7b1f6c71-1a0e-4e70-9385-6b972f8aa333',
      stage: 'StemService',
      reason: 'vocal separation dependency failed explicitly',
      created_at: now.toISOString(),
    },
  ],
  recent_revisions: [mockRevision],
}

function suggestedPatchTypes(reasonCodes: string[]) {
  const patchTypes = new Set<string>()
  if (reasonCodes.includes('octave_outlier')) patchTypes.add('shift_octave')
  if (reasonCodes.includes('large_quantize_error')) patchTypes.add('adjust_duration')
  if (reasonCodes.includes('possible_fragmentation')) patchTypes.add('adjust_duration')
  if (reasonCodes.includes('possible_overmerge')) patchTypes.add('delete_note')
  patchTypes.add('mark_uncertain')
  return Array.from(patchTypes)
}
