# 当前 F0 -> Candidate 实现对比评审（2026-05-15）

## 结论

当前项目已经出现了非常明确的生产化提示：`RMVPEF0Extractor`、`NoteCandidateSet v2`、lineage 字段、选择/量化链路保留 candidate 来源、`ScoreIR` lineage warning。这说明代码正在朝正确方向走。

但一针见血地说：它还不是完整的生产 F0 -> candidate 主链路。现在更像是“旧 detector-note 主路 + 新 F0/candidate 契约侧挂 + 局部 lineage 贯通”。方向对，骨架有了，但权威链路还没切干净。

## 有价值的提示

### 1. F0 抽取开始独立成 stage

证据：`backend/app/modules/pitch/f0_extractor.py` 已有 `RMVPEF0Extractor`，并明确只输出 `F0Track`。

- `RMVPEF0Extractor` 定义在 `backend/app/modules/pitch/f0_extractor.py:15`。
- docstring 明确不做 note segmentation，不用 CREPE/basic-pitch fallback 掩盖 RMVPE 失败：`backend/app/modules/pitch/f0_extractor.py:16`。
- extractor 强制 `pitch_backend="rmvpe"`，清空 fallback：`backend/app/modules/pitch/f0_extractor.py:38`。
- 调用 `_build_rmvpe_model()` 和 `_predict_rmvpe_frames()`，再用 `_store_frame_artifacts()` 形成 F0 artifact：`backend/app/modules/pitch/f0_extractor.py:66`、`backend/app/modules/pitch/f0_extractor.py:77`、`backend/app/modules/pitch/f0_extractor.py:97`。
- 最终返回 typed `F0Track`：`backend/app/modules/pitch/f0_extractor.py:181`。

判断：这是正确方向，已经把“F0 是一等中间产物”落进代码了。

### 2. Candidate builder 已能从 F0 contour 生成 candidate

证据：`backend/app/modules/pitch/note_candidate_builder.py` 已经有 `note_candidate_set_v2`。

- `SCHEMA_VERSION = "note_candidate_set_v2"`：`backend/app/modules/pitch/note_candidate_builder.py:41`。
- `build()` 输入显式是 `f0_track + pitch_contours + raw_candidates`：`backend/app/modules/pitch/note_candidate_builder.py:47`。
- 先保留 raw notes，再遍历 normalized contours 生成 contour candidate：`backend/app/modules/pitch/note_candidate_builder.py:68`、`backend/app/modules/pitch/note_candidate_builder.py:72`。
- 输出里有 `lineage_contract`，要求 `candidate_id`、`source_contour_ids`、`source_f0_frame_range`：`backend/app/modules/pitch/note_candidate_builder.py:123`。
- contour-derived candidate 的稳定 ID 来自帧范围、起止时间、pitch center：`backend/app/modules/pitch/note_candidate_builder.py:633`。

判断：这是真进步。之前最大的问题是“raw note 为空则 contour 不能变 candidate”，现在 builder 层已经能独立从 contour 产出 candidate。

### 3. 后续链路开始保留来源

证据：项目里已有 `test_pitch_lineage_contract.py`，测试 candidate -> selected melody -> quantized notes 的 lineage 传播。

- 测试验证 `NoteCandidateSet` 是 v2：`backend/tests/test_pitch_lineage_contract.py:61`。
- 测试验证 selected note 保留 `source_candidate_id`、`source_candidate_ids`、`source_contour_ids`、`source_f0_frame_range`：`backend/tests/test_pitch_lineage_contract.py:68`。
- 测试验证 quantized note 继续保留同样 lineage：`backend/tests/test_pitch_lineage_contract.py:80`。

判断：这是产品化必须要的诊断闭环，值得保留并继续扩大。

### 4. ScoreIR 已经开始接 lineage，但只是 warning

证据：`ScoreIRBuilder` 先从 quantized artifact 构建，再 fallback 到 measures、analysis lead、raw。

