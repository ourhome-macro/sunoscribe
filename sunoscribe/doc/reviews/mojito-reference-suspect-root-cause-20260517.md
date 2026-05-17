# Mojito reference_suspect 继续排查（2026-05-17）

## 结论

- `expected_melody_track=2` 没有选错。这里的 `2` 是 mido 原始 track index；Mojito MIDI 的 mido track 0/1 是空元数据轨，track 2 才是第一个有音的 `Mojito` 高声部。
- `octave_reference_suspect` 是真问题：参考 melody track 的中位音高是 MIDI 74，而真实 RMVPE F0 和当前 selected melody 的中位音高都约 MIDI 60，差约 14 个半音；把参考 track 2 下移 12 半音后，中位音高变 62，才和真实 F0 对齐。
- `dtw_sequence_alignment_suspect` 不是“错轨”的证据，更像“参考 MIDI 是量化/记谱旋律，当前产物仍稀疏且 timing 不可严格按 onset 对齐”的证据。当前产物只有 93 个导出音，对参考 408 个音，覆盖率 0.131，所以 DTW 能救回顺序匹配但不能证明参考时间轴错。
- 继续修 production pipeline 时，不应拿参考 MIDI 修 `ScoreRevision`；benchmark 层可以增加显式参考转调/八度元数据，避免把男声 F0 与高八度记谱 MIDI 当作同一音区硬比。

## 触发 suspect 的真实规则

`backend/app/scripts/mp4_midi_benchmark.py` 中 `_reference_review_sample` 给 Mojito 打了两个 reason：

- `octave_reference_suspect`：DTW 最佳八度位移是 `12`，且 DTW pitch-match recall `0.1936 >= 0.10`，同时没有应用 octave shift。
- `dtw_sequence_alignment_suspect`：DTW recall lift 是 `0.1887 >= 0.10`。

当前 `reference_review.json` 关键值：

```json
{
  "reference_status": "reference_suspect",
  "reference_suspect_reasons": [
    "octave_reference_suspect",
    "dtw_sequence_alignment_suspect"
  ],
  "expected_note_count": 408,
  "predicted_note_count": 93,
  "predicted_expected_note_ratio": 0.22794117647058823,
  "note_recall": 0.004901960784313725,
  "octave_normalized_note_recall": 0.024509803921568627,
  "median_pitch_delta_raw": -14.0,
  "dtw_pitch_match_recall_proxy": 0.19362745098039216,
  "dtw_recall_lift": 0.18872549019607843,
  "best_dtw_octave_shift_semitones": 12,
  "pred_to_exp_shift_sec": -0.943,
  "shift_corrected_recall": 0.19362745098039216,
  "shift_corrected_matched": 79,
  "first_note_delay_sec": 1.6701240818181802
}
```

## Manifest 与 MIDI 轨道核验

Manifest 片段：

```json
{
  "id": "mojito",
  "expected_midi": "source_mid/Mojito.mid",
  "expected_melody_track": 2,
  "expected_reference_strategy": null,
  "tags": [
    "lead_vocal_midi",
    "paired_v1"
  ],
  "notes": "Initial v1 melody-track label; review by listening before enabling strict quality gates."
}
```

Mido 轨道统计：

| index | name | program | is_drum | note_count | first | last | median_pitch | min_pitch | max_pitch | total_note_sec | coverage | gap50_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 |  | None | False | 0 |  |  |  | None | None |  |  |  |
| 1 |  | None | False | 0 |  |  |  | None | None |  |  |  |
| 2 | Mojito | 88 | False | 408 | 17.739 | 176.342 | 74.0 | 64 | 84 | 120.391 | 0.759 | 0.032 |
| 3 | TGlaogong | 66 | False | 131 | 1.304 | 154.69 | 74 | 56 | 84 | 39.484 | 0.257 | 0.023 |
| 4 | QQ394358936 | 0 | False | 368 | 2.087 | 176.864 | 46.5 | 36 | 59 | 139.783 | 0.8 | 0.079 |
| 5 | MIDISHOW | None | True | 615 | 2.087 | 176.478 | 40 | 36 | 70 | 100.956 | 0.579 | 0.007 |

解释：`pretty_midi` 打印的 instrument 0 对应 mido track 2，所以不是 0/1-based bug。

## 真实 F0 vs 参考 MIDI 音区

- F0 voiced conf>=0.5：`{'n': 8418, 'min': 39.969, 'p25': 57.077, 'median': 59.941, 'p75': 63.778, 'max': 83.731, 'mean': 59.844}`
- selected melody：`{'n': 96, 'min': 49.526, 'p25': 58.792, 'median': 60.054, 'p75': 63.835, 'max': 83.526, 'mean': 60.532}`
- 参考 mido track 2：median pitch `74`，range `64-84`
- 参考 mido track 2 下移 12 半音：median pitch `62`，range `52-72`

