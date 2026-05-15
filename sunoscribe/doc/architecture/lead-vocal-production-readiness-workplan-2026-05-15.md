# Lead Vocal Production Readiness Workplan (2026-05-15)

## Executive Judgment

SunoScribe lead-vocal transcription is now in late prototype / candidate-production migration. It has moved beyond demo wiring, but it is not yet a production online service.

To become production-grade, the project must finish four hard things:

1. Collapse the MIR pipeline into one typed authoritative artifact chain.
2. Persist every required artifact and ScoreRevision with lineage and failure semantics.
3. Add operational job control, observability, reproducibility, and rollback.
4. Validate quality with real audio fixtures and error budgets, not only unit tests.

The highest-risk gap remains upstream candidate authority:

```text
F0Track -> PitchContourSet -> NoteCandidateSet
```

Until `NoteCandidateSet v2` is the only source accepted by melody selection, the service can still produce plausible but architecturally ambiguous scores.

## Production Definition

A production online service means:

- every user request has a durable job id;
- every required stage has explicit input/output artifacts;
- every failure is classified and visible to user/admin tooling;
- every generated ScoreRevision can be traced back to typed MIR artifacts;
- no required stage silently falls back to low-quality alternatives;
- exports are regenerated from ScoreRevision, not random intermediate files;
- the system is observable, reproducible, and safe under concurrent traffic;
- quality is measured against curated fixtures and monitored after deployment.

A successful request must produce this chain:

```text
Upload
  -> MediaAsset
  -> CanonicalAudio
  -> StemSet
  -> VocalStem
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet
  -> MelodySelection
  -> RhythmGrid
  -> QuantizedNoteSet
  -> LeadVocalScoreRevision
  -> MIDI/MusicXML/frontend score_data
```

Each arrow must be durable, typed, validated, and diagnosable.

## Phase 1: Finish The Authoritative Lead-Vocal MIR Chain

### 1. Make NoteCandidateSet the only melody candidate source

Current risk: `PitchPipeline` still carries detector notes, contour bridge output, and candidate builder output as semi-authoritative sources.

Required work:

- Make `RMVPEF0Extractor -> PitchContourBuilder -> NoteCandidateBuilder` the main lead-vocal candidate path.
- Make `NoteCandidateSet v2` the only input accepted by melody selection.
- Treat detector raw notes as optional evidence only, never as production melody candidates.
- Move `ContourToCandidateBridge` to legacy/shadow compare mode.
- Ensure persisted `note_candidates.json` is the exact artifact downstream uses.

Acceptance tests:

- raw detector notes empty + valid F0/contours => candidate set exists and has full lineage;
- selector cannot run without `NoteCandidateSet v2`;
- quantized notes trace to candidate ids from the persisted candidate artifact;
- ScoreNote traces back to the same candidate id, contour id, and F0 frame range.

### 2. Split services by stage

Current risk: `PitchPipeline` and `AudioAnalysisService` still do too much orchestration and artifact mixing.

Required production service boundaries:

```text
MediaIngestService
StemService
F0ExtractionService
PitchContourService
NoteCandidateService
MelodySelectionService
RhythmGridService
QuantizedNoteService
LeadVocalScoreBuildService
RenderExportService
```

Rules:

- each service consumes typed artifacts, not arbitrary dicts where avoidable;
- each service emits one primary typed artifact;
- each service can be tested with persisted fixtures;
- each service has explicit failure reason codes.

### 3. Harden candidate model semantics

Current candidate model is usable but still MVP-level.

Required additions:

- onset/offset uncertainty;
- pitch center and pitch distribution summary;
- octave alternative candidates;
- segmentation alternatives;
- candidate scoring/ranking components;
- explicit rejected candidate records;
- reason codes for glide, vibrato, low confidence, short duration, out-of-range, unstable contour.

Do not overfit selector heuristics before this model is stable.

## Phase 2: Persistence, Artifacts, And Revisions

### 1. Add durable Artifact model

Each intermediate output must be an artifact row or equivalent durable record.

Required artifact types:

- source upload;
- canonical audio;
- stem manifest and stem WAVs;
- F0Track JSON;
- F0 debug plot;
- PitchContourSet JSON;
- NoteCandidateSet JSON;
- MelodySelection JSON;
- RhythmGrid JSON;
- QuantizedNoteSet JSON;
- ScoreIR JSON;
- MusicXML;
- MIDI;
- frontend score_data;
- diagnostic package.

