# ScoreIR Quantized Primary Input Review (2026-05-15)

## 结论

这次推进方向是对的，而且比上一版更接近生产：`ScoreIRBuilder` 已经把 `QuantizedNoteSet` 放到主入口，`AudioAnalysisService` 也开始对 `ScoreNote` 的 `quantized_note_id/source_candidate_id/source_candidate_ids/source_contour_ids/source_f0_frame_range` 做硬校验。

但当前仍不能宣布“完整收口”。最危险的问题不在 `ScoreIRBuilder`，而在上游 `NoteQuantizer._preprocess_notes()`：默认启用的 merge/overlap 逻辑会重新构造 `Note`，但没有复制 candidate/contour/F0 lineage，导致进入 `QuantizedNoteSet` 前就把链路打断。

一句话判断：ScoreIR 入口这刀是正确的，但 quantizer lineage preservation 还有 P1 级破口，必须先补。

## 已经做对的部分

### 1. ScoreIRBuilder 现在优先消费 QuantizedNoteSet

- `ScoreIRBuilder.build()` 新增 `quantized_notes_artifact` 参数：`backend/app/modules/score_ir/builder.py:35`。
- 构建顺序优先 `_build_notes_from_quantized_artifact()`：`backend/app/modules/score_ir/builder.py:39`。
- 有 quantized artifact 时，meta 写入 `lead_note_source="quantized_notes"`、`timing_origin`、`quantizer_backend`、`quantized_note_count`：`backend/app/modules/score_ir/builder.py:61`。
- `_build_notes_from_quantized_artifact()` 生成的 `ScoreNote` 会带 `source_candidate_id/source_candidate_ids/source_contour_ids/source_f0_frame_range/quantized_note_id`：`backend/app/modules/score_ir/builder.py:204` 到 `backend/app/modules/score_ir/builder.py:235`。

判断：这是正确收口方向。之前“先 build 再替换”的服务层补丁味道很重，现在 builder 主入口更干净。

### 2. AudioAnalysisService 已经有生产硬校验

- `_validate_score_ir_uses_quantized_notes()` 在缺 `QuantizedNoteSet` 时 hard fail：`backend/app/services/audio_analysis_service.py:410`。
- 空 notes hard fail：`backend/app/services/audio_analysis_service.py:413`。
- ScoreIR note 数与 QuantizedNoteSet note 数不一致 hard fail：`backend/app/services/audio_analysis_service.py:418`。
- 缺 `source_candidate_id/source_candidate_ids/source_contour_ids/source_f0_frame_range/quantized_note_id` hard fail：`backend/app/services/audio_analysis_service.py:422`。

判断：这是生产需要的，不再只是 warning。这个方向必须保留。

### 3. serializer 和 score_data 已扩展 lineage 字段

- `ScoreNote` 类型有 `source_candidate_id/source_candidate_ids/source_contour_ids/source_f0_frame_range/quantized_note_id`：`backend/app/modules/score_ir/types.py:40`。
- `ScoreIRSerializer.to_score_data()` 把这些字段写入前端/export-facing score data：`backend/app/modules/score_ir/serializer.py:87`。

判断：前端和导出层终于有机会展示/诊断 lineage，这是产品化必要条件。

## 当前最大问题

### P1：Quantizer merge/overlap 会丢 lineage

默认配置里：

- `quantize_merge_same_pitch_enabled=True`：`backend/app/modules/pitch/config.py:60`。
- `quantize_overlap_resolution_enabled=True`：`backend/app/modules/pitch/config.py:65`。

但 `NoteQuantizer._preprocess_notes()` 在合并相邻音符时重新构造 `Note`，只保留 pitch/time/confidence/reason_codes：`backend/app/modules/pitch/quantizer.py:107` 到 `backend/app/modules/pitch/quantizer.py:116`。

重叠处理也重新构造 `Note`，同样只保留 pitch/time/confidence/reason_codes：`backend/app/modules/pitch/quantizer.py:157` 到 `backend/app/modules/pitch/quantizer.py:172`。

这会直接清空：

- `candidate_id`
- `source_candidate_id`
- `source_candidate_ids`
- `source_contour_ids`
- `source_f0_frame_range`
- `candidate_origin`
- `contour_bridge_evidence`
- `segmentation_evidence`

我用最小样例复现：两个带完整 lineage 的相邻 `C4` 被 merge 后，输出 `QuantizedNote` 的 lineage 变成：

