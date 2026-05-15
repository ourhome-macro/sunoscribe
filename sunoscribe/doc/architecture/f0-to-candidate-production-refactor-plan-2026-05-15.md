# F0 -> Candidate 生产化重构方案（2026-05-15）

## 0. 结论

当前 `F0 -> candidate` 链路不能继续靠 `ContourToCandidateBridge`、`MelodySelector`、后置 artifact builder 叠补丁。正确的生产化路线是把它改成一条单一事实源的 typed MIR pipeline：

```text
vocals.wav
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet
  -> MelodySelection
  -> RhythmGrid
  -> QuantizedNoteSet
  -> LeadVocalScoreRevision
```

其中：

- `F0Track` 是 RMVPE 的唯一生产输出；
- `NoteCandidateSet` 是未量化旋律候选的唯一生产事实源；
- `MelodySelection` 只能引用 `candidate_id`，不能凭空发明 note；
- `QuantizedNoteSet` 只能引用 `selected_candidate_id`；
- `ScoreIR/ScoreRevision` 只能从 `QuantizedNoteSet` 构建；
- 任意最终 `ScoreNote` 必须能反查到 `F0Track` frame range。

这份方案的目标不是“让当前 demo 更顺”，而是把它改成可上线、可诊断、可回归测试、可被 agent 安全编辑的生产代码。

## 1. 当前代码问题定位

### 1.1 真实链路

当前主链路是：

```text
PitchDetector.detect()
  -> RMVPE raw frames
  -> PitchDetector._frames_to_notes()
  -> detector raw Note[]
  -> PitchPipeline._build_f0_track()
  -> PitchContourBuilder.build()
  -> ContourToCandidateBridge.bridge(raw Note[] + contours)
  -> MelodySourceArbitrator
  -> MelodySelector
  -> NoteQuantizer
  -> PitchAnalysisResult / semantic_audio
  -> MelodyTranscriptionService 再组装 note_candidates.json
  -> RuleBasedMelodySelector 再选 selected_melody.json
  -> QuantizedNotesArtifactBuilder 再量化 quantized_notes.json
  -> AudioAnalysisService 用 quantized_notes 回填 ScoreIR
```

### 1.2 根因

根因不是某个阈值差，而是 stage ownership 错了：

- `PitchDetector` 同时负责 F0 extraction 和 note segmentation；
- `ContourToCandidateBridge` 是补丁，不是 candidate builder；
- `NoteCandidateBuilder` 在服务层事后重建 artifact，不是主流程的权威 stage；
- `ScoreIRBuilder` 允许从 measures/lead/raw notes fallback 建谱；
- candidate ID、selected note ID、quantized note ID 之间没有强制可追溯契约。

## 2. 目标架构

### 2.1 新服务边界

#### `F0ExtractionService`

职责：

- 输入：`vocals.wav` 或目标 lead audio stem；
- 调用 RMVPE；
- 输出：`F0Track`；
- 只做 frame 级别处理：time、f0、midi_float、confidence、voiced、backend metadata；
- 不输出 `Note`；
- 不做 note merge、pitch rounding、duration filtering。

禁止：

- 不得调用 `_frames_to_notes()`；
- 不得生成 raw MIDI；
- 不得在 RMVPE 失败时降级到 CREPE/basic-pitch；
- 不得输出 placeholder F0。

#### `PitchContourService`

职责：

- 输入：`F0Track`；
- 输出：`PitchContourSet`；
- 按 voiced segment、pitch stability、local slope、glide、vibrato、短 unvoiced gap 切出 contour；
- 保留 contour 的 frame ranges、pitch distribution、confidence summary、reason codes。

禁止：

- 不得输出最终 note；
- 不得丢弃低置信 contour 而不记录 rejected/diagnostic；
- 不得把 glide/vibrato 压成唯一音符决定。

#### `NoteCandidateService`

职责：

