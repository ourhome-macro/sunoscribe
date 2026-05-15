# F0 Candidate Lineage Phase 1/3 Migration Note (2026-05-15)

## Scope

This update advances the production refactor in small reversible slices:

```text
vocals.wav
  -> RMVPEF0Extractor.extract()
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet v2
  -> MelodySelection v2
  -> QuantizedNoteSet v2
  -> ScoreIR lineage warnings
```

The legacy detector-note path still exists for compatibility and evidence, but the pipeline now has an explicit required F0 extraction stage before contour building.

## Contract Changes

### NoteCandidateSet v2

`NoteCandidateBuilder` now emits `schema_version="note_candidate_set_v2"` and a `lineage_contract` block.

Every production candidate is expected to carry:

- `candidate_id`
- `source_contour_ids`
- `source_f0_frame_range`

Raw detector notes remain optional evidence, not the only way to produce candidates. Contour-derived candidates continue to be generated when raw detector notes are empty but F0 contours are valid.

### MelodySelection v2

`RuleBasedMelodySelector` now emits `schema_version="selected_melody_v2"` and keeps both:

- `source_candidate_id`
- `source_candidate_ids`

It also preserves:

- `source_contour_ids`
- `source_f0_frame_range`

This makes the selector output a reference to `NoteCandidateSet`, not a newly invented note set.

### QuantizedNoteSet v2

`QuantizedNotesArtifactBuilder` now emits `schema_version="quantized_note_set_v2"` and carries forward:

- `source_candidate_id`
- `source_candidate_ids`
- `source_contour_ids`
- `source_f0_frame_range`

Quantization therefore remains traceable back to the selected melody candidate and the original F0 frame range.

## Pipeline Change

`PitchPipeline` now owns an `RMVPEF0Extractor` instance and calls it for the lead-vocal F0 stage before building contours.

Compatibility behavior is intentionally narrow:

- If tests or legacy callers already supplied a detector `f0_track` artifact, the pipeline may reuse it only when extractor execution fails.
- If no F0Track can be produced, the pipeline raises `required_f0_extraction_failed`.
- This is not a CREPE/basic-pitch fallback. It only reuses an RMVPE-style detector frame artifact already present in the same call.

## ScoreIR Validator

`ScoreIRBuilder` now adds warning-level production lineage checks. It does not hard fail yet.

Current warnings:

- `score_ir_lineage_warning:missing_source_candidate_id`
- `score_ir_lineage_warning:missing_quantized_note_id`
- `score_ir_lineage_warning:authoritative_selection_empty`

These warnings are a transition guard before a later hard-fail validator.

## Validation

Targeted unittest command:

```powershell
$env:PYTHONPATH='backend'; python -m unittest backend.tests.test_pitch_pipeline backend.tests.test_rmvpe_f0_extractor backend.tests.test_pitch_lineage_contract backend.tests.test_note_candidate_builder backend.tests.test_melody_selection_artifact backend.tests.test_quantized_notes_artifact backend.tests.test_score_ir_builder
```

Result:

```text
Ran 62 tests in 0.080s
OK
```

Broader service validation command:

```powershell
$env:PYTHONPATH='backend'; python -m unittest backend.tests.test_audio_analysis_service backend.tests.test_pitch_pipeline backend.tests.test_rmvpe_f0_extractor backend.tests.test_pitch_lineage_contract backend.tests.test_note_candidate_builder backend.tests.test_melody_selection_artifact backend.tests.test_quantized_notes_artifact backend.tests.test_score_ir_builder
```

Result:

```text
Ran 73 tests in 1.160s
FAILED (failures=1)
```

The only remaining failure was `test_default_audio_processor_uses_mvp_canonical_format`, because this local environment cannot instantiate the default audio stack: `No module named 'pydantic'`. All F0/candidate/selection/quantization/ScoreIR lineage tests passed in that broader run.

`pytest` is not available in the current Python environment, so validation used `unittest`.