- 优先 `_build_notes_from_quantized_artifact()`：`backend/app/modules/score_ir/builder.py:39`。
- 仍继续 fallback 到 measures、analysis lead、raw：`backend/app/modules/score_ir/builder.py:41`、`backend/app/modules/score_ir/builder.py:43`、`backend/app/modules/score_ir/builder.py:45`。
- lineage 校验目前只是 warning：`backend/app/modules/score_ir/builder.py:90`。
- warning 包括缺少 `source_candidate_id`、`source_candidate_ids`、`source_contour_ids`、`source_f0_frame_range`：`backend/app/modules/score_ir/builder.py:118`、`backend/app/modules/score_ir/builder.py:128`、`backend/app/modules/score_ir/builder.py:133`、`backend/app/modules/score_ir/builder.py:138`。

判断：这是“过渡保护”，不是生产硬约束。生产版必须让 lead vocal 主路没有 lineage 就失败，而不是 warning 后继续出谱。

## 仍然没有解决的关键问题

### 1. Pipeline 主路仍先跑 detector notes，而不是先跑 F0 candidate service

`PitchPipeline.run()` 现在仍然先调用 `_safe_detect_candidates()` 产出 `detected_notes`：`backend/app/modules/pitch/pipeline.py:667`。

之后才抽 `lead_f0_track`：`backend/app/modules/pitch/pipeline.py:773`。

这意味着主链路顺序仍然是：

```text
detector.detect -> detected_notes
              -> F0Track
              -> contour bridge 修补 detected_notes
              -> selector/quantizer
```

目标生产链路应该是：

```text
RMVPEF0Extractor -> F0Track
PitchContourBuilder -> PitchContourSet
NoteCandidateBuilder -> NoteCandidateSet
MelodySelection -> QuantizedNoteSet
ScoreIR
```

差别不是小细节，是权威事实源的问题。现在 `NoteCandidateBuilder` 在 service/payload 层能构建 candidate，但 `PitchPipeline` 真正给 selector 的仍是 `detected_notes` 经 bridge 后的 `Note` 列表。

### 2. `ContourToCandidateBridge` 还在主路上

pipeline 仍调用 `contour_candidate_bridge.bridge()`：`backend/app/modules/pitch/pipeline.py:790`，然后把 `detected_notes = contour_bridge_result.notes`：`backend/app/modules/pitch/pipeline.py:795`。

这说明“bridge”仍承担生产连接职责，而不是 legacy/shadow 对照职责。

生产上这不理想：bridge 的语义是修补旧世界，不是权威 candidate service。它会让系统继续混合 raw detector notes 与 contour-derived notes，导致 candidate provenance 复杂化。

### 3. `NoteCandidateBuilder` 输出还不是 pipeline 的唯一输入

`SemanticAudioResult` 里的 `melody_candidates` 仍由 `_build_candidate_set(notes=detected_notes, selected_notes=lead_notes)` 构建：`backend/app/modules/pitch/pipeline.py:868`。

这不是直接塞入 `NoteCandidateBuilder.build()` 的 v2 payload。换句话说，pipeline 内部的 `melody_candidates` 仍是从 `Note` list 包装出来的 candidate set，而不是权威 `NoteCandidateSet v2`。

结果是：

- service 层可以重新构造 `note_candidates.json`；
- pipeline 层 selector/quantizer 已经基于另一个 note 集合完成决策；
- 两者有机会不一致。

这就是典型“双事实源”。必须消灭。

### 4. F0 extractor 失败后仍允许复用 detector artifact

`_extract_lead_f0_track()` 捕获 extractor 异常后，如果 detector artifact 里已有 F0Track，会 warning 并返回 fallback_track：`backend/app/modules/pitch/pipeline.py:389`。

文档说这是兼容测试和旧调用，不是 CREPE/basic-pitch fallback。这个解释可以接受为迁移期策略，但生产语义上它仍然是 fallback 行为。

生产建议：

- `production_mode=True` 时 extractor 失败必须 hard fail；
- `legacy/test mode` 才允许 `detector_last_detection_artifact` 复用；
- warning 不足以保护产品质量。

