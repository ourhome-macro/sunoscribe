# Lead Vocal Chain And F0 Candidate Audit

日期：2026-05-15

## 结论

不是“代码已基本完善，只差真实音频”这么简单。

更准确的结论是：

1. `lead_vocal` 主链中的 `F0Track -> PitchContourSet -> NoteCandidateSet -> MelodySelection -> QuantizedNoteSet -> ScoreIR -> MIDI/MusicXML` 已经是实装代码，不是空壳。
2. `f0-candidate` 这段尤其不是纸面设计，已经能在真实音频上跑出真实 artifact，并且有较完整的 lineage 和硬失败约束。
3. 但整条产品链还没有完全闭环到“只缺真实用户音频就能上生产”：
   - `piano_score` 任务入口仍未接通。
   - 歌词识别与对齐链路当前是空转/延期状态，不是完整生产实现。
   - 一部分导出与上层任务编排是 MVP 水位，不是最终生产级完成态。

所以：`f0-candidate` 不是主要短板；短板在更上层的产品链闭环和非 pitch 子系统。

## 本次核查范围

- 静态核查 backend 主链服务与 orchestration。
- 运行 pitch runtime health。
- 运行关键 pitch/F0/candidate 测试。
- 用仓库内真实 vocal wav 跑一条 `AudioAnalysisService` 实链。

## 实跑结果

### 1. Runtime health

已确认当前环境存在真实 RMVPE runtime 与模型，不是 mock 环境。

- `pitch_backend = rmvpe`
- `allow_backend_fallbacks = false`
- `rmvpe.status = ok`
- `model_path = backend/.venv310/Lib/site-packages/rmvpe_onnx/data/rmvpe.onnx`

说明当前 F0 主链不是靠 fallback 冒充成功。

### 2. 关键测试

执行：

```powershell
.\.venv310\Scripts\python.exe -m pytest tests\test_rmvpe_f0_extractor.py tests\test_note_candidate_builder.py tests\test_pitch_pipeline.py tests\test_pitch_runtime_health.py tests\test_pitch_lineage_contract.py -q
```

结果：

- `31 passed`

这说明 `F0 -> contour -> candidate -> selected melody -> quantized -> lineage` 这段至少在契约层和核心行为层是稳定的。

### 3. 真实音频链路运行

实际运行了：

- 输入：仓库根目录 `source_(Vocals)_UVR_MDXNET_Main.wav`
- 服务：`AudioAnalysisService.process_audio(..., enable_vocal_separation=False)`

结果摘要：

- `f0_track.frames = 29769`
- `melody_candidates.notes = 249`
- `selected_melody.selected_notes = 16`
- `quantized_notes.notes = 16`
- `score_ir.notes = 16`
- 生成了 machine revision、artifact manifest、MIDI、MusicXML

落盘目录：

- `backend/data/projects_runtime_check/runtimecheck01/...`

这已经足够说明 `f0-candidate` 不是“还没实现，只差喂数据看看”的状态。

## 已确认闭环的部分

### 1. F0 强约束是实的

`backend/app/modules/pitch/f0_extractor.py`

- 明确声明 F0 stage 只负责 `F0Track`，不做 note segmentation。
- RMVPE 不可用时显式失败，不允许用其他 backend 悄悄补位。
- `fallback_allowed = False`

这和项目的 no-silent-fallback 原则是一致的。

### 2. Melody transcription 子链是实装且硬依赖完整

`backend/app/services/melody_transcription_service.py`

- 缺 `pitch_pipeline` 直接失败。
- 缺 `F0Track` 直接失败。
- 缺 `PitchContourSet` 直接失败。
- 没有 authoritative `selected_melody` 直接失败。

这不是 demo 型“能出什么算什么”的写法，而是生产链约束写法。

### 3. Note candidate 不是虚结构

实际产物 `note_candidates.json` 显示：

- `schema_version = note_candidate_set_v2`
- `analysis_info.accepted_candidate_count = 249`
- `analysis_info.rejected_candidate_count = 195`
- 带 `source_contour_ids`
- 带 `source_f0_frame_range`
- 带 rejection reason 和 segmentation evidence

