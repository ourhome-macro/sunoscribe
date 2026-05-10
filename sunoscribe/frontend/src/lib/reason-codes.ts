export const reasonCodeLabels: Record<string, { label: string; tooltip: string }> = {
  large_quantize_error: {
    label: '量化误差大',
    tooltip: '音符与节拍网格偏差较大，优先检查节奏网格或持续时值。',
  },
  octave_outlier: {
    label: '八度可疑',
    tooltip: 'F0 或候选音高可能出现八度错误，可尝试升/降八度。',
  },
  possible_fragmentation: {
    label: '疑似碎片化',
    tooltip: '一个持续音可能被切成多个短音，适合检查合并或时值调整。',
  },
  possible_overmerge: {
    label: '疑似过度合并',
    tooltip: '多个音可能被合并为一个音，适合检查拆分或删除。',
  },
  low_confidence: {
    label: '置信度低',
    tooltip: '转写置信度低，需要结合 ScoreIR note summary 和诊断判断。',
  },
  uncertain: {
    label: '待确认',
    tooltip: '系统或 agent 已标记该音符需要人工确认。',
  },
  low_voiced_ratio: {
    label: '有效发声少',
    tooltip: '该片段 voiced frames 较少，可能是气声、弱唱或分离质量问题。',
  },
  too_short: {
    label: '短音可疑',
    tooltip: '音符过短，可能是颤音、滑音或分段碎片。',
  },
  too_unstable: {
    label: '音高不稳',
    tooltip: '片段内 F0 波动大，需要谨慎调整音高或时值。',
  },
  outside_vocal_range: {
    label: '超出人声范围',
    tooltip: '音高超出预期主唱范围，可能是八度或伴奏串扰。',
  },
  likely_harmonic: {
    label: '疑似谐波',
    tooltip: '检测到的音高可能是泛音而非真实基频。',
  },
  likely_accompaniment_bleed: {
    label: '疑似伴奏串扰',
    tooltip: '伴奏残留可能影响主唱 F0 或候选音符。',
  },
  duplicate_fragment: {
    label: '重复碎片',
    tooltip: '可能存在重复候选片段，适合检查删除或合并。',
  },
  overlaps_stronger_candidate: {
    label: '被强候选覆盖',
    tooltip: '该候选与更强候选重叠，可能不是最终主旋律音。',
  },
  insufficient_onset_evidence: {
    label: '起音证据弱',
    tooltip: '缺少明确 onset 证据，节奏位置可能不可靠。',
  },
  silence_or_breath_region: {
    label: '静音/换气区',
    tooltip: '该区域可能不是稳定唱音，需避免误改成确定音符。',
  },
  suspected_vibrato: {
    label: '疑似颤音',
    tooltip: '颤音可能导致过度分段或音高抖动。',
  },
  suspected_glide: {
    label: '疑似滑音',
    tooltip: '滑音可能导致音高中心或边界判断困难。',
  },
  dp_fallback: {
    label: 'DP 回退',
    tooltip: '量化阶段使用了回退路径，结果应显示为诊断风险。',
  },
  rhythm_grid_unavailable: {
    label: '节奏网格缺失',
    tooltip: '缺少 RhythmGrid 会污染节奏量化，不能当作可靠成功结果。',
  },
  dp_no_candidate_path: {
    label: '候选路径缺失',
    tooltip: '动态规划未找到稳定候选路径，需检查 F0 和候选。',
  },
  quantizer_backend_unsupported: {
    label: '量化后端不支持',
    tooltip: '当前量化后端不满足该任务，需要明确失败或诊断处理。',
  },
}

export function describeReasonCode(code: string) {
  return reasonCodeLabels[code] ?? { label: code, tooltip: '未知 reason code，请保留原始稳定编码用于排查。' }
}
