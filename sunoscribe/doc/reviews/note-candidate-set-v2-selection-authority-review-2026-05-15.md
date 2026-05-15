# NoteCandidateSet v2 Selection Authority Review (2026-05-15)

## Verdict

This cut is a real step forward. Production melody selection is now much closer to being driven by `NoteCandidateSet v2`, and the new raw-empty F0/contour contract test proves the most important behavior: valid F0 and contours can produce authoritative candidates even when detector raw notes are empty.

However, this is not yet a fully clean upstream authority chain. `PitchPipeline` still runs detector notes before F0 extraction, still runs `ContourToCandidateBridge`, and still assigns `detected_notes = contour_bridge_result.notes`. That means bridge output can still affect production raw/arrangement evidence, even if typed selection now consumes `NoteCandidateSet v2`.

Final judgment: candidate authority is partially reclaimed at the selection boundary, but `ContourToCandidateBridge` must be moved to shadow diagnostics next.

## What Is Now Correct

### 1. Selector now has a NoteCandidateSet v2 hard contract

`RuleBasedMelodySelector.select()` validates v2 candidates before selection:

- selector entry: `backend/app/modules/pitch/melody_selection_artifact.py:80`
- v2 validation call: `backend/app/modules/pitch/melody_selection_artifact.py:90`
- lineage contract fields in output: `backend/app/modules/pitch/melody_selection_artifact.py:131`
- missing candidate/contour/F0 lineage violations: `backend/app/modules/pitch/melody_selection_artifact.py:220` to `backend/app/modules/pitch/melody_selection_artifact.py:229`

This is the right production direction: selector should select candidates, not invent notes.

### 2. Pipeline now builds NoteCandidateSet v2 before typed selection

`PitchPipeline._build_note_candidate_payload()` calls `NoteCandidateBuilder.build()` and requires `schema_version="note_candidate_set_v2"`:

- builder call: `backend/app/modules/pitch/pipeline.py:425`
- v2 schema hard check: `backend/app/modules/pitch/pipeline.py:438`

`PitchPipeline._select_authoritative_melody()` then sends that payload into the typed selector:

- typed selector call: `backend/app/modules/pitch/pipeline.py:449`
- selected note conversion: `backend/app/modules/pitch/pipeline.py:461`

This is the important architectural move.

### 3. SemanticAudio melody_candidates now comes from the NoteCandidateSet payload

`SemanticAudioResult.melody_candidates` is now built from `_note_candidate_set_from_payload()` rather than wrapping `detected_notes` directly:

- `backend/app/modules/pitch/pipeline.py:1056` to `backend/app/modules/pitch/pipeline.py:1064`

This reduces the previous double-fact problem.

### 4. Contract test covers raw-empty detector path

The new pipeline test proves:

- detector returns `[]`: `backend/tests/test_pitch_pipeline.py:416`
- F0 extractor returns valid `F0Track`: `backend/tests/test_pitch_pipeline.py:417`
- pipeline still produces one melody candidate: `backend/tests/test_pitch_pipeline.py:430`
- candidate has contour lineage and F0 frame range: `backend/tests/test_pitch_pipeline.py:432`
- authority marker is `note_candidate_set_v2`: `backend/tests/test_pitch_pipeline.py:434`
- selected lead note traces to candidate id: `backend/tests/test_pitch_pipeline.py:437`

This is a strong regression test and should remain a gate.

## Remaining Issue

### P1 Residual: ContourToCandidateBridge still mutates production detected_notes

The pipeline still does this:

```text
contour_bridge_result = self.contour_candidate_bridge.bridge(...)
detected_notes = contour_bridge_result.notes
```

Concrete lines:

- bridge call: `backend/app/modules/pitch/pipeline.py:969`
- mutation: `backend/app/modules/pitch/pipeline.py:974`

Then `detected_notes` still feeds melody source arbitration:

- `arrangement_decision = self.melody_arbitrator.decide(...)`: `backend/app/modules/pitch/pipeline.py:976`
- `rmvpe_candidate.notes=detected_notes`: `backend/app/modules/pitch/pipeline.py:982`

And the selected lead notes from that arbitration are still passed as raw evidence into `NoteCandidateBuilder`:

- `raw_notes=arrangement_decision.selected_lead_notes`: `backend/app/modules/pitch/pipeline.py:1003`

This means the production path is better, but not pure. `NoteCandidateSet v2` is now the selection input, but the raw evidence entering its builder can still be shaped by bridge mutation.

### Existing test confirms bridge still impacts production-visible output

`test_contour_to_candidate_bridge_runs_before_melody_selector_and_raw_artifact` still expects bridge-created notes in raw output and lead notes:

- test name: `backend/tests/test_pitch_pipeline.py:439`
- bridge note expected in `result.raw_notes`: `backend/tests/test_pitch_pipeline.py:520`
- bridge note expected in lead notes: `backend/tests/test_pitch_pipeline.py:527`

This is exactly why the proposed next cut is correct.

## Next Cut Recommendation

Move `ContourToCandidateBridge` to shadow diagnostics.

Required behavior:

```text
production candidates = NoteCandidateBuilder(F0Track, PitchContourSet, optional raw detector evidence)
bridge output = diagnostics only
bridge must not mutate detected_notes
bridge must not feed melody arbitration
bridge must not create selected melody notes
```

Implementation steps:

1. Replace `detected_notes = contour_bridge_result.notes` with immutable raw detector notes for production.
2. Keep `contour_bridge_result.summary` under diagnostics only.
3. Rename tests that expect bridge production mutation into legacy/shadow tests.
4. Add a new test proving bridge accepted candidates do not appear in `result.lead_notes` unless they also exist in authoritative `NoteCandidateSet v2`.
5. Ensure `NoteCandidateBuilder` contour-seed candidates are the only way F0 contours become production candidates.

## Final Assessment

This cut successfully moved melody selection toward `NoteCandidateSet v2` authority. It is not cosmetic.

But the next knife must remove bridge mutation from production. Until then, the upstream chain is still in a migration state:

```text
better: NoteCandidateSet v2 drives typed selection
not yet ideal: bridge still mutates detected_notes before candidate building/arbitration
```

The user's next proposed cut is exactly right.
