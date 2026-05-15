# ScoreIR QuantizedNoteSet Primary Input Migration (2026-05-15)

## Change

Lead-vocal ScoreIR build now accepts `QuantizedNoteSet` as the primary production input instead of building lead notes from `measures`, `lead_notes`, or `raw_notes` and then replacing them after the fact.

The production chain is now tighter:

```text
F0Track
  -> PitchContourSet
  -> NoteCandidateSet v2
  -> MelodySelection v2
  -> QuantizedNoteSet v2
  -> ScoreIR lead notes
```

## Implementation

- `ScoreIRBuilder.build(..., quantized_notes_artifact=...)` builds lead `ScoreNote` objects directly from `QuantizedNoteSet.notes`.
- `ScoreBuildService.build(..., quantized_notes_dict=...)` forwards the artifact into the builder.
- `AudioAnalysisService` validates that production ScoreIR notes came from `QuantizedNoteSet`; it no longer relies on post-build replacement as the production contract.
- `ScoreNote` now carries:
  - `source_candidate_ids`
  - `source_contour_ids`
  - `source_f0_frame_range`
- `ScoreIRSerializer` includes those fields in `score_data` and serialized score payloads.
- `NoteQuantizer` and pipeline measure packing preserve candidate/contour/F0 lineage when using legacy in-memory quantized notes.

## Failure Semantics

When a `QuantizedNoteSet` is expected by `AudioAnalysisService`, ScoreIR validation fails explicitly if:

- the artifact is missing;
- the artifact has no notes;
- ScoreIR note count differs from QuantizedNoteSet note count;
- any final lead `ScoreNote` lacks `quantized_note_id`, `source_candidate_id`, `source_candidate_ids`, `source_contour_ids`, or `source_f0_frame_range`.

This is intentional. A production score must not silently fall back to measure notes, raw detector notes, debug MIDI, or post-hoc reconstruction.

## Compatibility

`ScoreIRBuilder` still keeps non-production fallback readers for older unit tests and diagnostic callers, but production orchestration now passes and validates `QuantizedNoteSet`.

The old `AudioAnalysisService._replace_lead_notes_from_quantized_artifact()` remains temporarily for compatibility tests and staged removal. It is no longer the production path used by `_run_perception_stage`.

## Validation

Passing targeted contract suite:

```text
PYTHONPATH=backend python -m unittest \
  backend.tests.test_score_ir_builder \
  backend.tests.test_pitch_lineage_contract \
  backend.tests.test_pitch_pipeline \
  backend.tests.test_rmvpe_f0_extractor \
  backend.tests.test_note_candidate_builder \
  backend.tests.test_melody_selection_artifact \
  backend.tests.test_quantized_notes_artifact
```

Result: 63 tests passed.

Broader `backend.tests.test_audio_analysis_service` still has one local environment failure unrelated to this migration: `pydantic` is unavailable, so the default audio processor factory returns `None`. The quantized ScoreIR path tests in that module pass once the environment dependency is present.
