# Lead Vocal Launchable MVP Scope (2026-05-15)

## One-Line Judgment

A launchable MVP is not the full production platform. It is a narrow, honest lead-vocal transcription service that can accept one audio/video file, run the deterministic lead-vocal pipeline, persist a machine ScoreRevision and exports, and clearly fail when required MIR stages fail.

MVP goal:

```text
upload audio/video
  -> canonical audio
  -> vocal stem or selected vocal audio
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet v2
  -> MelodySelection
  -> RhythmGrid
  -> QuantizedNoteSet
  -> machine LeadVocalScoreRevision
  -> MIDI + MusicXML + frontend score_data
```

MVP does not mean perfect transcription. It means traceable output or honest failure.

## MVP Must-Haves

### 1. One target only: lead_vocal

MVP should support only:

```text
transcription_target = lead_vocal
```

Do not ship `piano_score` as part of this MVP. Do not silently downgrade piano requests to lead melody.

### 2. Candidate authority must be closed

This is the most important MIR requirement before launch.

MVP must enforce:

- `NoteCandidateSet v2` is the only source accepted by melody selection;
- `ContourToCandidateBridge` is diagnostics/shadow only;
- raw detector notes are optional evidence, not authoritative candidates;
- every successful selected/quantized/score note traces to candidate, contour, and F0 frame range.

If this is not true, do not launch.

### 3. Minimal artifact persistence

Full artifact platform can come later, but MVP needs durable files and metadata for the core chain.

Required persisted artifacts:

- uploaded source file path/metadata;
- canonical WAV;
- vocal stem or selected vocal audio;
- `f0_track.json`;
- `pitch_contours.json`;
- `note_candidates.json`;
- `selected_melody.json`;
- `rhythm_grid.json`;
- `quantized_notes.json`;
- `score_ir.json`;
- `score_data.json`;
- `output.mid`;
- `output.musicxml`;
- `failure.json` when failed.

A database `Artifact` table is ideal, but MVP can begin with a manifest JSON if it is durable and tied to a job/project id.

Minimum manifest fields:

```json
{
  "job_id": "...",
  "project_id": "...",
  "target": "lead_vocal",
  "status": "succeeded|failed",
  "artifacts": [
    {
      "type": "note_candidates",
      "schema_version": "note_candidate_set_v2",
      "path": "...",
      "producer": "...",
      "source_artifacts": ["f0_track", "pitch_contours"]
    }
  ]
}
```

### 4. Minimal ScoreRevision

MVP needs a real machine revision. It does not need full collaborative editing on day one.

Required fields:

- `revision_id`;
- `project_id`;
- `revision_type = machine`;
- `transcription_target = lead_vocal`;
- `score_ir_path` or `score_ir_json`;
- `score_data_path` or `score_data_json`;
- `midi_artifact_path`;
- `musicxml_artifact_path`;
- `source_job_id`;
- `created_at`;
- immutable after creation.

MVP rule:

```text
Exports must come from ScoreRevision, not arbitrary pipeline files.
```

User editing and ScorePatch can be post-MVP, but the machine revision must not be overwritten by reruns.

### 5. Async job, but simple

MVP should not block an HTTP request until MIR finishes.

Minimum job states:

```text
queued
running
succeeded
failed
cancelled
```

Minimum endpoints:

```text
POST /projects/{project_id}/transcriptions
GET  /jobs/{job_id}
GET  /projects/{project_id}/revisions/{revision_id}
GET  /projects/{project_id}/artifacts
GET  /artifacts/{artifact_id or path}/download
```

If full queue infra is not ready, MVP can use a single background worker process. But it must still persist job status and failure reason.

### 6. Honest failure semantics

MVP must fail clearly for required stages:

- invalid upload;
- media ingest failed;
- vocal stem missing if separation is required;
- RMVPE model unavailable;
- F0Track empty;
- PitchContourSet empty despite voiced F0;
- NoteCandidateSet empty;
- MelodySelection empty;
- QuantizedNoteSet empty;
- ScoreIR lineage contract failed;
- MIDI/MusicXML export failed.

User-facing failure examples:

```text
No lead vocal could be extracted.
F0 extraction model is unavailable.
Pitch contours were too unstable to form note candidates.
No traceable melody candidates were produced.
Score build failed because candidate lineage was incomplete.
```

No silent fallback in required stages.

### 7. Minimal frontend

MVP frontend only needs:

- upload file;
- show job progress/status;
- show clear failure reason;
- render MusicXML with OSMD;
- play/download MIDI;
- download MusicXML;
- show artifact list for admin/dev mode.

No need for full editing UI in launchable MVP.

### 8. Minimal fixture gate

Before launch, have a small curated fixture set, not a huge benchmark suite.

Minimum fixtures:

1. clean monophonic vocal;
2. vocal with vibrato;
3. vocal with slide/glissando;
4. vocal with accompaniment leakage;
5. no-vocal/silent negative case;
6. short clip under 15 seconds;
7. longer clip around 60-90 seconds.

MVP gates:

- successful fixtures produce ScoreRevision + MIDI + MusicXML;
- negative/no-vocal fixture fails, not fake score;
- all successful ScoreNotes have candidate/contour/F0 lineage;
- exports open in the frontend renderer;
- runtime is within acceptable p95 for file length.

### 9. Minimal operations

MVP ops requirements:

- max upload size and duration limit;
- isolated per-job workspace;
- temp cleanup;
- structured logs with job id and stage;
- model availability checked at startup or first job;
- basic auth/project authorization;
- backup for revision/artifact metadata;
- admin can inspect failure.json and core artifacts.

## Explicit Non-Goals For MVP

Do not include these in launchable MVP unless already finished:

- piano_score transcription;
- full ScorePatch editing system;
- RVC cover generation;
- PDF score engraving;
- collaborative editing;
- advanced agent editing;
- chord/form analysis as product truth;
- perfect lyric alignment;
- polyphonic arrangement;
- full object storage migration if local durable storage is acceptable for first deployment.

## Launch Blockers

Do not launch if any are true:

- `ContourToCandidateBridge` still mutates production melody candidates;
- selector can consume `selected_notes` or `pitch_contours` as production bypass instead of `NoteCandidateSet v2`;
- successful ScoreNotes lack `source_candidate_id/source_candidate_ids`, `source_contour_ids`, or `source_f0_frame_range`;
- ScoreRevision is missing or can be overwritten;
- MIDI/MusicXML are produced from intermediate state instead of ScoreRevision;
- job failure reason is not persisted;
- no-vocal fixture produces fake notes;
- RMVPE missing falls back silently to another backend;
- frontend cannot render the generated MusicXML;
- long-running jobs block API request threads.

## MVP Implementation Order

### Step 1: Finish candidate authority

- Move `ContourToCandidateBridge` to shadow diagnostics.
- Assert selector input is always `NoteCandidateSet v2`.
- Add end-to-end test: raw empty + valid F0/contour -> ScoreRevision with lineage.

### Step 2: Minimal revision/artifact persistence

- Add job workspace manifest.
- Add machine ScoreRevision record or durable JSON equivalent.
- Persist required artifacts and exports.
- Ensure rerun creates a new machine revision or new job output, never overwrites prior machine revision.

### Step 3: Async job wrapper

- Create transcription job endpoint.
- Run pipeline in worker/background task.
- Persist status and failure reason.
- Add status endpoint.

### Step 4: Export and frontend render

- Generate MIDI/MusicXML from ScoreRevision.
- Render MusicXML via OSMD.
- Provide downloads.

### Step 5: Fixture gate and deploy hardening

- Build the 7-fixture MVP suite.
- Add no-silent-fallback tests.
- Add basic logs, cleanup, upload limits, model availability check.

## MVP Acceptance Checklist

A build is launchable only if this manual test passes:

1. Upload a clean vocal clip.
2. Job progresses to succeeded.
3. Artifacts list includes F0, contours, candidates, selected melody, rhythm grid, quantized notes, ScoreIR, MIDI, MusicXML.
4. A machine ScoreRevision exists.
5. Frontend renders the MusicXML.
6. MIDI downloads and plays.
7. Pick any visible note and trace it back to candidate id, contour id, and F0 frame range.
8. Upload a no-vocal clip.
9. Job fails with a clear no-vocal/F0/candidate reason and produces no fake score.
10. Restart service and reload project: revision and downloads still exist.

## Final MVP Definition

Launchable MVP is:

```text
one target: lead_vocal
one honest pipeline: typed MIR artifacts -> machine ScoreRevision -> MIDI/MusicXML/render
one job system: async status + durable failure
one quality gate: small real-audio fixture suite
```

If you do only one thing before launch, finish candidate authority. If you do two things, add immutable machine ScoreRevision. If you do three, wrap it in async jobs with persisted status.