- 输入：`F0Track + PitchContourSet`；
- 输出：`NoteCandidateSet`；
- 是 `F0 -> candidate` 的唯一权威实现；
- 对每个候选生成稳定 `candidate_id`；
- 保留 source frame range、source contour ids、pitch summary、onset/offset uncertainty、octave alternatives、segmentation alternatives、reject reasons；
- 当 F0 voiced coverage 充足但 candidate 为空时，抛出明确错误。

禁止：

- 不得消费 detector raw notes；
- 不得依赖 `ContourToCandidateBridge` 才能产生 candidate；
- 不得把 selected melody 混进 candidate set；
- 不得把 quantized duration 写进 candidate。

#### `MelodySelectionService`

职责：

- 输入：`NoteCandidateSet`；
- 输出：`MelodySelection`；
- 只选择 candidate，不改变 candidate 的 source identity；
- 支持删除、合并、八度修正、装饰音标记，但每个决策必须保留 source candidate ids。

禁止：

- 不得凭空创建没有 source candidate 的 note；
- 不得直接消费 raw F0 frames；
- 不得直接量化。

#### `QuantizedNoteService`

职责：

- 输入：`MelodySelection + RhythmGrid`；
- 输出：`QuantizedNoteSet`；
- 保留 `source_candidate_ids`、measure、beat position、duration beats、quantization warnings。

禁止：

- 不得从 raw notes 或 detector notes fallback；
- 不得在 RhythmGrid 缺失时生成正式 score notes；
- 不得把节奏失败伪装成成功 score。

#### `LeadVocalScoreBuildService`

职责：

- 输入：`QuantizedNoteSet`；
- 输出：`LeadVocalScoreRevision` / `ScoreIR`；
- 每个 `ScoreNote` 必须有 `source_candidate_id` 或 `source_candidate_ids`；
- 每个 revision 必须指向使用的 artifact IDs。

禁止：

- 不得从 `PitchAnalysisResult.raw_notes` fallback 建谱；
- 不得从 `raw_pitch.mid`、debug MIDI 或 backend MIDI 建谱；
- 不得覆盖 machine revision。

### 2.2 新权威链路

```text
MelodyTranscriptionService.transcribe()
  -> F0ExtractionService.extract(vocals_path)
  -> persist f0_track.json / Artifact(F0_TRACK)
  -> PitchContourService.build(f0_track)
  -> persist pitch_contours.json / Artifact(PITCH_CONTOURS)
  -> NoteCandidateService.build(f0_track, pitch_contours)
  -> persist note_candidates.json / Artifact(NOTE_CANDIDATES)
  -> MelodySelectionService.select(note_candidates)
  -> persist selected_melody.json / Artifact(SELECTED_MELODY)
  -> RhythmQuantizationService.build_rhythm_grid(...)
  -> persist rhythm_grid.json / Artifact(RHYTHM_GRID)
  -> QuantizedNoteService.quantize(selected_melody, rhythm_grid)
  -> persist quantized_notes.json / Artifact(QUANTIZED_NOTES)
  -> LeadVocalScoreBuildService.build(quantized_notes)
  -> persist ScoreRevision
  -> RenderExportService.export(score_revision_id)
```

## 3. 数据契约

### 3.1 `F0Track v2`

最低字段：

```json
{
  "schema_version": "f0_track_v2",
  "artifact_type": "f0_track",
  "transcription_target": "lead_vocal",
  "source_artifact_id": "...",
  "input_audio_artifact_id": "...",
  "backend": "rmvpe",
  "model": {
    "name": "rmvpe",
    "model_path_hash": "...",
    "sample_rate": 16000,
    "step_size_ms": 10
  },
  "frames": [
    {
      "frame_index": 0,
      "time_sec": 0.0,
      "f0_hz": 0.0,
      "midi_float": null,
      "confidence": 0.0,
      "voiced": false
    }
  ],
  "summary": {
    "frame_count": 0,
    "voiced_frame_count": 0,
    "voiced_coverage_ratio": 0.0,
    "duration_sec": 0.0
  },
  "warnings": []
}
```

### 3.2 `PitchContourSet v2`

最低字段：