### 5. `ScoreIRBuilder` 仍然允许 raw/measures fallback 建谱

`ScoreIRBuilder.build()` 在 quantized artifact 不存在时继续从 measures、analysis lead、raw notes 建谱：`backend/app/modules/score_ir/builder.py:39` 到 `backend/app/modules/score_ir/builder.py:45`。

这对兼容旧数据有用，但对生产 lead-vocal transcription 是危险的：它会让缺少 candidate lineage 的谱继续被输出，只留一个 warning。

生产主路应该要求：

```text
LeadVocalScoreRevision 必须由 QuantizedNoteSet v2 构建；
每个 ScoreNote 必须能追到 source_candidate_id 或 source_candidate_ids；
再往上追到 source_contour_ids 和 source_f0_frame_range。
```

### 6. Candidate 仍然偏“单一路径 note”，竞争模型不足

当前 builder 有 rejection reason、origin count、stable id，这些都好。但它仍然缺少真正的候选竞争结构：

- onset/offset uncertainty 不是核心字段；
- octave alternatives 不是候选模型的一等对象；
- segmentation alternatives 不够明确；
- candidate score/ranking 没有形成可解释的全局选择模型；
- reject 的 contour 还没有成为可诊断的产品级 false negative 分析入口。

这意味着它可以作为 MVP 的保守 note candidate，但还不能称为强生产 MIR candidate layer。

## 综合判断

### 是否有所提示？

有，而且提示很明显：当前项目已经在按重构方案推进，不是原地踏步。

最关键的正向信号是：

1. `RMVPEF0Extractor` 已经把 F0 抽取从 note segmentation 中拆出来。
2. `NoteCandidateBuilder` 已经能从 F0 contour 生成 candidate，并写入 lineage contract。
3. selected melody 和 quantized notes 已经开始保留 candidate/F0 lineage。
4. `ScoreIR` 已经有 lineage warning，准备从软约束过渡到硬约束。

### 是否已经可生产？

还不行。

核心原因只有一个：权威主路还没切换。现在新契约已经存在，但主 pipeline 仍然围绕 `detected_notes`、`ContourToCandidateBridge` 和 fallback builder 运转。

这会导致三个生产风险：

1. 产物可能看起来有 `note_candidates.json`，但 ScoreIR 实际不是从同一个权威 candidate set 来的。
2. F0 extractor 失败可能被 detector artifact 复用掩盖。
3. ScoreIR 可以在缺少完整 lineage 的情况下继续输出。

## 下一步最优解

不要继续小修 bridge。下一刀应该切权威主路。

建议按这个顺序做：

1. 新增或显式化 `NoteCandidateService`，唯一输入是 `F0Track + PitchContourSet`，输出唯一权威 `NoteCandidateSet v2`。
2. `PitchPipeline.run()` 在 lead vocal 路径中改为先 `RMVPEF0Extractor -> PitchContourBuilder -> NoteCandidateBuilder`，再把 `NoteCandidateSet v2` 交给 selector。
3. `ContourToCandidateBridge` 降级为 `legacy_bridge` 或 `shadow_compare`，不得再更新生产 `detected_notes`。
4. `MelodySelection` 输入改为 `NoteCandidateSet v2`，输出只引用 candidate，不再消费任意 `Note` list。
5. `QuantizedNoteSet v2` 成为 `ScoreIRBuilder` 的生产必需输入；缺失 lineage 在 production mode 下 hard fail。
6. `detector.detect()` 的 `_frames_to_notes()` 保留为 legacy/debug，不再参与 lead-vocal production main path。

最小可交付标准：一条 lead vocal 成功转谱后，任意一个 `ScoreNote` 都能追溯：

```text
ScoreNote
  -> quantized_note_id
  -> source_candidate_id/source_candidate_ids
  -> source_contour_ids
  -> source_f0_frame_range
  -> F0Track frames
```

做不到这条，就只能算“有生产化提示”，不能算“生产可用链路”。