Each artifact needs:

- artifact id;
- project id/job id;
- artifact type;
- schema version;
- source artifact ids;
- file path/object key;
- checksum;
- created timestamp;
- producer version/config hash;
- validation status;
- failure/warning summary if applicable.

### 2. Add ScoreRevision as product state

Production must not treat raw ScoreIR or MusicXML as the mutable source.

Required semantics:

- machine revision and user revisions are separate;
- original machine transcription is immutable;
- edits create new revisions;
- exports are tied to a specific revision;
- RVC correction later consumes a specific revision, not latest random state.

### 3. Add ScorePatch and validation

Agents/users should not replace whole scores casually.

Patch operations should include:

- replace note pitch;
- adjust note timing/duration;
- delete note;
- split/merge note;
- bind lyric token;
- mark ornament/tie candidate;
- adjust measure assignment where valid.

Patch validator must reject:

- unknown note ids;
- negative durations;
- invalid pitch ranges;
- measure inconsistency;
- export-breaking structures;
- losing lineage unless explicitly allowed for manual edits with provenance.

## Phase 3: Failure Semantics And No Silent Fallback

### Required stage failures

The service must fail clearly for:

- upload invalid;
- media ingest failed;
- canonical WAV unavailable;
- vocal stem unavailable;
- RMVPE model unavailable;
- F0Track empty;
- F0Track mostly unvoiced;
- PitchContourSet empty despite voiced F0;
- NoteCandidateSet empty despite valid contours;
- MelodySelection empty;
- RhythmGrid unavailable;
- QuantizedNoteSet empty;
- ScoreIR lineage contract failed;
- export generation failed.

### Fallback policy

Allowed:

- optional diagnostics can fail with warnings;
- legacy/shadow comparison can run without affecting production artifacts.

Forbidden:

- CREPE/basic-pitch silently replacing required RMVPE F0;
- chroma treated as note transcription;
- debug MIDI used to repair production ScoreIR;
- post-build score replacement to hide builder failure;
- raw detector notes used as final melody candidates when NoteCandidateSet is required.

## Phase 4: Quality Validation

### Fixture suite

Build a curated fixture set:

- clean lead vocal monophonic;
- vocal with vibrato;
- vocal with slides/glissando;
- breathy/low-confidence vocals;
- male/female range extremes;
- octave-error-prone material;
- vocal with dense accompaniment leakage;
- short clips and long clips;
- silent/no vocal sections;
- non-vocal audio as negative cases.

Each fixture should include expected diagnostics and approximate reference melody where available.

### Metrics

Track at least:

- F0 voiced frame coverage;
- gross pitch error rate;
- octave error rate;
- candidate recall/precision against reference notes;
- onset/offset median error;
- note F1;
- quantization measure alignment error;
- ScoreIR lineage completeness;
- export success rate;
- user-visible failure category distribution.

### Golden regression gates

A build should not ship if:

- required lineage completeness < 100% on successful cases;
- successful cases produce ScoreIR without matching QuantizedNoteSet;
- known no-vocal fixtures produce fake notes;
- model missing cases do not hard fail;
- export success regresses;
- fixture note F1 drops beyond agreed tolerance.

## Phase 5: Online Job System

### Job orchestration

Production request should be asynchronous:

```text
POST /projects/{id}/transcriptions
  -> create job
  -> queue stages
  -> stream or poll status
  -> persist artifacts and revision
```

Job state machine:

```text
queued
running_media_ingest
running_stem_separation
running_f0_extraction
running_candidate_generation
running_selection_quantization
running_score_build
running_export
succeeded
failed
cancelled
```

Required job features:

- idempotency key;
- cancellation;
- retry policy for safe stages;
- timeout per stage;
- progress events;
- structured failure payload;
- durable logs/artifact links.

### Concurrency and resource control

MIR stages are expensive. Production needs:

- worker queue;
- CPU/GPU resource limits;
- model warmup lifecycle;
- max upload duration/size;
- per-user/project quotas;
- temp file cleanup;
- deterministic workspace layout per job.

## Phase 6: Observability And Debuggability

### Structured logs

Every stage log should include:

- request id;
- job id;
- project id;
- stage name;
- artifact ids;
- model/config versions;
- duration;
- failure reason code;
- warning reason codes.

### Metrics

Track:

- job success/failure rate by stage;
- median/p95 runtime by stage;
- artifact validation failure rate;
- model load failures;
- no-vocal/F0-empty rates;
- ScoreIR lineage hard-fail rate;
- export failure rate.

### Debug package

Admin/dev debug package should include:

- waveform;
- spectrogram;
- F0 trajectory;
- vocal activity;
- pitch contours;
- note candidates;
- rejected candidates;
- selected melody;
- beat/downbeat grid;
- quantized notes;
- ScoreIR issue spots;
- all reason codes.

## Phase 7: API And Frontend Contract

### API requirements

Frontend needs endpoints for:

- create transcription job;
- get job status;
- list artifacts;
- get ScoreRevision;
- get score_data;
- download MIDI/MusicXML;
- get debug summary;
- apply ScorePatch;
- regenerate exports for revision.

### User-facing failure display

Do not show generic “analysis failed”.

Examples:

- “No lead vocal detected in selected stem.”
- “F0 extraction model unavailable.”
- “Pitch contours were too unstable to form note candidates.”
- “Beat grid could not be built reliably.”
- “Score build failed because candidate lineage was incomplete.”

## Phase 8: Security, Safety, And Storage

Required before public production:

- upload MIME validation and size limits;
- audio/video decoding sandbox strategy;
- path traversal protection;
- per-job isolated workspace;
- cleanup policy for temp files;
- object storage lifecycle policy;
- user/project authorization on artifacts and revisions;
- rate limits;
- dependency vulnerability scanning;
- model file integrity checks.

## Phase 9: Deployment Readiness

Production deployment needs:

- pinned Python dependencies;
- reproducible model artifact download/build process;
- environment variable validation at startup;
- health checks for API, worker, storage, database, and model availability;
- database migrations;
- backup/restore plan;
- canary deployment;
- rollback plan;
- staged feature flags for legacy vs v2 pipeline;
- runbooks for common failures.

## Immediate 3-Sprint Plan

### Sprint 1: Upstream candidate authority

Deliverables:

- service/pipeline contract test for raw-empty + valid F0/contour candidate generation;
- authoritative `NoteCandidateSet v2` persisted artifact;
- melody selection consumes `NoteCandidateSet v2` only;
- contour bridge moved to shadow/legacy;
- candidate -> selected -> quantized -> ScoreIR lineage test including merge/trim.

Exit criteria:

- no successful lead-vocal ScoreIR can be built without persisted NoteCandidateSet lineage;
- raw detector notes are optional evidence only.

### Sprint 2: Artifact and revision foundation

Deliverables:

- Artifact model and storage manifest;
- ScoreRevision model;
- export artifacts tied to revision;
- no direct MusicXML/MIDI product state from intermediate files;
- job status includes artifact ids and failure reason.

Exit criteria:

- user can reload a project and see the same revision/artifacts without rerunning MIR;
- exports are reproducible from ScoreRevision.

### Sprint 3: Production job runner and fixture gate

Deliverables:

- async job runner;
- stage status and cancellation;
- fixture regression suite;
- debug package generation;
- p95 runtime and failure metrics;
- no-silent-fallback integration tests.

Exit criteria:

- a staged environment can process multiple jobs with durable artifacts and visible failures;
- fixture gate blocks regressions.

## Hard Non-Negotiables

Do not go production if any of these are false:

- `NoteCandidateSet v2` is not the sole melody candidate source.
- `ScoreRevision` does not exist or can be overwritten by machine reruns.
- Required artifact failures are hidden behind fallback outputs.
- A successful ScoreNote cannot trace back to candidate, contour, and F0 frames.
- Exports are not tied to a specific ScoreRevision.
- There is no curated audio fixture regression gate.
- Job execution is synchronous, unbounded, and not recoverable.

## Final Recommendation

The fastest honest route to production is not adding more MIR tricks. It is making the existing narrow lead-vocal path deterministic, typed, persistent, observable, and failure-honest.

The next engineering milestone should be named:

```text
Lead Vocal Candidate Authority Milestone
```

Until that milestone is complete, the system remains a strong prototype with production-shaped lower layers, not a production service.