```json
{
  "schema_version": "pitch_contour_set_v2",
  "artifact_type": "pitch_contours",
  "source_f0_artifact_id": "...",
  "contours": [
    {
      "contour_id": "pc_...",
      "source_frame_range": {
        "start_frame_index": 120,
        "end_frame_index": 180,
        "start_time_sec": 1.2,
        "end_time_sec": 1.8
      },
      "duration_sec": 0.6,
      "pitch_center_midi": 64.2,
      "pitch_median_midi": 64.1,
      "pitch_stddev_semitones": 0.18,
      "pitch_range_semitones": 0.7,
      "mean_confidence": 0.87,
      "voiced_ratio": 0.96,
      "shape": {
        "kind": "stable|glide|vibrato|unstable",
        "slope_semitones_per_sec": 0.0,
        "vibrato_rate_hz": null,
        "vibrato_extent_cents": null
      },
      "reason_codes": []
    }
  ],
  "rejected_contours": [],
  "summary": {}
}
```

### 3.3 `NoteCandidateSet v2`

最低字段：

```json
{
  "schema_version": "note_candidate_set_v2",
  "artifact_type": "note_candidates",
  "source_f0_artifact_id": "...",
  "source_pitch_contour_artifact_id": "...",
  "role": "lead_vocal_melody",
  "candidates": [
    {
      "candidate_id": "nc_...",
      "source_contour_ids": ["pc_..."],
      "source_f0_frame_range": {
        "start_frame_index": 120,
        "end_frame_index": 180,
        "start_time_sec": 1.2,
        "end_time_sec": 1.8
      },
      "onset_time_sec": 1.2,
      "offset_time_sec": 1.8,
      "onset_uncertainty_sec": 0.02,
      "offset_uncertainty_sec": 0.03,
      "pitch_center_midi": 64.1,
      "pitch_name": "E4",
      "pitch_confidence": 0.88,
      "segmentation_confidence": 0.79,
      "voiced_ratio": 0.96,
      "mean_confidence": 0.87,
      "pitch_stddev_semitones": 0.18,
      "pitch_range_semitones": 0.7,
      "candidate_score": 0.82,
      "candidate_origin": "f0_contour_segment",
      "alternative_pitch_hypotheses": [
        {
          "pitch_center_midi": 52.1,
          "reason": "possible_low_octave_error",
          "score": 0.31
        },
        {
          "pitch_center_midi": 76.1,
          "reason": "possible_high_octave_error",
          "score": 0.22
        }
      ],
      "segmentation_evidence": {
        "strategy": "stable_region_dp",
        "local_frame_count": 61,
        "boundary_reason": "pitch_stability_change"
      },
      "reason_codes": []
    }
  ],
  "rejected_candidates": [
    {
      "candidate_id": "nc_rej_...",
      "source_contour_ids": ["pc_..."],
      "rejection_reason_codes": ["low_confidence", "too_unstable"],
      "diagnostic_payload": {}
    }
  ],
  "summary": {
    "candidate_count": 0,
    "rejected_candidate_count": 0,
    "f0_to_candidate_loss_ratio": 0.0
  },
  "warnings": []
}
```

### 3.4 `MelodySelection v2`

```json
{
  "schema_version": "melody_selection_v2",
  "artifact_type": "selected_melody",
  "source_note_candidate_artifact_id": "...",
  "selected_notes": [
    {
      "selection_id": "sel_...",
      "source_candidate_ids": ["nc_..."],
      "selected_pitch_midi": 64,
      "selected_pitch_name": "E4",
      "start_time_sec": 1.2,
      "end_time_sec": 1.8,
      "selection_action": "keep|merge|octave_correct|ornament_mark",
      "selection_confidence": 0.84,
      "reason_codes": []
    }
  ],
  "suppressed_candidates": [],
  "summary": {}
}
```

### 3.5 `QuantizedNoteSet v2`

