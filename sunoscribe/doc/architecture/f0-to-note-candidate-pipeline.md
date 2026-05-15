# F0 到 NoteCandidate 流水线生产评审

## 目的

这份文档只回答一件事：当前 `F0 -> candidate -> selected melody -> quantized notes` 链路为什么在生产上不稳，以及应该收敛到什么架构。

结论先说：现在的实现不是一个清晰的 typed MIR 链路，而是“检测结果、桥接结果、预选结果、二次选择结果、二次量化结果”混在一起。它能出结果，但不适合作为生产事实源。

## 当前链路真实形态

当前真实链路不是文档里理想化的 `F0Track -> PitchContourSet -> NoteCandidateSet -> RhythmGrid -> ScoreRevision`，而是下面这条：

```text
RMVPE frames
  -> detector notes
  -> contour bridge（仅在 raw candidates 非空时运行）
  -> arrangement arbitration
  -> pipeline MelodySelector
  -> pipeline NoteQuantizer
  -> semantic_audio.melody_candidates { notes, selected_notes }
  -> MelodyTranscriptionService 二次组装 note_candidates.json
  -> RuleBasedMelodySelector 二次选择 selected_melody.json
  -> QuantizedNotesArtifactBuilder 二次量化 quantized_notes.json
  -> ScoreIR 用 quantized_notes 回填
  -> ScoreRevision
```

对应事实：

- `PitchPipeline` 先从 lead 音频拿 detector notes，再把 `F0Track` 组装成 `pitch_contours`，然后跑一次 `ContourToCandidateBridge`。
- bridge 后的结果先经过 `MelodySourceArbitrator` 和 `MelodySelector`，形成 pipeline 内部的 `lead_notes`。
- `semantic_audio.melody_candidates` 同时保存 `notes` 和 `selected_notes`，语义已经开始叠层。
- `MelodyTranscriptionService` 再把这些内容写成 `note_candidates.json`，随后重新跑 `RuleBasedMelodySelector` 产出 `selected_melody.json`。
- `QuantizedNotesArtifactBuilder` 再对 `selected_melody.json` 做一次独立量化，产出 `quantized_notes.json`。
- `AudioAnalysisService` 最终不是直接信 pipeline 的 measures，而是优先用 `quantized_notes.json` 回填 `ScoreIR` note 列表。

一句话：现在生产事实源不是单一 stage 输出，而是“前半条链路先选一遍，后半条链路再选一遍、再量化一遍”。

## 主要生产风险

### 1. 语义边界混乱

当前至少有五种“像 note 的东西”：

- RMVPE frame/F0 evidence
- detector raw notes
- contour bridge 补出的 notes
- pipeline 内部 selected lead notes
- artifact 层 selected melody / quantized notes

这些对象名字接近，但契约不同，最终谁是 authoritative source 并不清楚。结果是：

- 调试时很难回答“到底是哪个 stage 丢了 note”；
- 下游容易把候选当最终结果；
- `note_candidates.json` 同时承载 raw 与 preselected，已经不是单纯的 `NoteCandidateSet`。

### 2. 失败原因被吞噬

当前链路会在多个 stage 改写、过滤、合并 note，但很多失败不会以 stage-fatal 的方式暴露，只会表现成：

- selected 变少；
- quantized 变少；
- ScoreIR 被回填成另一套 notes；
- warnings 留下，但事实源已经变了。

这会直接破坏生产诊断：你看到的是“结果不好”，看不到“坏在 detector、bridge、selector 还是 quantizer”。

### 3. contour bridge 不能救 raw 空

这是当前实现里最致命的事实之一。

`ContourToCandidateBridge.bridge(...)` 和 `RuleBasedMelodySelector._bridge_from_contours(...)` 都要求 raw candidates 存在；一旦 detector raw notes 为空，bridge 直接失效。也就是说：

- F0 明明有 voiced contour；
- contour 也明明存在；
- 但 raw 空时，bridge 不会把 contour 提升成正式 candidate。

所以它不是 `F0 -> NoteCandidate` 的正式 builder，只是“对已有 raw candidates 的保守补丁”。这不满足生产 required stage 的语义。

### 4. candidate ID 不稳定

当前 candidate ID 来源混乱：

- detector 结果可能自带 `candidate_id`，也可能没有；
- contour bridge 会临时生成 `contour_bridge:*`；
- selector 归一化时会退化成按序号生成 `cand_00001`；
- quantized notes 又会重新生成 `qn_00001`，同时 `source_candidate_id` 可能来自不同层。

结果是：

- 同一段音符跨 stage 无法稳定追踪；
- patch、诊断、benchmark gap attribution 都会失去锚点；
- “这颗 note 为什么被删了/改了”很难稳定回答。

生产里没有稳定 ID，就没有可审计链路。

### 5. 双 selector / quantizer 分叉

现在实际上有两套选择与量化逻辑并行存在：

