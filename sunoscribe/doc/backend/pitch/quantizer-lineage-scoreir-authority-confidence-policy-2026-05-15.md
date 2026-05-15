# Quantizer Lineage, Typed ScoreIR Authority, and Confidence Policy

Date: 2026-05-15
Worktree: `sunoscribe-candidate-authority`

## Status

This change closes the next production-risk slice for the lead-vocal candidate authority refactor.

The production path is now treated as:

```text
F0Track
  -> PitchContourSet
  -> NoteCandidateSet v2
  -> MelodySelection
  -> RhythmGrid
  -> QuantizedNoteSet v2
  -> ScoreIRBuilder
  -> LeadVocal ScoreIR
```

`ContourToCandidateBridge`, detector note segmentation, raw/debug MIDI, and post-build quantized artifacts remain non-authoritative diagnostics only.

## Quantizer Lineage Preservation

`NoteQuantizer` previously rebuilt `Note` instances during same-pitch merge and overlap trim. That could erase:

- `source_candidate_id`
- `source_candidate_ids`
- `source_contour_ids`
- `segmentation_evidence.source_f0_frame_range`

The quantizer now preserves those fields through:

- same-pitch merge
- overlap trimming from the previous note end
- overlap trimming from the current note start
- final `QuantizedNote` construction

For merged notes, the output carries the union of source candidate IDs and contour IDs, and a merged F0 frame range covering the full source span. The original source frame ranges are retained under `segmentation_evidence.merged_source_f0_frame_ranges` for diagnostics.

Failure policy: this is not a fallback. If downstream ScoreIR production sees missing lineage after quantization, it fails through the ScoreIR lineage contract.

## ScoreIR Typed Artifact Authority

`ScoreIRBuilder` now validates the required typed `QuantizedNoteSet v2` before building production lead-vocal notes.

Hard-fail cases:

- `score_ir_quantized_primary_contract_failed:missing_quantized_note_set_v2`
- `score_ir_quantized_primary_contract_failed:invalid_quantized_note_set_schema`
- `score_ir_quantized_primary_contract_failed:empty_quantized_note_set_v2`
- `score_ir_quantized_primary_contract_failed:invalid_quantized_note_set_notes:*`
- `score_ir_quantized_primary_contract_failed:duplicate_quantized_note_ids:*`
- `score_ir_quantized_primary_contract_failed:measure_note_not_in_quantized_note_set:*`
- `score_ir_lineage_contract_failed:*`

The production note body is now built from `semantic_audio.melody_candidates.analysis_info.quantized_notes.notes`, not from a post-hoc artifact side path. Measures are allowed to provide measure boundaries and optional ID consistency checks, but not the authoritative note content.

The old AudioAnalysisService helpers remain present only as explicit tripwires:

- `_replace_lead_notes_from_quantized_artifact()` raises `legacy_score_ir_quantized_artifact_replacement_disabled:*`
- `_annotate_score_ir_notes()` raises `legacy_score_ir_quantized_artifact_annotation_disabled:*`

## Confidence Policy

MVP confidence gates are now explicit config fields and persisted into typed metadata.

Lowered recall-biased defaults:

- detector confidence threshold: `0.50 -> 0.45`
- quantize noise floor: `0.35 -> 0.30`
- quantize merge min confidence: `0.50 -> 0.45`
- melody selection min confidence: `0.52 -> 0.45`
- short/isolated melody note min confidence: `0.62 -> 0.58`

New explicit fields:

- `note_candidate_min_confidence`
- `note_candidate_min_voiced_ratio`
- `note_candidate_min_stability`
- `melody_selection_min_voiced_ratio`
- `melody_selection_min_stability`
- `contour_bridge_min_confidence`
- `contour_bridge_min_voiced_ratio`
- `contour_bridge_min_duration_sec`
- `contour_bridge_max_duration_sec`
- `contour_bridge_min_stability`
- `contour_bridge_min_gap_sec`

The confidence policy is persisted under:

- `PitchAnalysisResult.analysis_info.confidence_policy`
- `semantic_audio.melody_candidates.analysis_info.confidence_policy`
- `NoteCandidateSet v2 analysis_info.confidence_policy`
- `QuantizedNoteSet v2 confidence_policy`

Policy version: `lead_vocal_confidence_policy_v1`.

Reason: `mvp_recall_bias_lower_confidence_gates`.

## Validation

Focused regression suite:

```text
PYTHONPATH=backend python -m unittest \
  backend.tests.test_quantizer \
  backend.tests.test_score_ir_builder \
  backend.tests.test_pitch_pipeline \
  backend.tests.test_note_candidate_builder \
  backend.tests.test_melody_selection_artifact \
  backend.tests.test_rmvpe_f0_extractor \
  backend.tests.test_pitch_lineage_contract \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_builds_note_candidates_with_raw_source_trace \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_fails_without_typed_note_candidate_artifact \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_perception_stage_routes_stems_to_pitch_request \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_legacy_quantized_artifact_score_ir_replacement_is_disabled \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_legacy_score_ir_quantized_annotation_is_disabled
```

Result:

```text
Ran 75 tests in 1.412s
OK
```

Environment warnings observed during tests:

- `audio-separator` is unavailable.
- `pydantic` is unavailable for the default `PitchPipeline` import path.

Those warnings are from optional/default service construction in tests and were not used as production fallbacks.