```json
{
  "schema_version": "quantized_note_set_v2",
  "artifact_type": "quantized_notes",
  "source_selected_melody_artifact_id": "...",
  "source_rhythm_grid_artifact_id": "...",
  "notes": [
    {
      "quantized_note_id": "qn_...",
      "source_selection_id": "sel_...",
      "source_candidate_ids": ["nc_..."],
      "pitch_midi": 64,
      "pitch_name": "E4",
      "start_time_sec": 1.2,
      "end_time_sec": 1.8,
      "measure_num": 2,
      "beat_position": 1.0,
      "duration_beats": 1.0,
      "quantization_confidence": 0.81,
      "reason_codes": []
    }
  ],
  "summary": {}
}
```

## 4. 代码改造计划

### Phase 1：先加护栏，不改主行为

目标：建立 characterization tests 和数据契约测试，避免重构中把当前能跑的路径打碎。

任务：

1. 新增 `tests/test_f0_candidate_lineage_contract.py`。
2. 固化以下行为：
   - 有 F0 voiced frames 时，`f0_track.json` 必须存在；
   - `note_candidates.json` 中每个 candidate 必须有稳定 `candidate_id`；
   - `selected_melody.json` 每个 selected note 必须能反查 `candidate_id`；
   - `quantized_notes.json` 每个 note 必须保留 `source_candidate_ids`；
   - `ScoreIR.notes[]` 必须带 `source_candidate_id(s)`。
3. 加失败语义测试：
   - `rmvpe_unavailable`；
   - `f0_empty`；
   - `f0_voiced_but_no_candidate`；
   - `candidate_exists_but_selector_removed_all`；
   - `rhythm_grid_unavailable`。

验收：

- 不改生产路径也能跑通新增 contract tests 的一部分；
- 失败语义中目前不满足的测试先标记为 expected failure 或先只文档化，不强行跳过。

### Phase 2：抽出 RMVPE F0 extraction

目标：让 RMVPE 的权威输出变成 `F0Track`，不是 raw notes。

改动：

1. 新增 `backend/app/modules/pitch/f0_extractor.py`。
2. 从 `PitchDetector._detect_with_rmvpe()` 中抽出：
   - model resolve；
   - model call；
   - output coercion；
   - frame artifact build。
3. 新增 `RMVPEF0Extractor.extract(audio_path) -> F0TrackPayload`。
4. `PitchDetector.detect()` 暂时保留兼容，内部调用 extractor 后再走旧 `_frames_to_notes()`。
5. `PitchPipeline` 新增 shadow path：直接拿 extractor 输出，和旧 `detector.last_detection_artifacts.f0_track` 对比。

验收：

- `F0Track` 由 extractor 直接产出；
- 旧路径输出 notes 不变；
- RMVPE missing 时仍硬失败，不 fallback。

### Phase 3：实现权威 `NoteCandidateService`

目标：让 `F0Track + PitchContourSet -> NoteCandidateSet` 成为唯一候选生成路径。

改动：

1. 新增 `backend/app/services/note_candidate_service.py` 或 `backend/app/modules/pitch/note_candidate_service.py`。
2. 将现有 `NoteCandidateBuilder` 升级为 v2 builder：
   - 不接收 `raw_candidates` 作为事实源；
   - raw detector notes 只允许作为 shadow diagnostics；
   - 支持一个 contour 产出多个 stable-region candidates；
   - 支持 rejected candidates；
   - 支持 octave alternatives；
   - 支持 deterministic candidate IDs。
3. `ContourToCandidateBridge` 降级为 legacy/shadow diagnostic，不再参与主链路。
4. 增加 hard failure：
   - `f0_to_candidate_segmentation_failed`：F0 voiced coverage 超阈值但 candidate 为空；
   - `note_candidate_schema_invalid`：candidate 缺 lineage 字段。

验收：

- raw detector notes 为空但 F0 contour 有效时，可以产生 candidates；
- `note_candidates.json` 与 pipeline 内部 candidates 是同一个对象序列化结果；
- 所有 candidates 有 source frame range。

### Phase 4：统一 selection 和 quantization

目标：删除“双 selector / 双 quantizer”事实分叉。

改动：

