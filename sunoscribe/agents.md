# SunoScribe Agents Guide

This document is the project-level guide for future agents and engineers working on SunoScribe. It captures the current architectural direction, MIR principles, data lineage, and the expected way to connect agent behavior into the product.

## Project Goal

SunoScribe should accept an audio or video file, extract the vocal melody, produce an editable lead-vocal score, export MIDI and MusicXML, render the score in the frontend, and later use the score and corrected F0 data to drive an external RVC cover workflow.

The first production milestone is intentionally narrow:

- Input: audio or video.
- Output: lead-vocal staff score, MIDI, MusicXML, frontend rendering, and downloadable artifacts.
- RVC: external service integration with ScoreIR-guided F0 correction.
- Deferred: full piano arrangement, full multi-track transcription, robust chord chart, structure labels, NMF/HPSS-based source decomposition.

## MIR Principles From `mirdoc.md`

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

All future work should preserve this typed artifact chain:

```text
Upload File
  -> MediaAsset
  -> CanonicalAudio
  -> StemSet
  -> F0Track
  -> NoteCandidateSet
  -> RhythmGrid
  -> ScoreRevision
  -> Export Artifacts
  -> Frontend Render/Edit
  -> CorrectedF0Track
  -> RVC Artifacts
```

Required stage contracts:

| Stage | Input | Output | Persistence | Consumers |
| --- | --- | --- | --- | --- |
| Upload | audio/video file | `MediaAsset` | `projects.audio_path`, source artifact | media ingest |
| Media ingest | `MediaAsset` | `CanonicalAudio` | `source.wav`, media metadata | separation, debug |
| Stem separation | `CanonicalAudio` | `StemSet` | `vocals.wav`, `accompaniment.wav`, manifest | F0, RVC, future harmony |
| F0 extraction | `vocals.wav` | `F0Track` | `f0_track.json`, debug image | notes, RVC |
| Note segmentation | `F0Track` | `NoteCandidateSet` | `note_candidates.json` | quantization |
| Rhythm analysis | `CanonicalAudio` or accompaniment | `RhythmGrid` | `rhythm_grid.json`, beat debug image | quantization |
| Quantization | notes + rhythm grid | quantized notes | intermediate JSON | ScoreIR |
| Score build | quantized notes + lyrics | `ScoreRevision` | database revision row | exports, frontend, RVC |
| Export | `ScoreRevision` | MIDI, MusicXML, view JSON | artifact rows and files | frontend, downloads |
| Edit | `ScoreRevision` + patch | new user revision | database revision row | exports, RVC |
| F0 correction | revision + original F0 | `CorrectedF0Track` | artifact row and JSON | RVC |
| RVC | vocals + corrected F0 + model | converted vocal | artifact row and WAV | mix |
| Mix | converted vocal + accompaniment | cover mix | artifact row and WAV | frontend |

Agents must not skip layers by reading arbitrary files or writing final outputs directly. Each stage should consume typed outputs from the previous stage.

## Architecture Boundaries

The current `AudioAnalysisService` is too broad for the target product. Future refactors should move toward these services:

- `MediaIngestService`: validates uploads, extracts audio from video, writes canonical WAV and metadata.
- `StemService`: performs vocal/accompaniment separation. In production, `vocals.wav` is required for the MVP.
- `MelodyTranscriptionService`: runs RMVPE on vocals and produces F0, voiced/unvoiced, confidence, and note candidates.
- `RhythmQuantizationService`: produces beat/downbeat grid and quantized note positions.
- `ScoreBuildService`: produces `ScoreIR` and `ScoreRevision`.
- `RenderExportService`: exports MIDI, MusicXML, and frontend view data from `ScoreRevision`.
- `RvcCoverService`: prepares corrected F0, calls an external RVC service, and mixes output with accompaniment.

`AnalysisIR` may later support harmony, structure, bassline, and form analysis, but it should not pollute the lead-vocal MVP with low-confidence baseline guesses.

## Required Repairs Before Agent Features

Before connecting a capable agent to user workflows, implement these foundations:

1. `Artifact` model
   - Store metadata for source media, canonical audio, stems, F0, debug images, MIDI, MusicXML, corrected F0, RVC vocal, and RVC mix.
   - Files may remain in the workspace initially and later move to MinIO.

2. `ScoreRevision` model
   - Keep machine and user revisions separate.
   - Never overwrite the machine transcription when a user or agent edits a score.
   - Exports should be generated from a specific revision.

3. `ScorePatch` schema
   - Agents must propose small, auditable edit operations rather than replacing the entire score.
   - Example operations: replace note pitch, adjust note duration, delete note, merge notes, bind lyric token.

4. Patch validator
   - Validate note IDs, pitch ranges, non-negative durations, measure consistency, lyric token references, and exportability.
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

RAG is not the preferred path because `mirdoc.md` is mostly stable project knowledge. Distill it into skills and validators so the agent follows fixed engineering rules instead of retrieving passages and improvising.

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

MVP:

- Media ingest for audio/video.
- Required vocal separation.
- RMVPE-based lead vocal F0.
- Rhythm grid and quantized lead melody.
- `ScoreRevision` and `Artifact`.
- MIDI and MusicXML export.
- OSMD frontend rendering.

Editing:

- `ScorePatch` operations.
- Patch validation.
- User revisions.
- Regenerate exports from selected revision.

RVC:

- External RVC service client.
- Gentle ScoreIR-guided F0 correction.
- Converted vocal and mix artifacts.

MIR expansion:

- Chord recognition with chroma, beat-synchronous chroma, HMM, and Viterbi.
- Structure analysis with SSM and novelty curve.
- Synchronization with CENS/chroma and DTW.
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
