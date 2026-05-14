# Piano Score Pipeline

This document defines the `piano_score` transcription target. It is a separate MIR pipeline for complete piano score or piano arrangement transcription. It shares ingest, artifact governance, revisions, exports, and frontend rendering with `lead_vocal`, but it must not reuse the lead-vocal F0 pipeline as a substitute for polyphonic piano transcription.

## Goal

`piano_score` should produce an editable piano `ScoreRevision` and derive MIDI, MusicXML, and score view JSON from that revision only.

The target output is a piano staff score with polyphony, measures, rhythm, voices, and hand/staff assignment. It is not a lead-vocal melody score and not a raw detector MIDI dump.

## Required Artifact Chain

```text
Upload File
  -> MediaAsset
  -> CanonicalAudio
  -> StemSet or SelectedAudioSource
  -> PolyphonicNoteEventSet
  -> PianoVoiceSet
  -> RhythmGrid
  -> PianoScoreRevision
  -> Export Artifacts
  -> Frontend Render/Edit
```

`StemSet` can contain piano, accompaniment, vocals, drums, or other separated stems depending on the selected backend. If no reliable piano stem is available and the configured mode requires one, the task must fail explicitly. Full-mix transcription is allowed only when the task profile explicitly requests full-mix piano scoring.

## Artifact Contracts

| Stage | Input | Output | Required Metadata | Consumers |
| --- | --- | --- | --- | --- |
| Media ingest | `MediaAsset` | `CanonicalAudio` | sample rate, duration, channels, source hash | stems, transcription |
| Source selection | `CanonicalAudio`, `StemSet` | `SelectedAudioSource` | selected source role, backend, quality diagnostics | polyphonic transcription |
| Polyphonic transcription | selected audio | `PolyphonicNoteEventSet` | onset, offset, pitch, velocity, confidence, backend, source frames | arrangement, benchmark |
| Rhythm analysis | `CanonicalAudio` or selected audio | `RhythmGrid` | beats, downbeats, tempo map, confidence | quantization, arrangement |
| Piano arrangement | notes + rhythm grid | `PianoVoiceSet` | voice id, staff, hand, measure positions, texture evidence | score build |
| Score build | `PianoVoiceSet` | `PianoScoreRevision` | score type, source artifact ids, warnings | export, frontend |
| Export | `ScoreRevision` | MIDI, MusicXML, view JSON | source revision id, export backend | downloads, OSMD |

## Service Boundaries

### `PolyphonicTranscriptionService`

Responsibilities:

- Run a production polyphonic transcription backend on the selected audio source.
- Produce `PolyphonicNoteEventSet` with overlapping note events.
- Preserve confidence, onset/offset evidence, pitch evidence, backend metadata, and diagnostic warnings.
- Fail explicitly when the configured backend, model, or required source artifact is unavailable.

Non-goals:

- It must not emit final MusicXML or final MIDI directly.
- It must not collapse polyphony into a single melody line.
- It must not use chroma as note transcription.
- It must not silently fall back to lead-vocal F0 extraction.

### `PianoArrangementService`

Responsibilities:

- Quantize polyphonic note events against `RhythmGrid`.
- Group notes into voices, staves, and hands.
- Detect and represent chords, repeated notes, arpeggios, sustained notes, rests, and texture changes.
- Produce `PianoVoiceSet` as the typed input for score building.

Non-goals:

- It must not invent missing notes to satisfy score density.
- It must not hide transcription uncertainty behind clean-looking notation.
- It must not use benchmark reference MIDI, DTW, or debug artifacts to repair production output.

### `PianoScoreBuildService`

Responsibilities:

- Convert `PianoVoiceSet` into piano `ScoreIR`.
- Persist a machine `ScoreRevision` with `score_type="piano_score"` or equivalent target metadata.
- Attach warnings and diagnostics without mutating source artifacts.
- Hand off exports to `RenderExportService`.

Non-goals:

- It must not overwrite lead-vocal revisions.
- It must not export directly without a revision.
- It must not replace a user revision when regenerating machine output.

## Hard Constraints

- Do not use `F0Track` as the main piano transcription representation.
- Do not use chroma as note transcription; chroma may support harmony, matching, structure, or diagnostics only.
- Do not pass `raw_pitch.mid`, debug MIDI, backend MIDI, or temporary transcription MIDI directly to final exports.
- Do not use reference MIDI, DTW alignment, or benchmark attribution to repair production `ScoreRevision`.
- Do not silently downgrade `piano_score` to `lead_vocal` when a polyphonic backend fails.
- Do not silently downgrade complete piano score output to melody-only output.
- MIDI, MusicXML, and score view JSON must be regenerated from a specific `ScoreRevision`.

## Failure Policy

Required-stage failures must fail the task clearly:

- media ingest failure;
- required source separation or source selection failure;
- configured polyphonic transcription backend unavailable;
- `PolyphonicNoteEventSet` cannot be produced;
- rhythm grid unavailable when the selected profile requires quantized notation;
- `PianoVoiceSet` cannot be built;
- `PianoScoreRevision` cannot be persisted;
- export from revision fails.

Debug artifact failures may warn only when the required production artifact was successfully produced.

## Benchmark and Reference Requirements

A `piano_score` benchmark needs piano-score ground truth.

Acceptable references:

- curated piano MusicXML;
- clean piano MIDI with left/right hand or voice metadata where available;
- manually validated piano arrangement notes.

Suspect references:

- lead-vocal melody only;
- full-band MIDI with non-piano tracks mixed into the target;
- auto-generated or unvalidated OMR output;
- piano reductions that substantially differ from the source audio arrangement;
- lead sheets that omit accompaniment texture.

Benchmark diagnostics should report:

- polyphonic precision and recall;
- onset and offset error distributions;
- voice/hand assignment quality where reference supports it;
- measure-level rhythm consistency;
- missing dense texture vs. hallucinated dense texture;
- reference-suspect warnings separately from production failure warnings.

## First Implementation Slice

A safe first implementation should be narrow:

1. Add `transcription_target="piano_score"` request metadata.
2. Persist `PolyphonicNoteEventSet` as an artifact from a configured backend.
3. Build a minimal `PianoVoiceSet` with simple treble/bass split heuristics and explicit uncertainty.
4. Build `PianoScoreRevision` from `PianoVoiceSet`.
5. Export MIDI and MusicXML from that revision only.
6. Add benchmark fixtures with curated piano MusicXML or piano MIDI references.

This first slice should prefer explicit failure and visible diagnostics over polished but unreliable piano notation.