1. `MelodySelectionService.select(note_candidate_set)` 成为唯一选择器。
2. `RuleBasedMelodySelector` 可保留为 selection 实现，但输入必须是 `NoteCandidateSet v2`。
3. `PitchPipeline.MelodySelector` 和 artifact 层 selector 合并。
4. `QuantizedNoteService.quantize(selected_melody, rhythm_grid)` 成为唯一量化器。
5. `PitchPipeline` 不再直接产 authoritative measures；只产 typed artifacts。

验收：

- 没有 “pipeline 内选一次，service 层再选一次”；
- 没有 “pipeline 内量化一次，artifact 层再量化一次”；
- `selected_melody.json`、`quantized_notes.json` 是下游唯一输入。

### Phase 5：改 ScoreIR build

目标：ScoreIR 只能从 `QuantizedNoteSet` 构建。

改动：

1. 新增 `LeadVocalScoreBuildService.build_from_quantized_notes()`。
2. `ScoreIRBuilder._build_notes_from_raw()` 在 production profile 下禁用。
3. `ScoreIRBuilder._build_notes_from_measures()` 只允许消费由 `QuantizedNoteSet` 生成的 canonical measures。
4. 每个 `ScoreNote` 保留：
   - `source_candidate_id` 或 `source_candidate_ids`；
   - `source_selection_id`；
   - `source_quantized_note_id`；
   - `source_artifact_ids`。

验收：

- 删除/禁用 raw fallback 后，生产测试仍通过；
- 任意 score note 可反查完整 lineage。

### Phase 6：删除 legacy 主路径

目标：清理旧的混合启发式主路径。

删除或降级：

- `PitchDetector._frames_to_notes()`：保留为 legacy debug 或测试工具，不用于 production；
- `ContourToCandidateBridge`：只保留为 comparison diagnostic；
- `PitchAnalysisResult.raw_notes`：生产路径不再使用；
- `semantic_audio.melody_candidates.selected_notes`：拆到 `MelodySelection` artifact；
- `AudioAnalysisService._replace_lead_notes_from_quantized_artifact()`：改成正常 build 输入，不再“回填”。

验收：

- 代码中 production path 搜索不到 raw note fallback；
- `note_candidates.json` 不是旁路 artifact，而是主链路 artifact。

## 5. 失败语义

### 5.1 Required hard failures

| Code | 条件 | 处理 |
| --- | --- | --- |
| `rmvpe_model_unavailable` | RMVPE runtime/model 不可用 | task fail |
| `f0_track_empty` | RMVPE 没有返回 frame 或全无效 | task fail |
| `f0_unvoiced_or_no_lead_vocal` | voiced coverage 低于 lead vocal 最低要求 | task fail 或明确 no vocal diagnostic |
| `pitch_contour_build_failed` | F0 有效但 contour 构建异常 | task fail |
| `f0_to_candidate_segmentation_failed` | voiced coverage 足够但 candidate 为空 | task fail |
| `note_candidate_schema_invalid` | candidate 缺 ID/source frame/source contour | task fail |
| `melody_selection_empty` | candidate 有效但 selection 为空 | task fail，除非用户选择 instrumental/no-vocal 模式 |
| `rhythm_grid_unavailable` | 需要量化但 rhythm grid 缺失 | task fail |
| `quantized_notes_empty` | selection 有效但量化结果为空 | task fail |
| `score_ir_lineage_invalid` | ScoreNote 缺 source candidate | task fail |

### 5.2 Optional warnings

| Code | 条件 | 处理 |
| --- | --- | --- |
| `low_downbeat_confidence` | downbeat confidence 低 | warning，仍可产候选，不可隐藏量化风险 |
| `candidate_octave_uncertain` | octave alternatives 接近主候选 | warning + candidate evidence |
| `possible_vibrato_oversegmentation` | vibrato 被切成多个 candidates | warning + debug view |
| `possible_glide_undersegmentation` | glide 被压成单 candidate | warning + debug view |
| `selector_removed_many_candidates` | selection 删除大量候选 | warning + suppression summary |

## 6. 测试矩阵

