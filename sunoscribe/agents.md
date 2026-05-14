# SunoScribe Agents Guide

This document is the project-level guide for future agents and engineers working on SunoScribe. It captures the current architectural direction, MIR principles, data lineage, and the expected way to connect agent behavior into the product.

## Project Goal

SunoScribe should accept an audio or video file, produce traceable editable score revisions, export MIDI and MusicXML, render the score in the frontend, and use typed MIR artifacts rather than raw backend output as product state.

The product now has two explicit transcription targets:

```text
transcription_target = "lead_vocal" | "piano_score"
```

`lead_vocal` remains the first narrow production route for vocal melody transcription and later RVC cover workflows:

- Input: audio or video.
- Output: lead-vocal staff score, MIDI, MusicXML, frontend rendering, and downloadable artifacts.
- RVC: external service integration with ScoreIR-guided F0 correction.

`piano_score` is a separate target for complete piano score or piano arrangement transcription:

- Input: audio or video, using full mix, accompaniment, or a piano stem depending on product mode.
- Output: polyphonic piano ScoreRevision, MIDI, MusicXML, frontend rendering, and downloadable artifacts.
- Required: polyphonic note transcription, rhythm grid, voice/hand assignment, and piano ScoreIR build.

Agents must not treat these targets as interchangeable. Lead-vocal F0 extraction cannot produce a complete piano score, and piano-score transcription cannot be evaluated with lead-vocal-only references.

See also:

- `doc/architecture/transcription-targets.md`
- `doc/architecture/piano-score-pipeline.md`

## MIR Principles From `doc/principles/mirdoc.md`

Agents must preserve these principles when proposing or implementing changes:

- Audio, MIDI, MusicXML, and sheet music are different representations. Do not treat one as a lossless substitute for another.
- The system needs an explicit semantic middle layer. `ScoreIR` is the center of the product, not a temporary export detail.
- Do not use chroma as note transcription. Chroma folds octaves and is suitable for harmony, synchronization, structure, and matching tasks.
- F0 extraction must account for voiced/unvoiced frames, octave errors, missing fundamentals, vibrato, slides, and confidence.
- Beat and downbeat errors contaminate quantization. Rhythm grid construction is a separate stage, not a side effect of pitch detection.
- Production MIR work requires visual diagnostics: waveform, spectrogram, F0 trajectory, note candidates, beat/downbeat, chroma, novelty curve, tempogram, and SSM where relevant.
- Do not judge by successful demos only. Keep failure cases and error categories visible.
- Do not silently fallback through required stages. If a required production dependency is unavailable, fail the task with a clear error.

## Data Lineage

All future work should preserve typed artifact chains. The shared prefix is:

```text
Upload File
  -> MediaAsset
  -> CanonicalAudio
  -> StemSet
  -> transcription_target switch
```

For `lead_vocal`:

```text
Vocal Stem
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet
  -> RhythmGrid
  -> LeadVocalScoreRevision
  -> Export Artifacts
  -> Frontend Render/Edit
  -> CorrectedF0Track
  -> RVC Artifacts
```

For `piano_score`:

```text
Selected Audio Stem or Full Mix
  -> PolyphonicNoteEventSet
  -> PianoVoiceSet
  -> RhythmGrid
  -> PianoScoreRevision
  -> Export Artifacts
  -> Frontend Render/Edit
```

Shared required stage contracts:

| Stage | Input | Output | Persistence | Consumers |
| --- | --- | --- | --- | --- |
| Upload | audio/video file | `MediaAsset` | `projects.audio_path`, source artifact | media ingest |
| Media ingest | `MediaAsset` | `CanonicalAudio` | `source.wav`, media metadata | stems, transcription, debug |
| Stem selection/separation | `CanonicalAudio` | `StemSet` | stems, manifest, diagnostics | target-specific transcription |
| Score build | target-specific typed artifacts | `ScoreRevision` | database revision row | exports, frontend, edits |
| Export | `ScoreRevision` | MIDI, MusicXML, view JSON | artifact rows and files | frontend, downloads |
| Edit | `ScoreRevision` + patch | new user revision | database revision row | exports, RVC where applicable |

Lead-vocal specific contracts:

| Stage | Input | Output | Persistence | Consumers |
| --- | --- | --- | --- | --- |
| F0 extraction | `vocals.wav` | `F0Track` | `f0_track.json`, debug image | contours, notes, RVC |
| Contour and notes | `F0Track` | `PitchContourSet`, `NoteCandidateSet` | JSON artifacts | selector, quantization, debug |
| F0 correction | revision + original F0 | `CorrectedF0Track` | artifact row and JSON | RVC |
| RVC | vocals + corrected F0 + model | converted vocal | artifact row and WAV | mix |

Piano-score specific contracts:

| Stage | Input | Output | Persistence | Consumers |
| --- | --- | --- | --- | --- |
| Polyphonic transcription | selected stem/full mix | `PolyphonicNoteEventSet` | JSON artifact, diagnostics | piano arrangement |
| Piano arrangement | polyphonic notes + rhythm grid | `PianoVoiceSet` | JSON artifact | piano score build |
| Piano score build | `PianoVoiceSet` | `PianoScoreRevision` | database revision row | exports, frontend |

Agents must not skip layers by reading arbitrary files or writing final outputs directly. Each stage should consume typed outputs from the previous stage.

## Architecture Boundaries

The current `AudioAnalysisService` is too broad for the target product. Future refactors should move toward target-aware services.

Shared services:

- `MediaIngestService`: validates uploads, extracts audio from video, writes canonical WAV and metadata.
- `StemService`: performs target-aware source separation or stem selection and persists manifests.
- `RenderExportService`: exports MIDI, MusicXML, and frontend view data from `ScoreRevision`.
- `ReferenceIngestService`: imports benchmark/reference MusicXML or MIDI and validates it against the selected target.

Lead-vocal services:

- `MelodyTranscriptionService`: runs RMVPE on vocals and produces F0, voiced/unvoiced, confidence, contours, and note candidates.
- `RhythmQuantizationService`: produces beat/downbeat grid and quantized lead melody positions.
- `ScoreBuildService`: produces lead-vocal `ScoreIR` and `ScoreRevision`.
- `RvcCoverService`: prepares corrected F0, calls an external RVC service, and mixes output with accompaniment.

Piano-score services:

- `PolyphonicTranscriptionService`: produces `PolyphonicNoteEventSet` from the selected audio source. It must not use chroma or lead-vocal F0 as piano note transcription.
- `PianoArrangementService`: groups polyphonic notes into voices, staves, hands, measures, and texture-aware notation.
- `PianoScoreBuildService`: produces piano `ScoreIR` and `PianoScoreRevision` from `PianoVoiceSet`.

`AnalysisIR` may later support harmony, structure, bassline, and form analysis, but it should not pollute either target with low-confidence baseline guesses.

Hard target boundaries:

- Do not use the lead-vocal F0 pipeline to generate complete piano scores.
- Do not silently downgrade `piano_score` to melody-only output.
- Do not evaluate lead-vocal output against piano-score references or piano-score output against lead-vocal references.
- Do not use reference MIDI, DTW, or debug attribution to repair production `ScoreRevision`.

## Required Repairs Before Agent Features

Before connecting a capable agent to user workflows, implement these foundations:

1. `Artifact` model
   - Store metadata for source media, canonical audio, stems, F0, polyphonic transcription intermediates, piano arrangement artifacts, debug images, MIDI, MusicXML, corrected F0, RVC vocal, and RVC mix.
   - Files may remain in the workspace initially and later move to MinIO.

2. `ScoreRevision` model
   - Keep machine and user revisions separate across both `lead_vocal` and `piano_score`.
   - Never overwrite the machine transcription when a user or agent edits a score.
   - Exports should be generated from a specific revision.

3. `ScorePatch` schema
   - Agents must propose small, auditable edit operations rather than replacing the entire score.
   - Example operations: replace note pitch, adjust note duration, delete note, merge notes, bind lyric token.

4. Patch validator
   - Validate note IDs, pitch ranges, non-negative durations, measure consistency, lyric token references, staff or voice consistency where relevant, and exportability.
   - Reject invalid patches before creating a new revision.

5. Debug artifacts
   - Produce development/admin-visible views for F0, notes, beat/downbeat, and separation quality.
   - Debug artifact failures can warn, but required production artifacts must fail explicitly.

## Agent Integration Strategy

Do not use a free-form agent for the audio-to-score pipeline. Do not use RAG as the primary control mechanism.

Use skill-driven, tool-constrained agents:

```text
deterministic MIR pipeline
  -> typed artifacts and ScoreRevision
  -> agent reads typed data
  -> agent proposes controlled action
  -> validator accepts or rejects
  -> service creates revision or job
```

Recommended skills:

- `skills/mir-transcription`: diagnose F0, voiced/unvoiced, octave errors, note segmentation, and rhythm issues.
- `skills/score-ir-editing`: propose and explain `ScorePatch` operations.
- `skills/debug-diagnosis`: read warnings and artifacts, classify failure causes, and recommend next actions.
- `skills/rvc-cover`: prepare RVC jobs using ScoreIR-guided F0 correction and external service constraints.

RAG is not the preferred path because `doc/principles/mirdoc.md` is mostly stable project knowledge. Distill it into skills and validators so the agent follows fixed engineering rules instead of retrieving passages and improvising.

## Agent Tool Rules

Allowed agent tools should be narrow and typed:

```text
read_score_revision(score_revision_id)
list_artifacts(project_id)
read_artifact_metadata(artifact_id)
diagnose_transcription(project_id)
propose_score_patch(score_ir, instruction)
validate_score_patch(score_ir, patch)
apply_score_patch(score_revision_id, patch)
regenerate_exports(score_revision_id)
prepare_rvc_job(project_id, score_revision_id, voice_model_id)
```

Agents must not:

- Directly modify database rows.
- Read arbitrary workspace files.
- Write MusicXML or MIDI directly.
- Call RVC directly.
- Bypass patch validation.
- Replace a full `ScoreIR` when a patch is sufficient.
- Hide required-stage failures behind fallback output.
- Treat debug warnings as successful production results.

## RVC Direction

RVC should be integrated as an external service, not embedded into the backend runtime.

Expected first version:

- Input: `vocals.wav`, `ScoreRevision`, original `F0Track`, selected voice model, transpose setting.
- Generate `CorrectedF0Track` by gently correcting note centers from ScoreIR while preserving natural slides and vibrato.
- Submit vocals and corrected F0 to the external RVC service.
- Persist converted vocals as an artifact.
- Mix converted vocals with accompaniment and persist the final cover artifact.

Do not start with MIDI-driven singing synthesis. That is a larger singing synthesis system and should not block the MVP.

## Frontend Direction

The frontend should use `React + Vite + TypeScript`.

For the MVP:

- Render MusicXML with OSMD.
- Show MIDI playback controls.
- Show task status and failure reasons.
- List generated artifacts.
- Allow light score editing through controlled patch operations.
- Save edits as new `ScoreRevision` rows.

Jianpu can be built later from `ScoreIR` view data. Staff notation and MIDI are the first priority.

## Backend Export Direction

Use `music21` for MusicXML generation rather than growing long-term hand-written XML logic. Hand-written XML may remain as a temporary compatibility path, but it should not be the long-term score engraving layer.

PDF is not a core MVP artifact. Current summary PDF behavior is not equivalent to score PDF. If score PDF is required later, use a proper engraving renderer such as MuseScore or Verovio through a dedicated service.

## Roadmap

Shared foundation:

- Media ingest for audio/video.
- `Artifact` and `ScoreRevision` models.
- Target-aware `ScoreIR` with explicit `score_type` or equivalent metadata.
- MIDI and MusicXML export from `ScoreRevision` only.
- OSMD frontend rendering and artifact listing.
- `ScorePatch`, patch validation, user revisions, and export regeneration.
- Target-aware benchmark references and `reference_suspect` diagnostics.

Lead-vocal MVP:

- Required vocal separation.
- RMVPE-based lead vocal F0.
- Pitch contours and conservative note candidates.
- Rhythm grid and quantized lead melody.
- Lead-vocal `ScoreRevision`.
- RVC external service client, corrected F0, converted vocal, and mix artifacts.

Piano-score MVP:

- `transcription_target="piano_score"` request path.
- Polyphonic transcription backend integration.
- `PolyphonicNoteEventSet` artifact.
- `PianoVoiceSet` with initial hand/voice assignment.
- Piano `ScoreRevision` and MusicXML/MIDI export.
- Piano-score benchmark fixtures using curated piano MusicXML or MIDI.

MIR expansion:

- Chord recognition with chroma, beat-synchronous chroma, HMM, and Viterbi.
- Structure analysis with SSM and novelty curve.
- Synchronization with CENS/chroma and DTW for diagnostics only.
- HPSS/NMF for source decomposition and future multi-track scoring.
- Fingerprint only if product requirements include retrieval, duplicate detection, or version identification.

## Review Checklist For Future Agents

Before changing code, verify:

- Which representation is being consumed and produced.
- Whether the change preserves data lineage.
- Whether required stages fail explicitly.
- Whether artifacts and revisions remain traceable.
- Whether agent output is validated before mutation.
- Whether the frontend can list and render the resulting artifacts.
- Whether tests or manual validation cover realistic audio failures, not only clean samples.



## No Silent Fallback Policy

Agents and services must not use low-quality fallback outputs to mask failures in required stages.

- If a required dependency (e.g., RMVPE model, vocal separation) is unavailable or fails, the task must fail explicitly with a clear diagnostic error.
- Do not silently degrade to alternative backends (e.g., CREPE, basic-pitch) in production.
- Do not produce approximate or guessed outputs (e.g., fake notes, placeholder scores) as if they were valid results.

Fallbacks are allowed only when:

- The stage is explicitly marked as optional, and
- The output is clearly labeled as optional or diagnostic.

The system should always prefer:

> correct failure + traceable diagnostics  
> over  
> seemingly successful but unreliable results



Agents should aim for the highest-quality result within defined system constraints,
but must not violate stage contracts, data lineage, or validation rules in pursuit of better output
