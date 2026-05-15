# MelodyTranscriptionService Note Candidate Builder 集成

本次调整把 `note_candidates` 的构建责任固定在 `MelodyTranscriptionService`，而不是继续把 detector/semantic 输出直接当最终 artifact。

当前策略：

- 若 `backend/app/modules/pitch/note_candidate_builder.py` 已存在，则优先实例化其中的 `NoteCandidateBuilder`。
- 若该文件尚未落地，则 service 使用内置兼容 builder，仅作为清晰的集成点，不创建新模块文件，避免与并行任务冲突。
- service 先产出 `f0_track`、再产出 `pitch_contours`、再构建 `note_candidates`，保持链路：`F0Track -> PitchContours -> NoteCandidates -> SelectedMelody -> QuantizedNotes`。

artifact 约束：

- `note_candidates.json` 的 canonical `melody_candidates.notes` 由 builder 产出。
- 原 `semantic_audio.melody_candidates` 不再被直接当成 canonical 输出，而是保存在 `melody_candidates.raw_source` 中作为 provenance。
- canonical notes 需要带 `builder_version`、`stable_id`、`source_contour_ids`，便于后续 selected/quantized/score trace。
- 当 semantic raw candidates 为空但 contour 稳定时，service 仍可从 contour 补出 canonical candidates，让 `selected_melody` 和 `quantized_notes` 继续走通。

注意：

- `_has_lead_notes` 仍只检查 pitch pipeline 原始产物，不把 service 层补出的 selected/quantized 当成“pitch pipeline 成功”的证据。
- 外部独立 builder 一旦接入，service 只做 schema 归一化和 provenance 补齐，不改 pitch pipeline 输出模型。