### 6.1 Unit tests

- `RMVPEF0Extractor`：
  - output schema；
  - confidence/voiced normalization；
  - missing model hard fail；
  - no fallback。

- `PitchContourService`：
  - voiced gap bridge；
  - stable pitch contour；
  - glide contour；
  - vibrato contour；
  - low confidence rejected contour。

- `NoteCandidateService`：
  - stable contour -> one candidate；
  - long contour with pitch plateaus -> multiple candidates；
  - raw notes empty but contour valid -> candidates produced；
  - octave alternatives emitted；
  - unstable/short/low confidence candidates rejected；
  - deterministic candidate IDs。

- `MelodySelectionService`：
  - keep candidates with lineage；
  - merge candidates preserving source ids；
  - octave correction preserving alternatives；
  - empty selection hard failure。

- `QuantizedNoteService`：
  - candidate IDs preserved；
  - measure/beat positions valid；
  - rhythm grid missing failure；
  - pickup/short note edge cases。

### 6.2 Integration tests

- `vocals.wav -> f0_track -> pitch_contours -> note_candidates`。
- `note_candidates -> selected_melody -> quantized_notes -> ScoreIR`。
- ScoreIR note lineage complete。
- Artifacts persisted with correct type and source artifact IDs。
- Production profile rejects fallback paths。

### 6.3 Regression fixtures

至少准备以下 synthetic F0 fixtures，不依赖真实模型：

1. 单个稳定长音；
2. 两个音中间短 unvoiced gap；
3. vibrato 不应被切碎；
4. glide 不应被简单当稳定音；
5. octave drop 一小段；
6. voiced F0 明显但 detector legacy raw notes 为空；
7. 低置信噪声 contour；
8. 长 phrase 内多个 pitch plateau。

## 7. 迁移策略

### 7.1 Shadow mode

先让新链路和旧链路并跑：

```text
old: detector notes -> bridge -> selector -> quantizer
new: f0 -> contours -> note_candidates_v2 -> selection_v2 -> quantized_v2
```

记录对比指标：

- old raw note count vs new candidate count；
- old selected count vs new selected count；
- onset difference distribution；
- pitch difference distribution；
- missing note windows；
- extra note windows。

Shadow mode 只写 diagnostics，不影响生产输出。

### 7.2 Canary switch

新增配置：

```text
PITCH_CANDIDATE_PIPELINE=v1_legacy|v2_shadow|v2_authoritative
```

阶段：

1. `v2_shadow` 默认开启，生产仍用 legacy；
2. benchmark 样本通过后，内部环境切 `v2_authoritative`；
3. 真实样本错误率达标后，production 切 `v2_authoritative`；
4. 保留 legacy rollback 一段时间；
5. 删除 legacy authoritative path。

### 7.3 Rollback

Rollback 只能切回完整 legacy path，不允许混用：

- 不允许 v2 candidates + legacy selector；
- 不允许 legacy raw notes + v2 quantizer；
- 不允许 ScoreIR 从 raw fallback。

混用会重新制造双事实源。

## 8. 质量门禁

### 8.1 Artifact gate

每次成功任务必须有：

- `F0_TRACK` artifact；
- `PITCH_CONTOURS` artifact；
- `NOTE_CANDIDATES` artifact；
- `SELECTED_MELODY` artifact；
- `RHYTHM_GRID` artifact；
- `QUANTIZED_NOTES` artifact；
- `SCORE_REVISION` row；
- `MIDI` / `MUSICXML` exports from the revision。

### 8.2 Lineage gate

必须满足：

```text
ScoreNote
  -> QuantizedNote
  -> MelodySelection item
  -> NoteCandidate
  -> PitchContour
  -> F0 frame range
```

任一断链即失败。

### 8.3 Failure gate

禁止以下行为：

- RMVPE 失败但 fallback 到 CREPE/basic-pitch；
- F0 有效但 candidate 为空仍生成空谱成功；
- candidate 为空但 ScoreIR 从 raw notes 或 debug MIDI 生成；
- ScoreIR note 无 source candidate；
- 修改用户 revision 覆盖 machine revision。