- pipeline 内：`MelodySelector` + `NoteQuantizer`
- artifact 层：`RuleBasedMelodySelector` + `QuantizedNotesArtifactBuilder`

这会导致三个问题：

- 同一输入可能得到两套不一致结果；
- 文档说的是一条链，代码跑的是两条链；
- `ScoreRevision` 最终吃的是后半条链，前半条链更像中间试运行结果。

这不是冗余保护，而是事实源分叉。

## 目标链路

目标必须收敛成单链路、单事实源、typed artifact 明确分层：

```text
F0Track
  -> PitchContourSet
  -> NoteCandidateSet
  -> SelectedMelody
  -> RhythmGrid / QuantizedNotes
  -> ScoreRevision
```

边界必须固定：

- `F0Track`：只保存 frames、voiced/unvoiced、confidence、vocal activity，不产出 note 结论。
- `PitchContourSet`：只表达 contour 与分段证据，不做最终 note 选择。
- `NoteCandidateSet`：只表达候选 note 与候选失败原因，不混入最终 selected 结果。
- `SelectedMelody`：唯一 selector 输出，负责“从 candidates 里选谁进入单旋律事实线”。
- `RhythmGrid`：独立节奏表示，不是 pitch side effect。
- `QuantizedNotes`：唯一 quantizer 输出，消费 `SelectedMelody + RhythmGrid`。
- `ScoreRevision`：只消费 `QuantizedNotes` 或等价 `ScoreIR` build input，不再回头吃别的 note 版本。

一句话：上游负责提供证据，中游负责做选择，下游负责量化与建谱；不要一边建谱，一边回头重选。

## 新 `NoteCandidateBuilder` 契约

`NoteCandidateBuilder` 应该替代“detector notes + contour bridge + note_candidates payload 拼装”的松散组合，成为唯一的 `PitchContourSet -> NoteCandidateSet` builder。

### 输入契约

输入最少应包含：

- `f0_track_id`
- `pitch_contour_set_id`
- `frames[]`
  - `frame_id`
  - `time_sec`
  - `f0_hz`
  - `pitch_midi`
  - `voiced`
  - `confidence`
- `contours[]`
  - `contour_id`
  - `start_time_sec`
  - `end_time_sec`
  - `duration_sec`
  - `pitch_center_midi`
  - `voiced_ratio`
  - `stability`
  - `has_vibrato`
  - `has_glide`
  - `frame_span`
  - `reason_codes`
- `vocal_activity[]`
  - `segment_id`
  - `start_time_sec`
  - `end_time_sec`
  - `state`
  - `voiced_ratio`
  - `mean_confidence`
- 可选 `detector_observations[]`
  - 仅作为外部 evidence，不再作为 candidate 的唯一来源门槛

关键要求：builder 必须能在 raw detector 为空时，仍依据 contour 生成候选或显式失败，不能把 raw 当成唯一入口。

### 输出契约

输出固定为单一 `NoteCandidateSet`：

- `note_candidate_set_id`
- `version`
- `source_f0_track_id`
- `source_pitch_contour_set_id`
- `candidates[]`
  - `candidate_id`
  - `start_time_sec`
  - `end_time_sec`
  - `duration_sec`
  - `pitch_center_midi`
  - `pitch_name`
  - `confidence`
  - `voiced_ratio`
  - `stability`
  - `candidate_origin`
  - `source_contour_ids[]`
  - `source_frame_ids[]`
  - `source_detector_note_ids[]`
  - `reason_codes[]`
  - `evidence`
- `rejected_candidates[]`
  - `candidate_id`
  - `reason_codes[]`
  - `evidence`
- `summary`
  - `candidate_count`
  - `accepted_count`
  - `rejected_count`
  - `reason_code_counts`
  - `builder_backend`
  - `builder_version`

严格要求：`NoteCandidateSet` 不再包含 `selected_notes`。那是 `SelectedMelody` 的职责，不是 candidate builder 的职责。

### 稳定 ID 规则

`candidate_id` 必须稳定、可重复生成、与枚举顺序无关。建议基于语义主键生成，例如：

```text
nc:{source_contour_id}:{start_ms}:{end_ms}:{pitch_cent_midi}
```

最低要求：

- 同一输入重复跑，ID 不变；
- 仅因列表顺序变化，ID 不变；
- selector、quantizer、patch、diagnosis 都沿用这个 ID 作为上游锚点；
- 新生成的 `quantized_note_id` 可以变化，但必须保存 `source_candidate_id`。

### `reason_codes` 规则

`reason_codes` 不能再只是零散 warning 标签，必须区分层级：

- builder accept reasons：为什么这个 contour 成为了 candidate
- builder reject reasons：为什么这个 contour 没成为 candidate
- diagnostic flags：这个 candidate 有什么风险但仍被保留

建议至少覆盖：

