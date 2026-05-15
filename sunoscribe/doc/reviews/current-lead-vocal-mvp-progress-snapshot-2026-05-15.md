# Current Lead Vocal MVP Progress Snapshot (2026-05-15)

## Summary

Current status: late prototype / launchable-MVP migration.

The lower half of the lead-vocal path is now substantially hardened. The upper candidate authority path is partially reclaimed but not fully clean because `ContourToCandidateBridge` still mutates production `detected_notes` before candidate building/arbitration.

In plain terms:

```text
Done enough to trust: QuantizedNoteSet -> ScoreIR lineage
Mostly done: NoteCandidateSet v2 -> MelodySelection boundary
Not done: bridge shadow-only, artifact/revision/job production shell
```

## Completed Or Mostly Completed

### 1. F0 extraction has an explicit typed stage

`RMVPEF0Extractor` exists and emits `F0Track` without note segmentation or backend fallback masking.

Status: mostly complete for MVP pipeline internals.

Remaining: production model availability checks and persisted artifact metadata.

### 2. NoteCandidateSet v2 exists and can be built from F0/contours

`NoteCandidateBuilder` can produce contour-seed candidates with lineage even when raw detector notes are empty.

Evidence:

- pipeline candidate builder entry: `backend/app/modules/pitch/pipeline.py:418`
- builder call: `backend/app/modules/pitch/pipeline.py:425`
- raw-empty pipeline contract test: `backend/tests/test_pitch_pipeline.py:384`

Status: functionally present.

Remaining: make it the only upstream production candidate source by removing bridge mutation.

### 3. MelodySelection now consumes typed NoteCandidateSet v2 in pipeline

Evidence:

- typed selector call: `backend/app/modules/pitch/pipeline.py:449`
- selector v2 validation: `backend/app/modules/pitch/melody_selection_artifact.py:90`
- selector lineage contract failure: `backend/app/modules/pitch/melody_selection_artifact.py:229`

Status: selection boundary is mostly reclaimed.

Remaining: legacy selector bypasses still exist for tests/compatibility; production must avoid them.

### 4. Quantizer preserves lineage through merge/trim

Evidence:

- merge helper: `backend/app/modules/pitch/quantizer.py:117`
- trim helper: `backend/app/modules/pitch/quantizer.py:147`
- F0 range merge: `backend/app/modules/pitch/quantizer.py:278`

Status: P1 lineage break fixed.

### 5. ScoreIR consumes QuantizedNoteSet and hard-fails lineage breaks

Evidence:

- `quantized_notes_artifact` input: `backend/app/modules/score_ir/builder.py:35`
- quantized primary build: `backend/app/modules/score_ir/builder.py:39`
- hard fail: `backend/app/modules/score_ir/builder.py:141`
- AudioAnalysisService QuantizedNoteSet validation: `backend/app/services/audio_analysis_service.py:403`

Status: lower half is close to MVP-ready.

Remaining: actual ScoreRevision persistence/export binding.

## Not Yet Done

### 1. ContourToCandidateBridge still mutates production detected_notes

Evidence:

- pipeline still detects raw notes first: `backend/app/modules/pitch/pipeline.py:846`
- bridge still runs in production path: `backend/app/modules/pitch/pipeline.py:969`
- bridge result still overwrites `detected_notes`: `backend/app/modules/pitch/pipeline.py:974`
- those notes still feed melody source arbitration: `backend/app/modules/pitch/pipeline.py:976`

Status: not done.

This is the next blocking architectural cleanup before MVP launch.

### 2. Minimal Artifact persistence is not complete

There are docs and JSON artifacts, but no confirmed durable product-level artifact model/manifest binding the full chain for reload, audit, and downloads.

Status: not done for launch MVP.

Minimum needed:

- manifest or Artifact rows for F0, contours, candidates, selected melody, rhythm grid, quantized notes, ScoreIR, score_data, MIDI, MusicXML;
- producer/schema/source lineage in metadata;
- failure artifact.

### 3. Machine ScoreRevision is not confirmed complete

`ScoreIR` is stronger, but MVP still needs an immutable machine revision record as product state.

Status: not done or not verified in this review.

Minimum needed:

- machine revision id;
- project id;
- target `lead_vocal`;
- ScoreIR/score_data/export refs;
- source job id;
- immutable rerun semantics.

### 4. Async job wrapper is not complete

The MIR path still appears primarily service/pipeline oriented. MVP needs durable job status and failure reason.

Status: not done.

Minimum needed:

- create job;
- background execution;
- status endpoint or equivalent;
- persisted failure reason;
- cancellation or at least timeout/cleanup.

### 5. Fixture gate is not complete

There are strong unit tests, but no confirmed curated real-audio MVP gate.

Status: not done.

Minimum needed:

- clean vocal;
- vibrato;
- slide;
- accompaniment leakage;
- silent/no-vocal negative;
- short clip;
- 60-90 second clip.

## MVP Completion Estimate By Area

```text
F0 extraction stage:                  70%
F0 -> candidate builder:              75%
Candidate authority in pipeline:      65%
Melody selection typed boundary:      75%
QuantizedNoteSet lineage:             90%
ScoreIR lineage hard fail:            90%
Artifact persistence:                 25%
Machine ScoreRevision product state:  25%
Async job/status:                     20%
Frontend render/download MVP:         unknown/not verified
Fixture gate:                         20%
Production ops/security:              20%
```

Overall launchable MVP completion: roughly 45-55%.

The MIR core is ahead of the product/service shell. The next fastest path to MVP is not more model work; it is bridge shadowing plus durable revision/artifact/job shell.

## Next Three Cuts

### Cut 1: Bridge shadow diagnostics

- stop assigning `detected_notes = contour_bridge_result.notes`;
- keep bridge summary only under diagnostics;
- ensure bridge-created notes do not enter `lead_notes`;
- update legacy tests accordingly.

### Cut 2: Minimal persistence shell

- job workspace manifest;
- required artifact paths;
- immutable machine ScoreRevision JSON or DB row;
- exports tied to revision.

### Cut 3: Async job and fixture gate

- background job execution;
- status/failure persistence;
- 7 MVP fixtures;
- no-vocal negative must fail honestly.

## Launch Readiness Judgment

Not launchable yet.

It is close enough that a focused MVP hardening sprint can make it launchable, but only if scope remains narrow:

```text
lead_vocal only
no editing
no piano_score
no RVC
no PDF engraving
```

The immediate blocker is still candidate authority cleanup: `ContourToCandidateBridge` must stop mutating production melody data.
