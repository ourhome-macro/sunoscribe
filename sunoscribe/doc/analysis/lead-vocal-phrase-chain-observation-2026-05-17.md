# Lead Vocal Candidate 后半段链路观察：Phrase 到 ScoreIR

日期：2026-05-17

## 结论先行

当前 `f0 -> contour -> candidate` 后面的主链路已经不是裸 detector 输出，而是：

```text
NoteCandidateSet v2
  -> RuleBasedMelodySelector.select
  -> PhraseAwarePostprocessor
  -> selected_melody_v2
  -> NoteQuantizer / QuantizedNoteSet v2
  -> ScoreIRBuilder
  -> ScoreRevision / MIDI / MusicXML
```

重点看 phrase 段：它确实接入了生产主链路，位置在 MelodySelection 内部，而不是只作为 debug 工具。整体方向是对的：phrase 后处理在进入量化前修正局部碎片、短缝、八度跳变和局部中值离群，后续 ScoreIR 强制从 QuantizedNoteSet 构建并校验 lineage。

但现在最危险的不是 f0-candidate，而是 phrase 和 quantize 的边界：phrase 修改了旋律事件的时值/音高/合并关系，量化又会二次吸附时间；如果 phrase 的动作没有被稳定地映射到最终 ScoreIR 的 issue/trace 上，前端和人工修正会看见结果，却不容易知道是哪一步改的。

## 实际代码链路

### 1. PitchPipeline 主流程

入口：`backend/app/modules/pitch/pipeline.py:1284`

关键顺序：

1. `detected_notes`：从 lead audio 跑 detector。
2. `lead_f0_track`：RMVPE F0 是 required stage，失败直接抛 `required_f0_extraction_failed`。
3. `pitch_contours_payload`：从 F0Track 建 PitchContourSet。
4. `note_candidate_payload`：构建 NoteCandidateSet v2。
5. `_select_authoritative_melody(...)`：进入 MelodySelection。
6. `lead_notes = melody_selection.notes`。
7. `self.quantizer.quantize(lead_notes, ...)`。
8. `_restore_quantized_lineage(...)` 和 `_recompute_quantized_positions(...)`。
9. `_build_quantized_note_set_payload(...)`。
10. `semantic_audio.melody_candidates.analysis_info` 中挂载：
    - `pitch_contours`
    - `note_candidate_set`
    - `selected_melody`
    - `quantized_notes`

对应挂载点：`backend/app/modules/pitch/pipeline.py:1543` 到 `backend/app/modules/pitch/pipeline.py:1549`。

### 2. Phrase 后处理入口

入口：`backend/app/modules/pitch/melody_selection_artifact.py:80`

`RuleBasedMelodySelector.select(...)` 做了三件事：

```text
candidate 规则筛选
  -> overlap resolve
  -> contour bridge accepted candidates 注入
  -> PhraseAwarePostprocessor.process_dict_notes(selected)
  -> selected_melody_v2
```

关键代码：

- `backend/app/modules/pitch/melody_selection_artifact.py:102`：先做 overlap resolve。
- `backend/app/modules/pitch/melody_selection_artifact.py:104`：从 contours 补 bridge candidates。
- `backend/app/modules/pitch/melody_selection_artifact.py:113`：调用 phrase postprocessor。
- `backend/app/modules/pitch/melody_selection_artifact.py:129`：返回 `selected_melody_v2`。

### 3. PhraseAwarePostprocessor 做了什么

文件：`backend/app/modules/pitch/phrase_postprocessor.py:110`

处理顺序在 `_process(...)` 内部：

```text
normalize/sort notes
  -> bridge short gaps
  -> absorb short notes
  -> remove isolated fragments（配置默认关闭）
  -> sustain phrase gaps
  -> correct octave jumps
  -> correct octave islands
  -> median smooth
  -> repeat until max_iterations or signature unchanged
```

它会生成 `PhrasePostprocessAction`，最终进入 selected melody 的：

- `summary.postprocess_action_counts`
- `summary.postprocess_reason_code_counts`
- `postprocess.actions`

这些 action 又被 `PitchPipeline` 摘要化到 `analysis_info`：

- `melody_postprocess_action_counts`
- `melody_postprocess_reason_code_counts`
- `melody_postprocess_actions`

对应：`backend/app/modules/pitch/pipeline.py:1579` 到 `backend/app/modules/pitch/pipeline.py:1581`。

## 后半段持久化与导出

### 1. MelodyTranscriptionService 抽取 typed artifacts

入口：`backend/app/services/melody_transcription_service.py:45`

它从 `PitchAnalysisResult.semantic_audio.melody_candidates.analysis_info` 中取：

- `PitchContourSet`：`backend/app/services/melody_transcription_service.py:94`
- `NoteCandidateSet v2`：`backend/app/services/melody_transcription_service.py:97`
- `selected_melody_v2`：`backend/app/services/melody_transcription_service.py:100`
- `QuantizedNoteSet v2`：`backend/app/services/melody_transcription_service.py:104`

并且会校验 selected melody 至少有 lineage，失败直接抛错：`backend/app/services/melody_transcription_service.py:115`。

### 2. ScoreIR 只吃 QuantizedNoteSet

入口：`backend/app/modules/score_ir/builder.py:30`

当前策略很明确：

- `_validate_required_quantized_artifact(...)` 要求 production lead-vocal 必须有 QuantizedNoteSet。
- `_build_notes_from_quantized_primary(...)` 优先从 quantized measures 构建 ScoreNote。
- `_validate_production_lineage(...)` 要求每个 ScoreNote 保留：
  - `source=quantized_notes`
  - `quantized_note_id`
  - `source_candidate_id`
  - `source_candidate_ids`
  - `source_contour_ids`
  - `source_f0_frame_range`

