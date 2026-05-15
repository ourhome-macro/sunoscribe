# ScoreIR Primary Input and Typed Artifact Authority Update - 2026-05-15

## Scope

This update closes the first two production authority cuts for lead-vocal MVP:

1. `ScoreIRBuilder` now treats `QuantizedNoteSet` carried by `PitchAnalysisResult.measures[*].notes` as the primary production input whenever the pipeline declares `lead_candidate_authority=note_candidate_set_v2`, `lead_selection_authoritative=true`, or `lead_note_source=quantized_notes`.
2. `MelodyTranscriptionService` now persists typed artifacts emitted by `PitchPipeline` instead of rebuilding candidate/selection/quantized artifacts as a side path.

## Production Semantics

- `PitchPipeline` writes authoritative typed payloads into `semantic_audio.melody_candidates.analysis_info`:
  - `pitch_contours`
  - `note_candidate_set`
  - `selected_melody`
  - `quantized_notes`
- `MelodyTranscriptionService` reads those payloads directly and fails if any required payload is missing. It does not rebuild `NoteCandidateSet`, `MelodySelection`, or `QuantizedNoteSet` from secondary inputs.
- `AudioAnalysisService` no longer replaces `ScoreIR.notes` from a standalone `quantized_notes` artifact after score build.
- The legacy `_replace_lead_notes_from_quantized_artifact()` entry point is intentionally disabled and raises `legacy_score_ir_quantized_artifact_replacement_disabled` if called.

## Lineage Contract

For production lead-vocal ScoreIR notes, every final `ScoreNote` must preserve:

- `source="quantized_notes"`
- `quantized_note_id`
- `source_candidate_id`
- `source_candidate_ids`
- `source_contour_ids`
- `source_f0_frame_range` with `start_frame_index`, `end_frame_index`, and positive `frame_count`

`ScoreIRBuilder` hard-fails with `score_ir_lineage_contract_failed:*` instead of warning when this contract is violated on an authoritative lead-vocal path.

## Test Result

Passed targeted contract suite:

```text
PYTHONPATH=backend python -m unittest \
  backend.tests.test_score_ir_builder \
  backend.tests.test_pitch_pipeline \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_passes_vocal_activity_to_selector \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_builds_note_candidates_with_raw_source_trace \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_perception_stage_routes_stems_to_pitch_request \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_perception_stage_fails_when_pitch_pipeline_returns_no_notes \
  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_legacy_quantized_artifact_score_ir_replacement_is_disabled
```

Result: `Ran 31 tests OK`.\n\nCombined authority suite:\n\n```text\nPYTHONPATH=backend python -m unittest \\\n  backend.tests.test_score_ir_builder \\\n  backend.tests.test_pitch_pipeline \\\n  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_passes_vocal_activity_to_selector \\\n  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_builds_note_candidates_with_raw_source_trace \\\n  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_melody_transcription_fails_without_typed_note_candidate_artifact \\\n  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_perception_stage_routes_stems_to_pitch_request \\\n  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_perception_stage_fails_when_pitch_pipeline_returns_no_notes \\\n  backend.tests.test_audio_analysis_service.TestAudioAnalysisService.test_legacy_quantized_artifact_score_ir_replacement_is_disabled \\\n  backend.tests.test_note_candidate_builder \\\n  backend.tests.test_melody_selection_artifact \\\n  backend.tests.test_quantizer \\\n  backend.tests.test_rmvpe_f0_extractor \\\n  backend.tests.test_pitch_lineage_contract\n```\n\nResult: `Ran 73 tests OK`.

Full `backend.tests.test_audio_analysis_service` currently has one unrelated environment failure in this local shell: `pydantic` is not installed, so `test_default_audio_processor_uses_mvp_canonical_format` cannot construct the default processor.

## MVP Impact

This removes the most dangerous remaining bypass for lead-vocal MVP: final ScoreIR is no longer post-mutated from a standalone quantized artifact, and upstream service persistence no longer silently rebuilds artifacts from alternate inputs.


