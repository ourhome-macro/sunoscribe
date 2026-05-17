# Mojito F0-Candidate Diagnosis

日期：2026-05-17

## 结论

`f0-candidate` 的优化没有白做，但它解决的是：

1. authority 正确性
2. typed lineage
3. silent fallback / raw bypass

它没有自动解决：

1. 候选召回率是否足够
2. contour 到 candidate 的保守阈值是否过严
3. 某些真实歌曲上的大量滑音/不稳定段如何进入 production note stream

`mojito` 这次失败，主因不是 F0 没提出来，也不是 quantizer 把音删光了，而是：

> `PitchContourSet -> NoteCandidateSet v2` 这一层把大部分 contour 拒掉了。

## 真实数量链路

来自：

- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/f0_track.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/pitch_contours.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/note_candidates.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/selected_melody.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/quantized_notes.json`

数量变化：

- `F0Track.frames = 18836`
- `PitchContourSet.contours = 213`
- `NoteCandidateSet v2 accepted = 25`
- `MelodySelection selected = 19`
- `QuantizedNoteSet = 19`

所以损失不是发生在 quantizer，而是发生在 candidate build。

## 关键事实

### 1. F0 没问题

- `f0_frame_count = 18836`
- `vocal_activity_count = 419`
- `RMVPE` required stage 成功

说明不是“F0 没抽出来”。

### 2. contour 也不少

- `contour_count = 213`

说明不是“前面就没声部轮廓”。

### 3. 真正被砍死的是 candidate acceptance

`note_candidates.json` 顶层统计：

- `accepted_candidate_count = 25`
- `rejected_candidate_count = 188`
- `raw_candidates_empty = true`

拒绝原因：

- `too_unstable = 181`
- `too_short = 10`
- `low_confidence = 5`
- `outside_vocal_range = 2`
- `uncertain = 188`

这说明：

- 主要不是低置信度
- 主要不是音域错
- 主要是大量 contour 被判成“不稳定”

### 4. production path 现在故意不吃 raw detector note 作为主候选

这次 `raw_detector_evidence_count = 249`，说明 detector 其实看到了很多 note-like 证据。

但：

- `raw_candidate_input_count = 0`
- `candidate_origin_counts` 只有 `note_candidate_builder.contour_seed = 25`

这意味着当前 production authority 路径里，raw detector notes 只做 `optional_evidence`，不再直接进入生产候选。

所以这次不是“系统完全看不到音”，而是：

> 系统看到了很多 raw detector evidence，但 candidate-authority cutover 后，它们不能直接救 production recall。

### 5. MelodySelection 不是主凶

`selected_melody.json`：

- 输入候选 `25`
- 最终保留 `19`
- 只拒绝了 `6`

拒绝原因全是：

- `too_short`
- `uncertain`

说明 selector 只是最后再裁了一点，不是从 213 砍到 19 的元凶。

### 6. Quantizer 也不是主凶

`quantized_notes.json`：

- `note_count = 19`

和 selected melody 一样。

说明 quantizer 基本只是保留，不是主要删除器。

## 为什么“优化了”还是会失败

因为这次优化本质上是“把 production 路径从不干净改干净”，不是“把 recall 自动变强”。

具体来说：

1. 以前 raw detector 候选可能在某些情况下偷偷补 production note stream。
2. 现在为了 authority 正确，production note 必须从 `NoteCandidateSet v2` 来。
3. 于是 `contour -> candidate` 这层一旦过严，召回会直接塌。

`mojito` 就是这个问题的典型样本：

- contour 很多
- raw detector evidence 也很多
- 但 `contour_seed` 候选因为 `too_unstable` 被大量拒绝
- 最终 production 只剩 19 个 note

## 当前最值得怀疑的参数面

从 `note_candidates.json` 里的 config 看：

- `min_confidence = 0.5`
- `min_voiced_ratio = 0.68`
- `min_duration_sec = 0.08`
- `min_stability = 0.55`
- `max_pitch_range_semitones = 2.5`

结合拒绝统计，最该怀疑的是：

1. `min_stability`
2. `max_pitch_range_semitones`
3. 对 glide/vibrato 的 contour 稳定性判定方式

不是优先怀疑：

1. quantizer
2. score_ir builder
3. MIDI export

## 最短下一步

如果只针对这次 `mojito` 问题，最短有效动作不是继续改 F0 extractor，而是：

1. 专查前 40 秒被拒掉的 contour 候选
2. 看 `too_unstable` 是因为 pitch range 过大，还是 stddev 过高，还是 glide 被整体误伤
3. 在不恢复 raw bypass 的前提下，放宽 `NoteCandidateBuilder` 对 vibrato/glide 的 production acceptance

一句话收口：

> 这次失败不是因为 `f0-candidate` 优化无效，而是因为优化后 production 路径更干净了，结果把 `contour -> candidate` 这一层本来就过严的 recall 问题彻底暴露出来了。

