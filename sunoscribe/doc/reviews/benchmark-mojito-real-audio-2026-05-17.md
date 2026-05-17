# Benchmark Run - Mojito Real Audio

日期：2026-05-17

## 运行命令

```powershell
cd backend
.\.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito --run-id codex_20260517_mojito_real_audio
```

## 结果概览

最终状态：

- `mojito: quality_failed`

这不是 pipeline 崩溃，而是：

- `dataset_validation = success`
- `mp4_to_midi_pipeline = success`
- `midi_metrics = success`
- `quality_gate = quality_failed`

说明：

1. 真是完整真实音频链路跑通了。
2. required stage 没炸。
3. 失败点在输出质量，不在工程链路可用性。

## 产物位置

run root:

- `samples/benchmark_runs/codex_20260517_mojito_real_audio/`

单样本产物：

- `samples/benchmark_runs/codex_20260517_mojito_real_audio/mojito/produced.mid`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/mojito/stage_status.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/mojito/metrics.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/mojito/quality_gate.json`

## 关键事实

### 1. 主链真的跑通

pipeline stage 输出显示：

- `canonical_audio_path` 已生成
- `vocals_path` 已生成
- `accompaniment_path` 已生成
- `has_f0_track = true`
- `has_note_candidates = true`
- `has_rhythm_grid = true`
- `has_score_data = true`
- `midi_path = .../exports/final_score.mid`

这说明真实 `MP4 -> ingest -> separation -> pitch -> score -> midi` 已跑通。

### 2. 质量很差，不是轻微退化

`Mojito.mid` 参考主旋律轨：

- expected note count: `408`

预测 MIDI：

- predicted note count: `19`

核心指标：

- raw `note_f1 = 0.0`
- raw `note_recall = 0.0`
- raw `note_precision = 0.0`
- `midi_coverage_ratio = 0.019685`
- `first_note_delay_sec = 18.360`

八度归一化后也几乎没救：

- octave-normalized `note_recall = 0.002451`
- octave-normalized `matched_note_count = 1`

### 3. quality gate 失败项

失败的 4 项：

1. `first_note_delay_sec = 18.36 > 15.0`
2. `midi_coverage_ratio = 0.019685 < 0.039583`
3. `note_recall = 0.002451 < 0.05`
4. `matched_notes = 1 < 10`

### 4. 失败模式判断

benchmark 自动归因为：

- `too_few_predicted_notes`
- `leading_silence_too_long`
- `midi_coverage_too_low`
- `possible_octave_error`
- `time_shift_improves_alignment`
- `expected_track_starts_before_vocal`
- `median_pitch_range_mismatch`

### 5. 对齐/参考诊断提示

这里有两个重要信号：

1. 参考被标记为 `reference_suspect`
   - `first_note_offset_suspect`
   - `time_origin_suspect`

2. 即使做时间/八度诊断补偿，提升仍然有限
   - best time-shift recall: `0.009804`
   - shift-corrected recall: `0.031863`
   - shift-corrected f1: `0.06089`

这说明：

- 参考 MIDI 轨可能存在时间原点不完全对齐问题；
- 但就算考虑这个问题，当前 produced MIDI 质量仍然远远不够。

## 现阶段判断

对 `mojito` 这首真实音频样本，当前系统状态是：

> 工程链路可运行，但转写质量明显不达标。

更直白一点：

- 不是“跑不起来”
- 是“跑起来了，但只产出了 19 个音，参考有 408 个音，严重漏检”

## 最值得盯的方向

按这次结果，下一步优先级不是 ingest/separation，而是 melody coverage：

1. 为什么 `selected_melody/quantized_notes` 最后只剩 19 个 note
2. 是 `NoteCandidateSet -> MelodySelection` 过度保守，还是 upstream candidate 本来就太少
3. `Mojito` 的 reference 是否确实存在 time-origin / track-selection 偏差，但即便修正参考，当前 recall 仍明显过低