- `low_confidence`
- `low_voiced_ratio`
- `too_short`
- `too_unstable`
- `outside_vocal_range`
- `no_vocal_activity_support`
- `octave_outlier_corrected`
- `derived_from_detector_note`
- `derived_from_contour_only`
- `contour_split_segment`
- `missing_local_context`
- `overlaps_existing_candidate`
- `raw_detector_empty`

核心原则：`reason_codes` 不是给人看热闹的字符串，而是 stage contract 的 machine-readable 失败语义。

### 诊断 `evidence` 规则

每个 candidate 必须带最小可审计 evidence：

- `source_contour_ids[]`
- `source_frame_range`
- `source_detector_note_ids[]`
- `raw_overlap_duration_sec`
- `nearest_gap`
- `left_context_candidate_id`
- `right_context_candidate_id`
- `vocal_activity_overlap_ratio`
- `octave_correction`
- `segmentation_evidence`
- `decision_trace`
  - `accepted_by`
  - `rejected_by`
  - `applied_rules[]`

要求很简单：任何一个 candidate 被接受、拒绝、修正，都必须能回溯到哪段 contour、哪批 frame、哪条规则。

## 迁移策略

迁移不要大爆炸，按四步走。

### 第一步：冻结语义边界

先在架构上明确：

- `note_candidates.json` 只存 candidates，不再混入 `selected_notes`
- `selected_melody.json` 成为唯一 selector 输出
- `quantized_notes.json` 成为唯一 quantizer 输出
- `ScoreRevision` 只认 `quantized_notes.json` 对应的单一链路

这一步先改 contract，不求一次改完所有内部实现。

### 第二步：引入新 `NoteCandidateBuilder`

把现在散落在：

- detector raw notes
- contour bridge
- note_candidates payload 组装

中的 candidate 生成职责收拢到一个 builder。

要求：

- 能从 `PitchContourSet` 独立生成候选；
- raw detector 只作为 evidence，不再作为 bridge 是否可运行的门槛；
- 输出稳定 ID、rejected candidates、reason counts、diagnostic evidence。

### 第三步：删除双 selector / quantizer 分叉

收敛到唯一链路：

- 一个 selector
- 一个 quantizer
- 一套 authoritative artifacts

任何旧链路如果还保留，只能作为 debug 对照，不得再回写生产 `ScoreIR`。

### 第四步：以 artifact lineage 验收

验收标准不是“看起来音更多了”，而是：

- 每个 stage 输入输出清楚；
- 失败能定位；
- 同一 candidate 能跨 stage 稳定追踪；
- `ScoreRevision` 可明确追溯到 `QuantizedNotes -> SelectedMelody -> NoteCandidateSet -> PitchContourSet -> F0Track`。

## 验收测试

必须补的是生产验收测试，不是 demo happy path。

### 1. raw 空但 contour 有效

输入：detector raw notes 为空，但 `F0Track` / `PitchContourSet` 有稳定 voiced contour。

期望：

- `NoteCandidateBuilder` 仍可生成 `derived_from_contour_only` candidates，或显式失败并给出 `raw_detector_empty` + 具体原因；
- 不能出现“contour 在，candidate 空，但流程继续成功”。

### 2. 稳定 ID 回归

同一输入重复执行两次。

期望：

- `candidate_id` 集合完全一致；
- 顺序变化不影响 ID；
- `SelectedMelody.source_candidate_id`、`QuantizedNotes.source_candidate_id` 稳定可追踪。

### 3. selector 单事实源

输入固定样本，分别关闭旧链路与新链路对照。

期望：

- 生产结果只来自唯一 `SelectedMelody`；
- 不再出现 pipeline selector 与 artifact selector 各选一套 note。

### 4. quantizer 单事实源

输入固定 `SelectedMelody + RhythmGrid`。

期望：

- `QuantizedNotes` 是唯一量化输出；
- `ScoreIR` 不再混用 pipeline measures 与 artifact quantized notes。

### 5. 失败显式化

构造以下失败：

- F0 空
- contour 空
- candidate 全拒绝
- rhythm grid 缺失

期望：

- 每个 stage 都有明确 failure code；
- 不允许只靠 warnings 吞掉；
- 不允许生成看似成功的 `ScoreRevision`。

### 6. evidence 完整性

随机抽取 accepted / rejected candidates。

期望：

- 每条都能看到 `source_contour_ids`、`reason_codes`、`evidence.decision_trace`；
- gap attribution 与 debug package 不再依赖猜测匹配。

## 最终判断

当前实现的根问题不是模型不够强，而是 stage contract 没收紧。

只要 `NoteCandidateSet` 还同时混着 raw、bridge、preselected，且 selector / quantizer 还双轨并行，F0 到乐谱的链路就不可审计、不可稳定回归、不可放心上生产。

下一步最优解不是继续 patch bridge 阈值，而是先把 `F0Track -> PitchContourSet -> NoteCandidateSet -> SelectedMelody -> RhythmGrid/QuantizedNotes -> ScoreRevision` 这条 typed 主链立起来。
