# Lead Vocal Pipeline State and Next Step (2026-05-15)

## Current State

The lead-vocal path has moved past ad-hoc demo wiring but is not yet production-complete.

The strongest progress is at the downstream end of the chain:

```text
QuantizedNoteSet -> ScoreIR -> ScoreRevision
```

This segment now has a clearer production contract:

- `ScoreIRBuilder` can consume `QuantizedNoteSet` as the primary lead-note input.
- Quantizer merge and overlap trim preserve candidate, contour, and F0 frame lineage.
- The old post-build replacement path is disabled rather than silently repairing ScoreIR after the fact.
- Missing production lineage now fails hard instead of being reported as a warning.

This means the system is no longer merely creating a plausible score artifact. It is beginning to enforce traceable score construction.

## What Is Still Not Production-Complete

The upstream chain is still in a migration state:

```text
vocals.wav -> F0Track -> PitchContourSet -> NoteCandidateSet
```

The main unresolved architectural problem is that candidate production still carries legacy overlap between:

- RMVPE frame extraction,
- detector raw notes,
- contour bridge output,
- candidate builder output,
- selector heuristics.

The desired production shape is a single typed chain:

```text
vocals.wav
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet
  -> MelodySelection
  -> RhythmGrid
  -> QuantizedNoteSet
  -> LeadVocalScoreRevision
```

The current code is closer to that target than before, but the upstream section can still behave like multiple semi-authoritative sources feeding the later stages. That is the next production risk.

## System Maturity Assessment

Current maturity: late prototype / candidate-production migration.

It is not a toy pipeline anymore because:

- lineage is now a first-class contract in the lower half of the melody path;
- missing quantized lineage can hard fail;
- ScoreIR is being re-centered as the production score source;
- legacy post-hoc replacement has been isolated.

It is not production-grade yet because:

- `PitchDetector` legacy behavior still mixes F0 extraction and note segmentation responsibilities;
- `NoteCandidateSet` is not yet the only authoritative source for downstream melody selection in every path;
- failure semantics are stronger downstream than upstream;
- end-to-end contract tests still need to cover the full typed chain under real failure shapes, not only unit-level lineage cases.

## Recommended Next Step

The next cut should not add more selector heuristics. It should remove upstream ambiguity.

Priority order:

1. Make `F0Track -> PitchContourSet -> NoteCandidateSet` the authoritative candidate path.
2. Add contract tests that prove `NoteCandidateSet` can be produced from valid F0/contours even when detector raw notes are empty.
3. Ensure `MelodyTranscriptionService` persists the authoritative candidate set from that typed path and downstream stages consume that artifact only.
4. Add an end-to-end lineage test from candidate to final `ScoreNote`, including a merge or trim case.
5. Only after that, tighten failure semantics for missing or invalid upstream typed artifacts.

## Immediate Implementation Slice

The next small, reversible slice should be:

```text
F0Track fixture
  -> PitchContourSet fixture
  -> NoteCandidateBuilder
  -> NoteCandidateSet v2 contract test
```

The test must assert:

- raw detector notes may be empty;
- valid contours still produce candidates;
- each candidate has `source_contour_id`;
- each candidate has `source_f0_frame_range`;
- no fallback source such as debug MIDI, chroma, CREPE, or basic-pitch is involved.

After the contract test is red/green, wire the service persistence path so this candidate set becomes the artifact downstream consumers use.

## Hard Line

The system should prefer a clear failure over a plausible untraceable score. The next work should therefore reduce sources of truth, not improve heuristic polish.