# Mojito lead-vocal segmentation completion review - 2026-05-17

## 结论

`mojito` 的 lead-vocal 失败已经从 `quality_failed` 修到 benchmark `success`。

根因不是 quantizer，也不是 reference track 错误，而是 `PitchContourSet -> NoteCandidateSet v2` 对长滑音/旋律短音节的处理过硬：先前只保留稳定 plateau 的 180ms 核，导致候选数量和候选总时长严重不足；后续 selected/quantized 基本只是继承这个稀疏输入。

本轮最终修复采用最小生产路径：

1. 在 `NoteCandidateBuilder` 内对 `too_unstable` contour 做稳定子段切分。
2. 用稳定子段定 pitch center / confidence / stability。
3. 只在同一 source contour 内，用相邻已接受稳定子段作为边界，把 note duration 扩到有 F0 支撑的上下文，默认最多 `0.35s`。
4. 不用 reference MIDI 修 production 输出；reference 只用于 benchmark 评价和诊断。
5. benchmark reference review 将 DTW 对 fragmented prediction 的提升归为 prediction diagnostic，不再误判 reference_suspect。

## 关键产物对比

### 原始真实 run

Run: `samples/benchmark_runs/codex_20260517_mojito_reference_shift_dtw_split`

- status: `quality_failed`
- reference status: `likely_comparable`
- candidates: `107 accepted / 126 rejected`
- contour segments: `82`
- selected / quantized: `96 / 93`
- quantized total duration: `23.69s`
- gap50 ratio: `0.8913`
- short note ratio: `0.1505`
- note recall: `0.0392`
- note F1: `0.0639`
- MIDI coverage: `0.1313`
- failed checks: `midi_coverage_ratio`, `note_recall`

### 中间修复：短音节切分

Run: `samples/benchmark_runs/codex_20260517_mojito_segmentation_short_syllable`

- candidates: `250 accepted / 67 rejected`
- contour segments: `225`
- selected / quantized: `221 / 208`
- quantized total duration: `48.57s`
- gap50 ratio: `0.7391`
- short note ratio: `0.4519`
- note recall: `0.0613`
- note F1: `0.0812`
- MIDI coverage: `0.2691`
- problem: 只切稳定核，短音过多，coverage 仍不足。

### 最终修复：accepted segment context extension 350ms

Run: `samples/benchmark_runs/codex_20260517_mojito_segment_extension_350ms`

- status: `success`
- reference status: `likely_comparable`
- reference suspect: `0`
- prediction diagnostic: `sequence_alignment_improves_fragmented_prediction`
- candidates: `250 accepted / 67 rejected`
- origin counts:
  - `note_candidate_builder.contour_seed = 25`
  - `note_candidate_builder.contour_segment = 225`
- selected / quantized: `236 / 205`
- candidate total duration: `77.42s`
- selected / quantized total duration: `78.61s`
- gap50 ratio: `0.5196`
- short note ratio: `0.1024`
- large jump ratio: `0.0539`
- note recall: `0.0858`
- octave-normalized recall: `0.1005`
- note F1: `0.1142`
- pitch accuracy: `0.5714`
- octave-normalized pitch accuracy: `0.6341`
- MIDI coverage: `0.4381` effective pass against threshold `0.4271`
- failed checks: none

## 代码修复

### `backend/app/modules/pitch/note_candidate_builder.py`

新增/调整：

- `segmentation_min_subsegment_duration_sec = 0.12`
- `segmentation_max_subsegment_duration_sec = 1.25`
- `segmentation_max_pitch_range_semitones = 1.00`
- `segmentation_max_pitch_stddev_semitones = 0.60`
- `segmentation_context_extension_sec = 0.35`

核心逻辑：

- `too_unstable` contour 不再直接整体拒绝。
- `_stable_frame_segments` 找稳定 pitch 子段。
- `_build_candidate_from_segment` 用稳定核计算 pitch center / range / stddev / confidence。
- `_extend_accepted_segment_candidates` 只基于已接受子段扩 duration，不让被拒短碎片夹断 note。
- `segmentation_evidence` 记录：
  - `stable_start_time_sec`
  - `stable_end_time_sec`
  - `stable_duration_sec`
  - `context_extension_sec`
  - `pitch_range_semitones`
  - `pitch_stddev_semitones`
  - source contour lineage
- `analysis_info.segmentation_counts` 记录 segment 接受和拒绝原因。

### `backend/app/modules/pitch/config.py`

新增生产配置字段：

- `note_candidate_segmentation_min_source_duration_sec`
- `note_candidate_segmentation_min_subsegment_duration_sec`
- `note_candidate_segmentation_max_subsegment_duration_sec`
- `note_candidate_segmentation_max_pitch_range_semitones`
- `note_candidate_segmentation_max_pitch_stddev_semitones`
- `note_candidate_segmentation_max_frame_gap_sec`
- `note_candidate_segmentation_context_extension_sec`

### `backend/app/modules/pitch/pipeline.py`

- `PitchPipeline._note_candidate_builder_config()` 传递上述配置。
- confidence policy metadata 暴露这些阈值，保证产物可追踪。

### `backend/app/scripts/mp4_midi_benchmark.py`

- reference review 不再把 fragmented prediction 的 DTW lift 误归为 `reference_suspect`。
- 新 prediction diagnostic: `sequence_alignment_improves_fragmented_prediction`。

## 测试与验证

