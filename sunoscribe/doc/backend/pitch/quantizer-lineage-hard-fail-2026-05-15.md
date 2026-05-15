# Quantizer Lineage Preservation and ScoreIR Hard Fail (2026-05-15)

## Change

This update closes the P1 lineage break in `NoteQuantizer._preprocess_notes()`. Same-pitch merge and overlap trimming no longer rebuild bare `Note` objects that drop production lineage.

## Quantizer Semantics

- Same-pitch or near-pitch merge keeps the leading note as the primary `source_candidate_id`.
- `source_candidate_ids` is the ordered union of both merged notes.
- `source_contour_ids` is the ordered union of both merged notes.
- `source_f0_frame_range` is expanded to the minimum start frame/time and maximum end frame/time available.
- `segmentation_evidence`, `contour_bridge_evidence`, guard reason codes, and candidate origin are preserved or merged.
- Overlap trimming changes timing only; it preserves candidate/contour/F0 lineage instead of clearing it.

## ScoreIR Semantics

`ScoreIRBuilder` now treats production lineage violations as hard failures, not warnings. If a quantized production note lacks candidate, contour, F0 frame range, or quantized-note identity, the build raises `score_ir_lineage_contract_failed:*`.

The old post-build replacement path in `AudioAnalysisService` is disabled under `_legacy_replace_lead_notes_from_quantized_artifact_for_old_builder_only()`. Production must build ScoreIR directly from `QuantizedNoteSet`.

## Validation

Passing targeted tests:

```text
PYTHONPATH=backend python -m unittest \
  backend.tests.test_quantizer \
  backend.tests.test_score_ir_builder \
  backend.tests.test_pitch_lineage_contract \
  backend.tests.test_pitch_pipeline \
  backend.tests.test_rmvpe_f0_extractor \
  backend.tests.test_note_candidate_builder \
  backend.tests.test_melody_selection_artifact \
  backend.tests.test_quantized_notes_artifact
```

Result: 74 tests passed.

A broader run including `backend.tests.test_audio_analysis_service` still has one environment failure unrelated to this migration: local `pydantic` is unavailable, so the default audio processor factory returns `None`.
