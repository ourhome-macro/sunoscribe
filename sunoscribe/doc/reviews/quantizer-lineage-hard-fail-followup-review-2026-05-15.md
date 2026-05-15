# Quantizer Lineage Hard-Fail Follow-up Review (2026-05-15)

## 结论

这刀有效。之前指出的 P1 断链点已经被堵住：`NoteQuantizer` 在 same-pitch merge 和 overlap trim 时不再裸构造 `Note`，而是保留并合并 candidate/contour/F0 lineage；`ScoreIRBuilder` 也从 warning 升级到 production lineage hard fail。

当前判断：这一刀可以算完成 P1 修复，ScoreIR 主旋律链路已经更接近生产可用。但仍不等于整个 F0 -> candidate 主链路完成，因为 pipeline 上游仍有 legacy detector/bridge 双事实源问题。

## 已验证的修复

### 1. merge 保链生效

`NoteQuantizer._preprocess_notes()` 在可合并相邻音符时调用 `_merged_note()`：`backend/app/modules/pitch/quantizer.py:106`。

`_merged_note()` 保留并合并：

- primary `source_candidate_id`：`backend/app/modules/pitch/quantizer.py:128`
- `source_candidate_ids` ordered union：`backend/app/modules/pitch/quantizer.py:132`
- `source_contour_ids` ordered union：`backend/app/modules/pitch/quantizer.py:133`
- `source_f0_frame_range` merged range：`backend/app/modules/pitch/quantizer.py:137`
- evidence fields：`backend/app/modules/pitch/quantizer.py:139` 到 `backend/app/modules/pitch/quantizer.py:144`

我复跑之前的最小复现：两个带完整 lineage 的相邻 `C4` 合并后输出为：

```text
source_candidate_id=cand_a
source_candidate_ids=['cand_a', 'cand_b']
source_contour_ids=['pc_a', 'pc_b']
source_f0_frame_range={'start_frame_index': 0, 'end_frame_index': 50}
```

这说明原 P1 断链已经消除。

### 2. overlap trim 保链生效

`_resolve_overlaps()` 不再裸构造 `Note`，而是调用 `_trimmed_note()`：`backend/app/modules/pitch/quantizer.py:198`、`backend/app/modules/pitch/quantizer.py:201`。

`_trimmed_note()` 改 timing，但保留：

- `candidate_id/source_candidate_id/source_candidate_ids`
- `source_contour_ids`
- `source_f0_frame_range`
- `candidate_origin`
- bridge/segmentation evidence

对应代码在 `backend/app/modules/pitch/quantizer.py:147` 到 `backend/app/modules/pitch/quantizer.py:165`。

判断：trim 语义是“时间裁剪，证据保留”。这对 MVP 是合理的；未来如果要更精确，可按 F0 frame 重新裁剪 range，但不是当前 P1。

### 3. F0 range 合并策略可接受

`_merged_f0_frame_range()` 对 start fields 取 min、end fields 取 max：`backend/app/modules/pitch/quantizer.py:278` 到 `backend/app/modules/pitch/quantizer.py:303`。

当前支持：

- `start_frame_index`
- `end_frame_index`
- `start_time_sec`
- `end_time_sec`
- `start_time`
- `end_time`

判断：生产 MVP 可接受。它保守地覆盖合并后音符来源范围，不会断链。

### 4. ScoreIR hard fail 生效

`ScoreIRBuilder._production_lineage_warnings()` 已实际变成 hard fail：`backend/app/modules/score_ir/builder.py:102`。

触发条件包括：

- `lead_note_source == "quantized_notes"`
- `lead_selection_authoritative`
- notes 中存在 `source == "quantized_notes"`

见 `backend/app/modules/score_ir/builder.py:108` 到 `backend/app/modules/score_ir/builder.py:112`。

失败时抛：

```text
score_ir_lineage_contract_failed:...
```

见 `backend/app/modules/score_ir/builder.py:141`。

测试已覆盖 authoritative empty selection 和 missing source candidate hard fail：`backend/tests/test_score_ir_builder.py:40`、`backend/tests/test_score_ir_builder.py:317`。

### 5. 旧替换旁路已禁用

`AudioAnalysisService._replace_lead_notes_from_quantized_artifact()` 已改为 legacy-disabled 入口，直接抛错提示 production 必须直接从 `QuantizedNoteSet` build：`backend/app/services/audio_analysis_service.py:434` 到 `backend/app/services/audio_analysis_service.py:442`。

判断：这消除了“先 build 再替换”的隐性旁路，方向正确。

## 本地验证

我运行了两类验证。

### 最小复现

之前失败的 merge lineage case 已通过：

```text
count 1
cand_a ['cand_a', 'cand_b'] ['pc_a', 'pc_b'] {'start_frame_index': 0, 'end_frame_index': 50}
```

### 单元测试

已通过：

```text
python -m unittest backend.tests.test_quantizer backend.tests.test_score_ir_builder
Ran 16 tests in 0.037s
OK
```

补充通过：

```text
python -m unittest backend.tests.test_pitch_lineage_contract backend.tests.test_pitch_pipeline backend.tests.test_rmvpe_f0_extractor backend.tests.test_note_candidate_builder backend.tests.test_melody_selection_artifact backend.tests.test_quantized_notes_artifact
Ran 58 tests in 0.088s
OK
```

## 剩余风险

### 1. pipeline 上游仍未完全切换权威 candidate 主路

本刀解决的是 `QuantizedNoteSet -> ScoreIR` 与 quantizer 断链。它没有解决更上游的问题：`PitchPipeline` 仍存在 detector notes、contour bridge、candidate builder 多事实源共存的迁移状态。

所以当前不能说整个 F0 -> candidate -> ScoreIR 生产链路已完成，只能说后半段证据链更稳了。

### 2. merge reason code 未显式追加

`_merged_note()` 合并 reason_codes，但没有强制追加类似 `quantizer_merged_same_pitch` 的 reason code。

这不是 blocker，但从诊断角度建议补：未来看到一个 ScoreNote 有多个 `source_candidate_ids` 时，应该能明确知道它是量化合并产生，而不是上游 selector 合并产生。

### 3. trim range 仍是保守保留，不是 frame-level 精裁

`_trimmed_note()` 保留原 `source_f0_frame_range`。这比清空好得多，但在细粒度诊断时会显示比实际裁剪后更宽的 F0 证据范围。

MVP 可接受；高精度版本应按 trim 后 start/end time 重算 frame range。

## 下一步建议

下一刀不要再在 ScoreIR 后半段打补丁，应回到上游权威事实源：

1. 让 `PitchPipeline` 直接产出并消费 `NoteCandidateSet v2`。
2. `MelodySelection` 输入只接受 `NoteCandidateSet v2`，不再接受任意 `Note` list。
3. `ContourToCandidateBridge` 降级为 legacy/shadow compare，不能再改生产 `detected_notes`。
4. 为“raw detector notes 为空但 F0 contour 有效”增加端到端 pipeline 测试，证明不依赖 bridge 也能完成 candidate -> selection -> quantized -> ScoreIR。

## 最终判断

P1 断链已修。ScoreIR hard fail 已落地。旧替换旁路已禁用。

当前最短板已经从 `QuantizedNoteSet -> ScoreIR` 转移到 `F0/contour -> NoteCandidateSet -> MelodySelection` 的权威主路切换。