说明它不仅生成了 candidate，还保留了足够强的可追溯性。

### 4. Selected melody 与 Quantized notes 已打通到 ScoreIR

真实运行结果显示：

- `quantized_notes.notes = 16`
- `score_ir.notes = 16`
- 首个 `score_ir.note.source_candidate_id` 与 `quantized_note.source_candidate_id` 对齐
- `score_ir.note.source = "quantized_notes"`

这说明当前 lead-vocal 的 ScoreIR 已经消费量化后的权威主旋律，不再是绕过 typed MIR artifact 直写 score。

### 5. Artifact lineage 已实际落盘

真实 artifact manifest 已包含：

- `source_media`
- `canonical_audio`
- `f0_track`
- `pitch_contours`
- `note_candidates`
- `selected_melody`
- `rhythm_grid`
- `quantized_notes`
- `score_ir`
- `score_data`
- `midi`
- `musicxml`

这一点很关键，说明链路不是“内存里拼一下返回结果”，而是确实按 typed artifact 思路落盘。

## 没有闭环的部分

### 1. `piano_score` 仍未接通

`backend/app/services/task_orchestrator.py`

任务执行里仍然写死：

- 读取 `transcription_target`
- 若不是 `lead_vocal`，直接 `unsupported transcription_target`

所以全项目层面不能说“结构链路已经完整”，只能说 lead-vocal 这支相对完整。

### 2. 歌词识别和对齐当前不是生产闭环

`backend/app/services/audio_analysis_service.py`

在 perception stage 中：

- `lyrics_segments` 直接初始化为空列表
- 没有实际调用 `_invoke_lyrics_recognizer`
- `process_audio()` 后直接走 `alignment = self._empty_alignment_stage()`

`_empty_alignment_stage()` 返回的是：

- `method = "plugin_deferred"`
- warning: `lyrics_alignment_deferred_to_plugin`

这意味着歌词相关链路当前并没有真正接入主流程，只是留了骨架。

### 3. 导出链路仍偏 MVP

当前确实能产出 MIDI 和 MusicXML，但从 `AudioAnalysisService` 代码形态看，导出链仍是内部拼装式实现，离你在架构文档里要求的长期形态还有距离。

尤其 MusicXML 路径仍更像临时实现，而不是最终 `music21` 主导的生产 engraving 路径。

### 4. `AudioAnalysisService` 仍然过宽

虽然主链已能跑，但服务边界仍偏“大一统”：

- media ingest
- stem separation
- melody transcription
- score build
- alignment placeholder
- export
- machine revision persist

这与架构文档里要求的 target-aware service 边界相比，还没有完全完成收敛。

## 对“f0-candidate”的直接判断

如果问题是：

> `f0-candidate` 这一段是不是已经写完，只差真实音频验证？

回答是：

- 不是“只差验证”，因为它已经在真实音频上跑通了。
- 也不是“还有大面积未实现”，因为其主体实现、runtime 依赖、artifact lineage、测试覆盖都已经在。

更准确的判断是：

- `f0-candidate` 主体已完成到可运行、可产物、可追溯的阶段。
- 后续更多是阈值、选择策略、桥接策略、样本覆盖面的调优，而不是从 0 到 1 的实现缺失。

## 对“是否只差真实音频”的最终判断

如果问题是：

> 整个现在的代码是不是已经完善，只差真实音频？

答案是否定的。

原因不是 pitch 主链不行，而是：

1. 只有 `lead_vocal` 分支接通。
2. 歌词识别/对齐主链未接通。
3. 部分导出与服务边界仍是 MVP 实现。
4. 上层产品级任务闭环还没完全达到你文档里定义的目标状态。

## 最硬的一句话

当前状态最准确的表述应该是：

> `lead_vocal` 的 F0-candidate 到 ScoreIR 主链已经基本打穿，并且已能在真实音频上产出可追溯 artifact；真正没闭环的，不是 F0-candidate，而是歌词链、`piano_score` 分支和更完整的产品级生产收口。