定向测试：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m pytest tests\test_note_candidate_builder.py tests\test_pitch_pipeline.py tests\test_mp4_midi_benchmark_cli.py -q
```

结果：`51 passed`。

最终真实样本验证：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito --run-id codex_20260517_mojito_segment_extension_350ms
```

结果：`mojito: success`。

## 后续仍可完善

`mojito` 虽已过 gate，但仍有可见诊断：

- `gap50_ratio = 0.5196`，仍偏碎。
- `prediction_diagnostic_reason_counts.sequence_alignment_improves_fragmented_prediction = 1`。
- DTW recall proxy 明显高于 raw recall，说明旋律结构可对齐，但 local timing / segmentation 还不够顺。

下一步不应继续盲目放宽 `NoteCandidateBuilder`。更合理的方向是：

1. 做 phrase-level same-contour / same-syllable 合并或 duration smoothing。
2. 改 melody postprocessor 的局部 gap/短音合并，而不是让 builder 吃掉更多不稳定 F0。
3. 为 selected/quantized 添加 visual diagnostic：F0 trajectory + stable core + extended note span + rejected segment overlay。
4. 单独处理 `time_shift_improves_alignment` / DTW diagnostic：这是 production timing/segmentation 质量提示，不是 reference 修复入口。
## 2026-05-17 phrase_postprocessor probe

我按“强化 phrase merge / sustain + 碎句吸积”方向做了一轮探针实现，然后用真实 `mojito` 跑了定向验证。

Probe run:
`E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\codex_20260517_mojito_phrase_merge_probe`

结果结论很明确：这条路当前实现过头了，不能直接进主线。

### probe 结果

- benchmark status 仍然是 `success`
- 但 selected note count 从 `236` 被压到 `99`
- postprocess action count `118`
- 其中 `fragment_island_accumulate = 89`
- output MIDI note count `99`
- phrase count `84`
- `tiny_phrases<=2` 比例升到 `95.24%`
- `gap50_ratio = 0.8367`
- `note_f1 = 0.0750`
- `pitch_accuracy = 0.4737`

### 判断

这说明“吸积”并没有把旋律组织成更长的 singing phrase，反而把原本还能对齐的局部音序压扁成更少、更长但更错的 note，导致：

- 对齐指标退化
- 局部旋律骨架丢失
- 碎句并没有真正减少，反而变成大量 1-2 note phrase

### 结论

`phrase_postprocessor.py` 确实是下一阶段需要处理的层，但不能直接靠局部 gap+pitch 阈值做 aggressive merge / island accumulation。

下一步更合理的是：

1. 先做 phrase 分段诊断，而不是直接合并。
2. 在 phrase 内做更弱的 duration smoothing / sustain。
3. 真正的“治碎”应优先利用 contour lineage 和 stable core 上下文，而不是只看 selected note 邻接关系。
4. 如果要继续改 phrase 层，必须先把 merge 的目标限定为“同一 source contour / 同一 contour segment chain / 同一局部 pitch shelf”，否则会把旋律轮廓压坏。
## 2026-05-17 same-contour phrase probe (rolled back)

按“只在同一 `source_contour_id` 内做 tiny phrase merge/absorb，并保持不跨 contour”方向做了一轮真实 `mojito` probe。

Probe runs:
- 失败版：`E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\codex_20260517_mojito_same_contour_phrase_v3`
- 恢复基线版：`E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\codex_20260517_mojito_restore_success`

### probe 结论

这条策略的局部约束本身没有逻辑错误，但在真实样本上会把原本有效的 phrase continuity 修复一起关掉，导致 benchmark 从 `success` 掉回 `quality_failed`。

失败版关键对比：

- 基线成功版：
  - `selected_count = 236`
  - `quantized = 205`
  - `midi_coverage_ratio = 0.4355`
  - postprocess actions: `phrase_gap_sustain = 19`, `short_gap_bridge = 7`, `median_smoothing = 1`
- same-contour probe 失败版：
  - `selected_count = 243`
  - `quantized = 214`
  - `midi_coverage_ratio = 0.4251`
  - postprocess actions: only `median_smoothing = 1`

虽然失败版的 `note_recall` / `note_f1` / `pitch_accuracy` 上升了，但 `coverage` 和 `gap50_ratio` 变差，最终掉出 quality gate。

### 结论

- `short_gap_bridge` / `short_note_absorb` 做 same-contour tiny guard 是合理方向，但当前实现还不能直接进主线。
- 真正的问题不是 merge 逻辑本身，而是它连带把原有 19 次有效 `phrase_gap_sustain` 也关掉了。
- 对 `mojito` 这类样本，当前 phrase 层的 continuity 修复比局部 same-contour merge 更关键。

### 当前主线决策

- 已回滚这轮 phrase probe 改动。
- 保留 `note_candidate_builder.py` 成功基线。
- 当前恢复 run：`E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\codex_20260517_mojito_restore_success`
- benchmark 已恢复：`mojito: success`

### 下一步建议

如果后续继续做 phrase 层，不要直接在现有 `phrase_postprocessor.py` 上替换主逻辑；应改成：

1. 保留现有 sustain/bridge 主线。
2. 在独立 diagnostic pass 中标记 same-contour tiny phrases。
3. 先做离线听感审查，再决定是否引入极小范围 merge。
4. phrase 改动必须满足双条件：
   - `mojito` benchmark 不能掉回 fail
   - 听感碎片必须实际改善
