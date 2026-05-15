# NoteCandidateSet v2 Selection Authority (2026-05-15)

## Decision

`NoteCandidateSet v2` is now the authoritative production input to lead-vocal melody selection.

The production chain is tightened to:

```text
F0Track
  -> PitchContourSet
  -> NoteCandidateSet v2
  -> MelodySelection v2
  -> QuantizedNoteSet v2
  -> ScoreIR
```

`MelodySelection` must not choose production notes from `selected_notes`, raw detector notes, or direct `PitchContourSet` fallback when a v2 candidate set is present.

## Code Changes

### Selector contract

`RuleBasedMelodySelector` now treats `note_candidate_set_v2` as a hard contract:

- It reads only `melody_candidates.notes` for v2 input.
- It ignores legacy `melody_candidates.selected_notes` for v2 input.
- It does not fall back to `pitch_contours.contours` for v2 input.
- It hard-fails when selected candidates are missing lineage fields:
  - `source_candidate_id` or `candidate_id`
  - `source_candidate_ids`
  - `source_contour_ids`
  - `source_f0_frame_range`

Legacy fallback behavior remains only for non-v2 payloads so older unit fixtures and diagnostic paths are isolated from production v2 semantics.

### Candidate builder contract

`NoteCandidateBuilder` now ensures contour-seeded candidates carry their own stable candidate id in:

- `source_candidate_id`
- `source_candidate_ids`

Raw detector notes are no longer allowed to become authoritative v2 candidates unless they can be linked to F0/PitchContour lineage. Raw notes without contour linkage are omitted from the v2 authority path instead of passing into selection with missing lineage.

### Pipeline authority

`PitchPipeline.run()` now builds an authoritative `NoteCandidateSet v2` after F0 and pitch contours are available, then selects lead melody from that typed candidate set.

Detector raw notes may still be used as optional evidence to seed candidate construction, but they are not the direct selector input. This makes raw detector notes evidence, not the melody selection source of truth.

The semantic melody candidate artifact now records:

- `candidate_authority = note_candidate_set_v2`
- `candidate_count`
- `selected_count`
- `selected_melody` payload summary
- existing bridge diagnostics for comparison

## Failure Semantics

This change intentionally prefers clear failure or empty selection over untraceable melody output.

If a v2 candidate reaches `MelodySelection` without candidate/contour/F0 lineage, the selector raises:

```text
melody_selection_lineage_contract_failed:...
```

If a v2 payload is present but does not expose `melody_candidates.notes`, selector fallback to raw selected notes or pitch contours is disabled.

## Tests Added Or Updated

Coverage now includes:

- v2 selector ignores legacy `selected_notes` and direct contour fallback.
- v2 selector hard-fails missing lineage.
- pipeline produces authoritative candidates from valid F0/contours when raw detector notes are empty.
- pipeline selection consumes typed candidate authority rather than raw detector notes.
- service selection and quantization preserve source candidate lineage.

## Validation

Passing targeted contract suite:

```text
PYTHONPATH=backend python -m unittest \
  backend.tests.test_pitch_pipeline \
  backend.tests.test_melody_selection_artifact \
  backend.tests.test_note_candidate_builder \
  backend.tests.test_pitch_lineage_contract \
  backend.tests.test_quantized_notes_artifact \
  backend.tests.test_quantizer \
  backend.tests.test_score_ir_builder \
  backend.tests.test_rmvpe_f0_extractor
```

Result:

```text
Ran 104 tests in 0.097s
OK
```

Broader suite including `backend.tests.test_audio_analysis_service` still has one local environment failure:

```text
test_default_audio_processor_uses_mvp_canonical_format
No module named 'pydantic'
```

That failure is unrelated to this migration and reflects the current local dependency environment. The audio service tests that exercise melody candidate persistence and ScoreIR quantized primary input pass before that dependency-specific assertion.

## Remaining Work

Next production cut should remove or shadow-only the old `ContourToCandidateBridge` mutation path inside `PitchPipeline.run()`. It can remain as diagnostics during migration, but it should stop mutating `detected_notes` before candidate authority is built.

After that, `PitchDetector` note segmentation should be demoted fully to optional evidence or debug output. F0 extraction and note segmentation must remain separate typed stages.