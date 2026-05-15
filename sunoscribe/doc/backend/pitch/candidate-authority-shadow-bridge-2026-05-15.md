# Candidate Authority Shadow Bridge Cutover (2026-05-15)

## Decision

Lead-vocal production melody selection now treats `NoteCandidateSet v2` as the only authoritative candidate input. `ContourToCandidateBridge` remains available only as shadow diagnostics in `analysis_info`; its returned notes are not written back into `detected_notes`, `raw_notes`, or `lead_notes`.

## Production semantics

- `RMVPEF0Extractor.extract()` is required for lead-vocal F0. Detector artifact F0 is no longer used as a hidden fallback when extraction fails.
- Detector note segmentation is optional evidence. `raw_notes` are preserved for diagnostics and copied into `raw_detector_evidence`, but they are not passed as production raw candidates to `NoteCandidateBuilder`; production lead melody is selected from `NoteCandidateSet v2` built from authoritative `F0Track` and `PitchContourSet`.
- `ContourToCandidateBridge.bridge()` can still summarize accepted/rejected contour candidates, but this summary is labeled `shadow_diagnostics_only` and cannot mutate the production note stream.
- `MelodySelection` is invoked with `note_candidate_set_v2.notes` and no contour fallback input. The selector therefore cannot create production notes directly from `PitchContourSet`; contours must first become v2 candidates.
- Quantized measure notes retain `source_candidate_id`, `source_candidate_ids`, `source_contour_ids`, and `source_f0_frame_range` in measure payloads for downstream lineage checks.

## Failure semantics

- Missing or failed RMVPE F0 extraction raises `required_f0_extraction_failed:*`.
- Missing `note_candidate_set_v2` payload raises `note_candidate_authority_failed:*`.
- Candidates without candidate id, source candidate ids, contour ids, or F0 frame range are filtered before production selection and counted as `rejected_untraceable_candidate_count`.

## Tests

Updated `backend.tests.test_pitch_pipeline` to cover:

- bridge diagnostics are preserved but do not enter `result.raw_notes` or `result.lead_notes`;
- raw detector notes can be empty while valid F0/contours still produce candidate -> selected -> quantized output;
- ScoreIR notes can be traced back through `source_candidate_id` to a v2 candidate with contour ids and F0 frame range using the existing analysis-lead ScoreIR path.

Validation command:

```powershell
$env:PYTHONPATH='backend'; python -m unittest backend.tests.test_pitch_pipeline backend.tests.test_note_candidate_builder backend.tests.test_melody_selection_artifact backend.tests.test_quantizer backend.tests.test_score_ir_builder backend.tests.test_rmvpe_f0_extractor
```

Result: `Ran 65 tests ... OK`.

## Remaining MVP work

The next production cut should move the same lineage guarantee into the primary ScoreIR measure/quantized-note path instead of relying on the existing analysis-lead builder route for the ScoreIR contract test. That requires changing ScoreIR builder/schema files and is intentionally outside this worktree's allowed edit scope.

