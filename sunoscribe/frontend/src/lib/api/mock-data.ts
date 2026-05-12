import type { AgentDiagnoseResponse } from '@/types/agents'
import type { PublicArtifactResponse } from '@/types/artifact'
import type { DiagnosticsResponse } from '@/types/diagnostics'
import type { ProjectDetail, ProjectSummary, StageProgressItem } from '@/types/project'
import type { ScoreRevisionSummary } from '@/types/revision'

const now = new Date('2026-05-10T09:20:00+08:00')

const stageProgress: StageProgressItem[] = [
  { stage: 'Media Ingest', status: 'success', summary: '已把上传文件整理成统一音频。' },
  { stage: 'StemService', status: 'success', summary: '已分离出主唱和伴奏摘要。' },
  { stage: 'F0Track', status: 'success', summary: '已识别人声的音高轨迹摘要。' },
  { stage: 'PitchContourIR', status: 'success', summary: '已整理连续的人声旋律线索。' },
  { stage: 'MelodySelector', status: 'success', summary: '已选出最像主唱的旋律候选。' },
  { stage: 'DP Quantizer', status: 'success', summary: '已把旋律对齐到拍子和小节。' },
  { stage: 'ScoreIR', status: 'success', summary: '已生成机器乐谱版本。' },
  { stage: 'Exports', status: 'success', summary: '已从当前乐谱版本导出文件。' },
]

export const mockProjects: ProjectSummary[] = [
  {
    project_id: '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101',
    name: 'Mojito 主唱旋律',
    status: 'ready',
    created_at: '2026-05-08T20:24:00+08:00',
    latest_revision: '72a86fb1-7ba9-4ee3-91cb-0a3f63e63f10',
    export_status: 'available',
  },
  {
    project_id: '3b4a9ea4-4472-48af-8774-6baf2fb1a002',
    name: '木吉他翻唱测试',
    status: 'processing',
    created_at: '2026-05-09T15:42:00+08:00',
    latest_revision: null,
    export_status: 'pending',
  },
  {
    project_id: '7b1f6c71-1a0e-4e70-9385-6b972f8aa333',
    name: '现场噪声人声测试',
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
    metadata: {
      export_scope: 'diagnostic_review',
      quality_gate_status: 'quality_failed',
      quality_failed_checks: ['note_recall'],
      diagnostic_message: 'MIDI is available for listening review, but the melody is sparse/fragmented and should not be treated as a clean transcription.',
    },
  },
]

export const mockProjectDetail: ProjectDetail = {
  ...mockProjects[0],
  description: '这首歌已经生成主唱旋律乐谱，导出文件都来自当前选中的乐谱版本。',
  current_task_id: 'task-20260508-mojito',
  analysis_status: 'complete',
  stage_progress: stageProgress,
}

export const mockDiagnosis: AgentDiagnoseResponse = {
  summary: '有 4 个音符需要确认，主要集中在第 5-6 小节和第 21 小节。',
  section_findings: [],
  suspected_issues: [
    {
      code: 'low_confidence_cluster',
      severity: 'medium',
      summary: '第 5-6 小节有连续的低可信度音符。',
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
      rationale: '修正音符会创建新的乐谱版本，并保留机器生成版本作为可追踪来源。',
    },
  ],
}

