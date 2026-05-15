# Merge Conflict Resolution - develop/candidate-authority

日期：2026-05-15

## 处理目标

解决以下文件的 merge 冲突，同时保证 lead-vocal 主链不退回旧的 authority 语义：

- `backend/app/modules/pitch/pipeline.py`
- `backend/app/modules/pitch/quantizer.py`
- `backend/app/modules/score_ir/builder.py`
- `backend/app/services/audio_analysis_service.py`
- `backend/tests/test_audio_analysis_service.py`
- `backend/tests/test_pitch_pipeline.py`
- `backend/tests/test_score_ir_builder.py`

## 合并原则

本次冲突不能机械地偏向任意一边，因为两边改的是不同层级：

1. `develop/candidate-authority` 改的是 production authority 语义：
   - `NoteCandidateSet v2` 成为唯一权威候选输入。
   - `QuantizedNoteSet v2` 成为 `ScoreIRBuilder` 的 primary production input。
   - 旧的 `ScoreIR` 后置替换/注释路径要显式禁用。

2. 当前分支改的是 runtime 约束和落盘闭环：
   - machine revision state
   - revision artifact manifest
   - revision-scoped MIDI / MusicXML export
   - 若干额外 runtime 断言与测试覆盖

最终策略：

- `pipeline.py` / `quantizer.py` / `score_ir/builder.py` 以 `candidate-authority` 版本为主干。
- `audio_analysis_service.py` 保留当前分支的 machine revision / export / manifest 落盘闭环，但切换到 `candidate-authority` 的 legacy-path tripwire 语义。
- 测试文件合并双方有价值断言，删除互相矛盾的旧预期。

## 关键决策

### 1. Pitch pipeline

保留了 `candidate-authority` 的核心语义：

- 生产候选来自 `NoteCandidateSet v2`
- detector notes 仅作为 `optional_evidence`
- `ContourToCandidateBridge` 仅保留 shadow diagnostics
- `selected_melody` 与 `quantized_notes` 被写入 `semantic_audio.melody_candidates.analysis_info`

同时保留当前分支对 quantized measure payload 中 lineage 字段的显式落盘：

- `candidate_id`
- `source_candidate_id`
- `source_candidate_ids`
- `source_contour_ids`
- `source_f0_frame_range`

### 2. Quantizer

选择了 `candidate-authority` 分支的实现，因为它对 merge / trim / overlap 的 lineage 保留更系统。

保留结果：

- same-pitch merge 不丢 source candidate lineage
- overlap trim 不丢 lineage
- merged notes 可保留 union lineage 和 merged frame range

### 3. ScoreIRBuilder

以 `candidate-authority` 版本为主：

- authoritative 路径从 `semantic_audio.melody_candidates.analysis_info.quantized_notes` 读 primary quantized payload
- 缺失 primary quantized payload 直接 hard fail
- authoritative path 上继续保留 strict lineage contract

另外补了一个兼容点：

- `build(..., quantized_notes_artifact=...)` 参数仍保留，避免上层 `ScoreBuildService` 调用断开
- 但该参数不再改变 primary authority，只用于兼容 metadata 补充

### 4. AudioAnalysisService

保留当前分支的：

- `MachineScoreRevisionState`
- `artifact_manifest.json`
- revision-scoped MIDI / MusicXML export
- file-backed machine revision落盘

切换为 `candidate-authority` 兼容语义的部分：

- `_replace_lead_notes_from_quantized_artifact()` 显式禁用
- `_annotate_score_ir_notes()` 显式禁用
- perception stage 不再调用旧的 `score_ir` 后置注释路径

但保留当前分支对 `ScoreIR` 与 `QuantizedNoteSet` 一致性的 runtime 校验：

- `required QuantizedNoteSet is unavailable for score_ir build`
- `score_ir quantized note count mismatch`
- `score_ir missing required QuantizedNoteSet lineage`

## 验证

执行：

```powershell
.\.venv310\Scripts\python.exe -m pytest tests\test_pitch_pipeline.py tests\test_quantizer.py tests\test_score_ir_builder.py tests\test_audio_analysis_service.py -q
```

结果：

- `52 passed`

说明：

1. 冲突文件已恢复到可运行状态。
2. `candidate-authority` 主语义没有被当前分支旧逻辑冲掉。
3. 当前分支的 machine revision / export / manifest 测试覆盖没有被破坏。

## 结论

本次冲突已经按 production authority 优先原则合并完成：

- lead-vocal 生产主链继续以 `NoteCandidateSet v2 -> QuantizedNoteSet v2 -> ScoreIR` 为唯一主路径；
- 旧的 `ScoreIR` 后置替换/注释路径不再允许回流；
- revision/export/manifest 的文件态闭环保留。