这说明 Mojito 的参考 MIDI 很可能是“方便记谱/演奏的高八度 melody”，而不是声学 F0 同音区标注。

## 不同参考假设下的指标

| track | reference_pitch_shift | expected | expected_median_pitch | median_pitch_delta | raw_recall | raw_f1 | matched | octave_recall | octave_matched | dtw_recall | dtw_octave_shift | shift_corrected_recall | shift_corrected_matched | first_delay |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | 0 | 408 | 74.0 | -14.0 | 0.0049 | 0.008 | 2 | 0.0245 | 10 | 0.1936 | 12 | 0.1936 | 79 | 1.67 |
| 2 | -12 | 408 | 62.0 | -2.0 | 0.0392 | 0.0639 | 16 | 0.0466 | 19 | 0.1936 | 0 | 0.201 | 82 | 1.67 |
| 3 | 0 | 131 | 74.0 | -14.0 | 0.0 | 0.0 | 0 | 0.0 | 0 | 0.1756 | 12 | 0.0611 | 8 | 18.105 |
| 3 | -12 | 131 | 62.0 | -2.0 | 0.0076 | 0.0089 | 1 | 0.0076 | 1 | 0.1756 | 0 | 0.0763 | 10 | 18.105 |
| 4 | 0 | 368 | 46.5 | 13.5 | 0.0054 | 0.0087 | 2 | 0.0163 | 6 | 0.1495 | -12 | 0.0462 | 17 | 17.322 |
| 4 | 12 | 368 | 58.5 | 1.5 | 0.019 | 0.0304 | 7 | 0.0245 | 9 | 0.1495 | 0 | 0.0543 | 20 | 17.322 |
| 5 | 0 | 615 | 40.0 | 20.0 | 0.0 | 0.0 | 0 | 0.0195 | 12 | 0.0504 | -24 | 0.0211 | 13 | 17.322 |
| 5 | 12 | 615 | 52.0 | 8.0 | 0.0016 | 0.0028 | 1 | 0.0211 | 13 | 0.0504 | -12 | 0.0228 | 14 | 17.322 |

关键观察：

- track 2 原始：median delta `-14`，raw recall `0.0049`，DTW 最佳 octave shift `12`。
- track 2 下移 12：median delta 变 `-2`，raw recall 升到 `0.0392`，DTW octave shift 变 `0`。
- 即使下移 12，recall 仍没过 `0.05`，主要因为产物稀疏/断裂，不是参考轨完全错。

## 最小修正建议

1. benchmark manifest 增加显式字段，例如 `expected_reference_pitch_shift_semitones: -12`，只作用于 benchmark reference extraction，不进入 production pipeline。
2. Mojito 样本配置该字段为 `-12`，并把 notes 改成：`Reference melody is notated one octave above acoustic lead-vocal F0; apply benchmark-only -12 semitone shift.`
3. `dtw_sequence_alignment_suspect` 不应在低覆盖/高 gap 输出时直接归咎 reference。建议拆成：`reference_timing_suspect` 和 `sequence_alignment_improves_sparse_prediction`。
4. 在继续修 lead-vocal pipeline 前，先把 benchmark reference octave 元数据显式化，否则质量指标会持续混入“记谱音区 vs 声学 F0 音区”的偏差。

## 2026-05-17 实施结果

已按上述最小修正落地：

- `BenchmarkSample` 新增 `expected_reference_pitch_shift_semitones`，范围限制为 `[-24, 24]`。
- `mp4_midi_benchmark` 在 `extract_reference_melody_notes` 后对 benchmark reference notes 应用 pitch shift；该逻辑只影响评测，不进入 production `ScoreRevision`。
- `samples/manifest.v1.json` 的 `mojito` 已配置 `expected_reference_pitch_shift_semitones: -12`。
- `reference_review` 将低覆盖/高 gap 场景下的 DTW 提升降级为 `prediction_diagnostic_reasons: [sequence_alignment_improves_sparse_prediction]`，不再误标 reference suspect。

验证命令：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m pytest tests\test_mp4_midi_benchmark_cli.py -q
.\.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito --run-id codex_20260517_mojito_reference_shift_dtw_split
```

验证结果：

- `tests/test_mp4_midi_benchmark_cli.py`：`22 passed`。
- Mojito 仍 `quality_failed`，但 `reference_status` 已从 `reference_suspect` 变为 `likely_comparable`。
- `reference_suspect_reasons` 为空；`prediction_diagnostic_reason_counts` 为 `{sequence_alignment_improves_sparse_prediction: 1}`。
- 指标按 -12 reference shift 后变为：raw recall `0.0392`，raw F1 `0.0639`，matched `16`，median pitch delta `-2.0`，octave shift applied `0`。
- 当前失败焦点已明确回到 pipeline：`midi_coverage_too_low`、`fragmented_melody_gaps`、`large_pitch_jumps`。
