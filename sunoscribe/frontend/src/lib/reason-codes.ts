export const reasonCodeLabels: Record<string, { label: string; tooltip: string; suggestion: string }> = {
  large_quantize_error: {
    label: '节拍位置不稳',
    tooltip: '这个音和拍子网格偏差较大，可能需要调整时值或重新检查节拍。',
    suggestion: '先听这个音的起点，再考虑调整时值。',
  },
  octave_outlier: {
    label: '可能高/低了八度',
    tooltip: '系统觉得这个音的八度不太像主唱真实旋律，常见于音高识别跳八度。',
    suggestion: '试试升高八度或降低八度。',
  },
  possible_fragmentation: {
    label: '可能被切太碎',
    tooltip: '一个长音可能被拆成多个短音，常见于颤音或滑音。',
    suggestion: '检查是否应该合并或延长。',
  },
  possible_overmerge: {
    label: '可能合并过头',
    tooltip: '多个相邻音可能被当成了一个长音。',
    suggestion: '检查是否需要删除、拆分或重新调整时值。',
  },
  low_confidence: {
    label: '把握不高',
    tooltip: '系统对这个音的判断不够确定，需要人工听辨。',
    suggestion: '优先听这一小节的人声。',
  },
  uncertain: {
    label: '待确认',
    tooltip: '系统或助手已经把这个音标记为需要确认。',
    suggestion: '确认后可以修正，或继续标记待确认。',
  },
  low_voiced_ratio: {
    label: '有效人声太少',
    tooltip: '这一段可能是气声、弱唱、换气，或主唱分离不够干净。',
    suggestion: '检查是否应该保留为音符。',
  },
  too_short: {
    label: '短音可疑',
    tooltip: '这个音太短，可能只是颤音、滑音或切分碎片。',
    suggestion: '考虑改短、改长或删除。',
  },
  too_unstable: {
    label: '音高不稳',
    tooltip: '这一段音高波动较大，可能是颤音、滑音或识别不稳定。',
    suggestion: '先按听感判断中心音高。',
  },
  outside_vocal_range: {
    label: '超出常见人声范围',
    tooltip: '这个音可能不像主唱能唱出的范围，可能是八度错误或伴奏串扰。',
    suggestion: '优先检查八度。',
  },
  likely_harmonic: {
    label: '可能是泛音',
    tooltip: '系统可能追到了泛音，而不是真实基频。',
    suggestion: '听起来偏尖或偏高时，尝试降八度。',
  },
  likely_accompaniment_bleed: {
    label: '可能混入伴奏',
    tooltip: '伴奏残留可能影响了主唱旋律判断。',
    suggestion: '如果听不到人声，可以考虑删除。',
  },
  duplicate_fragment: {
    label: '重复碎片',
    tooltip: '这一段可能重复记录了相同旋律片段。',
    suggestion: '检查是否删除重复音。',
  },
  overlaps_stronger_candidate: {
    label: '被更强候选覆盖',
    tooltip: '同一时间附近还有更可靠的候选音。',
    suggestion: '优先保留听起来更像主唱的音。',
  },
  insufficient_onset_evidence: {
    label: '起音不明确',
    tooltip: '这个音从哪里开始不够清楚，节奏位置可能不准。',
    suggestion: '检查拍点和时值。',
  },
  silence_or_breath_region: {
    label: '像静音或换气',
    tooltip: '这一段可能不是稳定唱音。',
    suggestion: '如果不是实际旋律音，可以删除。',
  },
  suspected_vibrato: {
    label: '可能是颤音',
    tooltip: '颤音会让系统误以为有多个音或音高不稳。',
    suggestion: '按听感保留一个中心音。',
  },
  suspected_glide: {
    label: '可能是滑音',
    tooltip: '滑音会让音高中心和边界变得难判断。',
    suggestion: '确认要记成目标音还是过渡音。',
  },
  dp_fallback: {
    label: '节拍对齐用了备用路径',
    tooltip: '节拍量化没有走到理想路径，结果需要谨慎检查。',
    suggestion: '优先检查节奏位置。',
  },
  rhythm_grid_unavailable: {
    label: '节拍网格缺失',
    tooltip: '没有可靠节拍网格时，音符时值和小节位置都可能不准。',
    suggestion: '需要重新生成节奏分析。',
  },
  dp_no_candidate_path: {
    label: '没找到稳定旋律路径',
    tooltip: '系统没有找到足够可靠的一串候选音。',
    suggestion: '检查主唱分离和音高识别质量。',
  },
  quantizer_backend_unsupported: {
    label: '节拍对齐后端不支持',
    tooltip: '当前处理方式不支持这类量化结果，应明确失败或切换配置。',
    suggestion: '交给诊断流程处理。',
  },
}

export function describeReasonCode(code: string) {
  return reasonCodeLabels[code] ?? { label: code, tooltip: '未知原因编码，保留原始编码用于排查。', suggestion: '请查看诊断报告。' }
}