对应：`backend/app/modules/score_ir/builder.py:302` 到 `backend/app/modules/score_ir/builder.py:335`。

这点是正确的，说明后半段已经在向 typed artifact chain 靠拢，不是直接从 raw notes 乱生成谱。

## 我看到的主要问题

### P0：phrase 的动作没有成为 ScoreIR 的一等诊断

phrase action 留在 `selected_melody` 和 `pitch_result.analysis_info`，最终 ScoreIR note 只带 `reason_codes`，但没有稳定地带出：

- action 类型，例如 `short_gap_bridge`、`octave_jump_correction`、`median_smoothing`
- action 前后音高
- action 前后时间范围
- 合并了哪些 source candidates

这会导致前端看见某个音变了，但无法解释“是 F0 原始如此、candidate 切分如此、phrase 修过、还是 quantizer 改过”。对生产调参非常不利。

建议：在 `QuantizedNoteSet.notes[]` 加一个稳定字段，例如：

```json
"postprocess_trace": [
  {
    "stage": "phrase_postprocess",
    "action": "octave_jump_correction",
    "reason_code": "octave_jump_corrected",
    "source_candidate_ids": ["..."],
    "pitch_before_midi": 55,
    "pitch_after_midi": 67
  }
]
```

然后 ScoreIRBuilder 原样带到 ScoreNote 或 `analysis_info.note_traces`。

### P0：phrase 规则会修改音高/时值，但缺少和 F0 frame 的反校验

例如 octave jump correction、median smooth 属于“音乐上下文修复”，不是 F0 观测本身。现在它们靠本地邻居和阈值判断，方向合理，但生产上必须防止把真实大跳、装饰音、滑音目标音错误拉平。

建议：每个 pitch mutation 必须附带 F0 frame evidence 汇总：

- 原 candidate 覆盖 frame 数
- 原 pitch median/stddev
- 修改后 pitch 与 frame median 的偏差
- voiced ratio / confidence
- mutation confidence

如果修改后离 F0 median 太远，只标 uncertain，不应强修。

### P1：phrase 和 quantizer 都在处理短 gap，职责边界容易重叠

phrase 有：

- bridge short gaps
- sustain phrase gaps
- absorb short notes

quantizer 又会 snap onset/duration。结果可能是：phrase 先把时间连续性改了，quantizer 再改变网格位置，最终 MusicXML 中的 duration 跟 phrase action 解释不完全一致。

建议明确分工：

- phrase 只修 melodic event identity：合并/删除/音高修复/是否 sustain。
- quantizer 只修 notation timing：tick、measure、duration type。
- 如果 phrase 改 `end_time_sec`，QuantizedNoteSet 必须记录 `performance_end_time_sec` 和 `phrase_end_time_sec` 的来源。

### P1：`MelodyTranscriptionService` 有重复定义方法

同一文件中 `_has_authoritative_selected_melody` 定义了两次：

- `backend/app/services/melody_transcription_service.py:209`
- `backend/app/services/melody_transcription_service.py:230`

后者会覆盖前者。虽然当前行为不一定错，但这是明显维护风险：第一版要求“所有 note 都有 lineage”，第二版只要“存在一个 note 有 lineage”就返回 true，校验强度实际变弱了。

建议删除弱校验版本，保留严格版本；如果确实需要宽松检查，应改名为 `_has_any_authoritative_selected_melody_note`。

### P1：downbeat fallback 仍然在主链路中存在

`PitchPipeline.run` 中 downbeat tracking 失败会 fallback 到 beats：`backend/app/modules/pitch/pipeline.py:1365` 到 `backend/app/modules/pitch/pipeline.py:1379`。

这和项目的 No Silent Fallback Policy 有冲突风险。虽然它记录了 warning 和低 confidence，但后续依然会生成 quantized score。对 lead-vocal MVP 来说，如果 rhythm grid 是 required stage，就不应静默完成；至少要把 ScoreIR 标为 rhythm_grid_uncertain 并让 UI 明确提示。

### P2：selected_melody 的 phrase action 截断到 200 条

`PitchPipeline` 只保留前 200 条 action 到 `analysis_info`：`backend/app/modules/pitch/pipeline.py:1581`。

长音频上这会丢诊断。artifact 里完整 `selected_melody` 可能还在，但 summary 不完整。建议 summary 只放计数，完整 trace 放 artifact 并提供 artifact id/path。

## 当前链路判断

整体链路比早期 demo 型实现健康很多：

- required F0 不可用会失败；
- NoteCandidateSet / SelectedMelody / QuantizedNoteSet 都有 schema；
- ScoreIRBuilder 已经强制从 QuantizedNoteSet 生成；
- ScoreIR lineage 校验比较硬；
- phrase 后处理不是孤立逻辑，确实在主链路中生效。

但 phrase 段现在仍偏“算法内部修复”，还没有完全产品化为可审计 artifact。真正上线前，我建议优先做两件事：

1. 把 phrase action trace 按 note 贯穿到 QuantizedNoteSet 和 ScoreIR。
2. 修掉 `MelodyTranscriptionService._has_authoritative_selected_melody` 重复定义导致的校验降级。

这两件事比继续调 f0-candidate 更关键，因为 candidate 已经能产出，后面最怕的是“看起来谱对了，但不知道为什么对/哪里被修过”。