export const mockDiagnostics: DiagnosticsResponse = {
  derived_diagnostics: {
    summary: '当前乐谱版本有足够的摘要用于诊断；前端只读取摘要，不请求完整人声音高轨迹。',
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
  continuity: {
    note_count: 174,
    gap50_ratio: 0.872832,
    big_gap_count: 52,
    short_note_ratio: 0.137931,
    large_jump_ratio: 0.098266,
    local_adjacent_pair_count: 53,
    local_large_jump_count: 2,
    local_large_jump_ratio: 0.037736,
    cross_phrase_adjacent_pair_count: 120,
    cross_phrase_large_jump_count: 15,
    cross_phrase_large_jump_ratio: 0.125,
    median_pitch: 60,
    pitch_range: [53, 74],
  },
  reference_alignment: {
    available: true,
    diagnostic_only: true,
    reference_suspect: true,
    reason_codes: [
      'reference_first_note_offset_suspect',
      'reference_time_origin_needs_review',
      'possible_global_time_offset',
      'possible_global_octave_shift',
      'possible_wrong_reference_track_or_pitch_source',
      'dtw_sequence_alignment_suspect',
    ],
    expected_first_note_time_sec: 0,
    predicted_first_note_time_sec: 14.234244,
    first_note_delay_sec: 14.234244,
    possible_global_time_offset_sec: -8.372,
    best_time_shift_note_recall: 0.031532,
    smart_onset_shift_sec: -1.045,
    smart_onset_shift_recall: 0.117117,
    best_octave_shift_semitones: 12,
    best_octave_shift_note_recall: 0.031532,
    median_pitch_delta_raw: -14,
    octave_normalized_recall_lift: 0.024024,
    dtw_recall_lift: 0.1997,
    raw_match_rate_vs_expected: 0.001502,
    expected_predicted_time_overlap_ratio: 0.926221,
  },
  selected_melody: {
    available: true,
    input_candidate_count: 211,
    pre_postprocess_selected_count: 181,
    selected_count: 174,
    rejected_count: 30,
    rejection_reason_counts: {
      low_confidence: 12,
      too_short: 8,
      outside_vocal_range: 3,
      overlaps_stronger_candidate: 7,
    },
    selected_reason_counts: {
      short_gap_bridged: 19,
      short_note_absorbed: 6,
      octave_jump_corrected: 2,
      phrase_median_smoothed: 3,
    },
    postprocess: {
      available: true,
      enabled: true,
      input_note_count: 181,
      output_note_count: 174,
      iteration_count: 2,
      action_count: 30,
      action_counts: {
        short_gap_bridge: 19,
        short_note_absorb: 6,
        octave_jump_correction: 2,
        median_smoothing: 3,
      },
      reason_code_counts: {
        short_gap_bridged: 19,
        short_note_absorbed: 6,
        octave_jump_corrected: 2,
        phrase_median_smoothed: 3,
      },
      actions: [
        {
          action: 'short_gap_bridge',
          reason_code: 'short_gap_bridged',
          note_ids: ['cand_0041', 'cand_0042'],
          output_note_id: 'cand_0041+cand_0042',
          start_time_sec: 14.234244,
          end_time_sec: 14.712991,
          pitch_before_midi: 60,
          pitch_after_midi: 60,
          details: {
            mode: 'merge_no_insert',
            gap_sec: 0.041,
            pitch_delta_semitones: 0,
            pitch_tolerance_semitones: 1,
          },
        },
        {
          action: 'short_note_absorb',
          reason_code: 'short_note_absorbed',
          note_ids: ['cand_0077', 'cand_0078', 'cand_0079'],
          output_note_id: 'cand_0077+cand_0078+cand_0079',
          start_time_sec: 21.381552,
          end_time_sec: 22.024109,
          pitch_before_midi: 72,
          pitch_after_midi: 60,
          details: {
            mode: 'merge_short_center_note',
            absorbed_duration_sec: 0.116,
            confidence_before: 0.55,
            neighbor_confidence_max: 0.91,
            pitch_outlier: true,
          },
        },
        {
          action: 'octave_jump_correction',
          reason_code: 'octave_jump_corrected',
          note_ids: ['cand_0105'],
          output_note_id: 'cand_0105',
          start_time_sec: 29.441002,
          end_time_sec: 29.632884,
          pitch_before_midi: 72,
          pitch_after_midi: 60,
          details: {
            mode: 'local_isolated_jump',
            semitone_shift: -12,
            anchor_count: 4,
            score_before: 7.24,
            score_after: 2.11,
          },
        },
      ],
    },
    mean_selected_confidence: 0.742618,
    mean_rejected_confidence: 0.411239,
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
      reason: '主唱分离依赖失败，任务已明确停止。',
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
