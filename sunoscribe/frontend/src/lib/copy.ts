import type { StageProgressItem } from '@/types/project'

export const navCopy = {
  dashboard: '首页',
  projects: '我的歌曲',
  upload: '上传歌曲',
  workspace: '乐谱工作台',
  diagnostics: '诊断报告',
  settings: '设置',
}

export const statusCopy: Record<string, { label: string; tone: 'success' | 'warning' | 'destructive' | 'secondary' }> = {
  ready: { label: '乐谱已生成', tone: 'success' },
  available: { label: '可下载', tone: 'success' },
  success: { label: '完成', tone: 'success' },
  complete: { label: '完成', tone: 'success' },
  processing: { label: '处理中', tone: 'warning' },
  running: { label: '处理中', tone: 'warning' },
  queued: { label: '排队中', tone: 'warning' },
  pending: { label: '等待中', tone: 'warning' },
  failed: { label: '失败', tone: 'destructive' },
  partial: { label: '部分完成', tone: 'warning' },
  unknown: { label: '未知', tone: 'secondary' },
  draft: { label: '草稿', tone: 'secondary' },
  not_started: { label: '未开始', tone: 'secondary' },
  retryable: { label: '可重试', tone: 'warning' },
  machine: { label: '机器生成', tone: 'secondary' },
  user: { label: '人工修改', tone: 'success' },
  agent: { label: '助手修改', tone: 'warning' },
}

export const stageCopy: Record<StageProgressItem['stage'], { title: string; technical: string; description: string }> = {
  'Media Ingest': {
    title: '上传与转码',
    technical: 'Media Ingest',
    description: '把音频或视频整理成系统统一处理的 WAV 音频。',
  },
  StemService: {
    title: '分离主唱',
    technical: 'StemService',
    description: '把歌曲尽量分成主唱和伴奏，后续只分析主唱旋律。',
  },
  F0Track: {
    title: '识别人声音高',
    technical: 'F0Track',
    description: '追踪人声每一刻大概唱的是哪个音高。',
  },
  PitchContourIR: {
    title: '整理音高曲线',
    technical: 'PitchContourIR',
    description: '把连续、会滑动和颤动的歌声整理成更稳定的旋律线索。',
  },
  MelodySelector: {
    title: '选择主旋律',
    technical: 'MelodySelector',
    description: '从候选音符里选出最像主唱旋律的那条线。',
  },
  'DP Quantizer': {
    title: '对齐节拍',
    technical: 'DP Quantizer',
    description: '把自由演唱的时间点对齐到拍子和小节上。',
  },
  ScoreIR: {
    title: '生成乐谱版本',
    technical: 'ScoreIR / ScoreRevision',
    description: '生成可检查、可修改、可导出的主唱乐谱版本。',
  },
  Exports: {
    title: '导出文件',
    technical: 'MIDI / MusicXML / score view JSON',
    description: '从当前乐谱版本导出 MIDI、MusicXML 和前端显示数据。',
  },
}

export const patchCopy: Record<string, { label: string; description: string }> = {
  shift_octave: { label: '调整八度', description: '这个音可能高/低了八度。' },
  mark_uncertain: { label: '标记待确认', description: '先保留这个音，但提醒之后再听一遍。' },
  delete_note: { label: '删除这个音', description: '这个音可能是伴奏串扰、气声或错误碎片。' },
  adjust_duration: { label: '调整时值', description: '这个音可能太短、太长或没有对齐拍子。' },
}

export const artifactTypeCopy: Record<string, string> = {
  source_media: '原始上传文件',
  canonical_audio: '统一音频',
  vocals_stem: '主唱音轨',
  accompaniment_stem: '伴奏音轨',
  f0_track: '人声音高轨迹',
  note_candidates: '候选音符',
  rhythm_grid: '节拍网格',
  musicxml: '五线谱文件',
  midi: 'MIDI 文件',
  view_json: '前端显示数据',
}

export const glossaryCopy: Record<string, { label: string; description: string }> = {
  ScoreRevision: {
    label: '乐谱版本',
    description: '系统每次生成或修改乐谱都会创建一个新版本，导出文件都来自某个明确版本。',
  },
  ScoreIR: {
    label: '乐谱中间表示',
    description: '系统真正相信的乐谱数据，不是 MIDI 或 MusicXML 文件本身。',
  },
  MusicXML: {
    label: 'MusicXML',
    description: '给五线谱软件和网页渲染器使用的乐谱交换文件，从乐谱版本导出。',
  },
  MIDI: {
    label: 'MIDI',
    description: '可播放或导入编曲软件的音符文件，从乐谱版本导出，不是事实源。',
  },
  F0Track: {
    label: '人声音高轨迹',
    description: '系统追踪主唱音高的结果，前端只看摘要，不拉取完整轨迹。',
  },
  Artifact: {
    label: '生成文件',
    description: '流水线每一步留下的可追踪文件或摘要，例如主唱音轨、乐谱文件和诊断图。',
  },
}

export function formatStatus(status: string | null | undefined) {
  return statusCopy[status ?? 'unknown'] ?? { label: status ?? '未知', tone: 'secondary' as const }
}

export function formatStage(stage: StageProgressItem['stage']) {
  return stageCopy[stage]
}

export function formatPatchType(patchType: string) {
  return patchCopy[patchType] ?? { label: patchType, description: '建议由后端校验后再应用。' }
}

export function formatArtifactType(artifactType: string) {
  return artifactTypeCopy[artifactType] ?? artifactType
}