```text
source_candidate_id=None
source_candidate_ids=[]
source_contour_ids=[]
source_f0_frame_range={}
```

因此当前链路在真实音乐里一旦触发 merge/overlap，就会在进入 ScoreIR 前断链。`AudioAnalysisService` 的 hard fail 会拦住一部分，但这意味着生产任务会因为量化预处理丢字段而失败，不是因为 F0/candidate 不存在。

## 次级问题

### 1. 旧替换路径还存在

`AudioAnalysisService._replace_lead_notes_from_quantized_artifact()` 仍保留：`backend/app/services/audio_analysis_service.py:435`。

即使当前主 build 已经能直接传 `quantized_notes_artifact`，这段旧路径仍会制造认知负担。下一步应删除或明确只给旧 builder 兼容测试使用，不能再是生产路径。

### 2. ScoreIRBuilder 仍保留 fallback build 顺序

`ScoreIRBuilder.build()` 在 quantized artifact 没产生 notes 时，仍 fallback 到 measures、analysis lead、raw：`backend/app/modules/score_ir/builder.py:40` 到 `backend/app/modules/score_ir/builder.py:45`。

服务层 hard validation 可以挡住 production 调用，但 builder 本身仍是兼容型 builder，不是纯 production builder。建议后续增加显式 `require_quantized_notes=True` 或拆出 `LeadVocalScoreBuildService`，避免未来调用方绕过 service。

### 3. lineage warning 还在 builder 内部保留

`_production_lineage_warnings()` 仍存在：`backend/app/modules/score_ir/builder.py:102`。

这不是错，但语义要清楚：warning 只适合 legacy/debug，production 应由 `_validate_score_ir_uses_quantized_notes()` 或 builder hard mode 失败。

## 建议立即修复

### 1. 给 quantizer 增加 lineage-preserving clone/merge helper

不要在 merge/overlap 里直接 `Note(...)` 裸构造。应集中做一个 helper，例如：

```text
_clone_note_with_timing(note, start_time, end_time, reason_codes)
_merge_note_lineage(prev, note)
```

合并两个 note 时：

- `source_candidate_id` 可保留主 pitch/confidence 的候选；
- `source_candidate_ids` 必须取并集；
- `source_contour_ids` 必须取并集；
- `source_f0_frame_range` 应合并为 min start frame、max end frame；
- `candidate_id` 若合并多个候选，不应伪装成单一原 candidate，可置空或生成 `merged_candidate_id`，但 `source_candidate_ids` 必须完整；
- `reason_codes` 追加 `quantizer_merged_same_pitch` 或等价 reason code。

裁剪 overlap 时：

- 不得清空 lineage；
- `source_f0_frame_range` 如果无法精确裁剪，至少保留原 range，并加 `quantizer_trimmed_overlap` reason code；
- 后续再做 frame-level 精确裁剪。

### 2. 增加 quantizer lineage regression tests

必须新增两类测试：

1. merge same pitch 后 `source_candidate_ids/source_contour_ids/source_f0_frame_range` 仍存在并合并。
2. overlap resolution 后被裁剪 note 仍保留 lineage。

当前 `test_pitch_lineage_contract.py` 只覆盖无 merge/overlap 的直通路径，不足以证明生产稳定。

### 3. 删除或隔离 `_replace_lead_notes_from_quantized_artifact()`

如果还需要兼容旧 builder，就加明确命名和调用条件，例如：

```text
_legacy_replace_lead_notes_from_quantized_artifact_for_old_builder_only
```

并保证 production path 不会走它。

## 最终判断

这次更新是明显进步：ScoreIR 主旋律入口开始真正依赖 `QuantizedNoteSet`，并且服务层已经有 hard fail。

但现在不能停。下一刀必须修 quantizer lineage 丢失，否则会出现很尴尬的局面：上游 candidate 是对的，ScoreIR builder 也是对的，最终却在量化合并/裁剪环节把证据链弄断。

生产验收标准应改成：

```text
NoteCandidateSet v2
  -> MelodySelection v2
  -> QuantizedNoteSet v2, including merge/overlap cases
  -> ScoreIR
  -> score_data
```

每一步都必须保留：

```text
source_candidate_id or source_candidate_ids
source_contour_ids
source_f0_frame_range
quantized_note_id after quantization
```

当前状态：ScoreIR 收口完成一半；quantizer lineage preservation 必须马上补。