## 9. 文件级改造清单

### 9.1 新增

- `backend/app/modules/pitch/f0_extractor.py`
- `backend/app/modules/pitch/f0_types.py` 或整合到 `types.py`
- `backend/app/modules/pitch/candidate_types.py` 或整合到 `types.py`
- `backend/app/services/note_candidate_service.py`
- `backend/app/services/melody_selection_service.py`
- `backend/app/services/quantized_note_service.py`
- `backend/tests/test_f0_extractor.py`
- `backend/tests/test_note_candidate_service_v2.py`
- `backend/tests/test_f0_candidate_lineage_contract.py`
- `backend/tests/fixtures/f0/*.json`

### 9.2 重构

- `backend/app/modules/pitch/detector.py`
  - 抽 RMVPE 调用到 `f0_extractor.py`；
  - `_frames_to_notes()` 降级为 legacy。

- `backend/app/modules/pitch/pitch_contours.py`
  - 输出 `PitchContourSet v2`；
  - 保留 rejected contours。

- `backend/app/modules/pitch/note_candidate_builder.py`
  - 升级为 v2 authoritative builder；
  - 移除 `raw_candidates` 权威输入。

- `backend/app/modules/pitch/pipeline.py`
  - 改为 artifact-oriented orchestration；
  - 删除 `ContourToCandidateBridge` authoritative path；
  - 删除双 selector/quantizer。

- `backend/app/services/melody_transcription_service.py`
  - 不再事后重建 `note_candidates.json`；
  - 只持久化 pipeline 返回的 authoritative artifacts。

- `backend/app/services/audio_analysis_service.py`
  - 删除 “ScoreIR build 后再用 quantized_notes 回填” 的语义；
  - 直接用 `QuantizedNoteSet` 建 ScoreIR。

- `backend/app/modules/score_ir/builder.py`
  - production 禁止 raw fallback；
  - 强制 source candidate lineage。

### 9.3 降级/删除

- `ContourToCandidateBridge`：降级为 shadow diagnostic 或删除。
- `PitchAnalysisResult.raw_notes`：legacy-only，不进入 production ScoreIR。
- `semantic_audio.melody_candidates.selected_notes`：迁移到 `MelodySelection` artifact。

## 10. 不做的事

本次重构不做：

- 不引入 piano_score polyphonic transcription；
- 不用 chroma 做 note transcription；
- 不用 reference MIDI/DTW 修生产结果；
- 不做 RVC F0 correction；
- 不做前端编辑器大改；
- 不用 LLM/agent 判断 F0 候选。

## 11. 最小可交付切片

如果要最快把方向落进代码，建议按这个切片做：

1. 新增 `RMVPEF0Extractor.extract()`，旧行为不变。
2. 新增 `NoteCandidateSet v2` schema 和 contract tests。
3. 改 `NoteCandidateBuilder`：允许 raw notes 空时从 contour 直接产 candidate。
4. 让 `MelodyTranscriptionService` 持久化 builder 的 authoritative candidate set。
5. 给 `selected_melody` 和 `quantized_notes` 强制补齐 source candidate lineage。
6. 在 `ScoreIRBuilder` 增加 production lineage validator，先 warning，后 hard fail。

这 6 步可以先不删除 legacy path，但必须让新 typed chain 可观测、可对比、可逐步切换。

## 12. 最终验收标准

生产化完成的定义：

- `PitchDetector` 不再是候选生成器；
- `F0Track -> PitchContourSet -> NoteCandidateSet` 是唯一候选链路；
- `note_candidates.json` 是主链路产物，不是旁路解释；
- `selected_melody.json` 只引用 candidates；
- `quantized_notes.json` 只引用 selected candidates 和 rhythm grid；
- `ScoreIR` 只从 quantized notes 构建；
- 所有 required stage fail explicitly；
- 每个最终 score note 可追溯到 F0 frames；
- 旧 raw fallback 和 bridge authoritative path 从 production profile 中移除。
