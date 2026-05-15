# Upstream Candidate Authority Agreement (2026-05-15)

## Judgment

I agree with the proposed next direction.

The next production cut should not polish `MelodySelector`. It should collapse upstream sources of truth so the lead-vocal path has one authoritative candidate chain:

```text
F0Track -> PitchContourSet -> NoteCandidateSet -> MelodySelection -> QuantizedNoteSet -> ScoreIR
```

The downstream half is now much harder than before: quantizer merge/trim preserves lineage, `QuantizedNoteSet -> ScoreIR` is the primary path, missing lineage can hard fail, and legacy post-build replacement is disabled. The weakest remaining production boundary is therefore upstream candidate authority.

## Evidence In Current Code

The pipeline still starts from detector notes before authoritative candidate construction:

- `PitchPipeline.run()` first calls `_safe_detect_candidates()` and creates `detected_notes`: `backend/app/modules/pitch/pipeline.py:667`.
- F0 extraction happens later: `backend/app/modules/pitch/pipeline.py:773`.
- Contours are built from F0: `backend/app/modules/pitch/pipeline.py:789`.
- `ContourToCandidateBridge` still updates production `detected_notes`: `backend/app/modules/pitch/pipeline.py:790` and `backend/app/modules/pitch/pipeline.py:795`.
- Melody selection still consumes `arrangement_decision.selected_lead_notes`, not a single authoritative `NoteCandidateSet v2`: `backend/app/modules/pitch/pipeline.py:821`.
- Semantic melody candidates are still wrapped from `detected_notes`: `backend/app/modules/pitch/pipeline.py:871`.

This confirms the current problem is not selector quality. It is source-of-truth ambiguity.

## What Is Already Covered

There is already a useful unit-level contract proving candidate generation from valid contours with empty raw detector notes:

- `test_builds_candidate_from_stable_contour_when_raw_candidates_empty`: `backend/tests/test_note_candidate_builder.py:29`.
- It calls `NoteCandidateBuilder().build(... raw_candidates={"melody_candidates": {"notes": []}})`: `backend/tests/test_note_candidate_builder.py:64`.
- It asserts `source_contour_ids` and `source_f0_frame_range`: `backend/tests/test_note_candidate_builder.py:74`.
- It asserts `raw_candidates_empty=True`: `backend/tests/test_note_candidate_builder.py:79`.

There is also a lineage chain unit test:

- `NoteCandidateBuilder -> RuleBasedMelodySelector -> QuantizedNotesArtifactBuilder`: `backend/tests/test_pitch_lineage_contract.py:56`.
- It verifies candidate lineage survives selection and quantization: `backend/tests/test_pitch_lineage_contract.py:72` to `backend/tests/test_pitch_lineage_contract.py:95`.

So the missing piece is not another isolated unit test only. The missing piece is wiring: the service/pipeline must persist and consume that authoritative candidate set instead of continuing to route through detector-note/bridge facts.

## Recommended Next Cut

### 1. Strengthen the contract test into a service/pipeline boundary test

Keep the existing `NoteCandidateBuilder` unit test, but add a higher-level test proving:

```text
raw detector notes empty
F0Track valid
PitchContourSet valid
=> persisted NoteCandidateSet v2 has candidates and full lineage
=> downstream selected/quantized/ScoreIR notes trace back to those candidates
```

This test should fail if candidate persistence is rebuilt from `semantic_audio.melody_candidates` rather than the authoritative builder output.

### 2. Make MelodyTranscriptionService persist the authoritative candidate set

`MelodyTranscriptionService._build_note_candidates_payload()` currently builds candidates using `f0_track_dict`, `pitch_contours_dict`, and `semantic_audio_dict.get("melody_candidates")` as `raw_candidates`: `backend/app/services/melody_transcription_service.py:217` to `backend/app/services/melody_transcription_service.py:237`.

The next change should make the output of this step the product artifact that downstream stages consume. It should not be a sidecar reconstruction after pipeline decisions already happened.

### 3. Change pipeline consumption order

Target order:

```text
lead_f0_track = RMVPEF0Extractor.extract(...)
pitch_contours = PitchContourBuilder.build(lead_f0_track)
note_candidates = NoteCandidateBuilder.build(f0_track, pitch_contours, raw_candidates=optional evidence only)
melody_selection = MelodySelectionService.select(note_candidates)
quantized_notes = QuantizedNoteService.quantize(melody_selection, rhythm_grid)
score_ir = ScoreIRBuilder.build(..., quantized_notes_artifact=quantized_notes)
```

`ContourToCandidateBridge` should become legacy/shadow compare only. It should not mutate production `detected_notes`.

## Hard Line

Do not spend the next cycle improving selector heuristics. A better selector on top of mixed facts only makes bad architecture harder to see.

The next production objective is single authority:

```text
NoteCandidateSet v2 is the only source accepted by MelodySelection.
```

Once that is true, selector quality work becomes meaningful.
