---
name: mir-transcription
description: Lead-vocal MIR transcription guidance for SunoScribe. Use when designing, reviewing, or modifying media ingest, vocal separation, RMVPE/F0 extraction, voiced/unvoiced handling, note segmentation, beat/downbeat analysis, quantization, ScoreIR transcription, MIDI export, MusicXML export, or any audio/video-to-score pipeline behavior.
---

# MIR Transcription

Use this skill to keep SunoScribe transcription work aligned with the MIR principles distilled from `doc/principles/mirdoc.md`.

## Core Rule

Preserve the representation chain:

```text
MediaAsset -> CanonicalAudio -> StemSet -> F0Track -> NoteCandidateSet -> RhythmGrid -> ScoreRevision -> Artifacts
```

Do not collapse the chain into `audio -> MIDI` or `audio -> MusicXML`. Each stage must consume typed input and produce typed output.

## Required Workflow

1. Identify the representation being changed.
   - Audio waveforms preserve sound but not note labels.
   - F0 tracks preserve pitch evidence but not score rhythm.
   - MIDI preserves events but not score notation semantics.
   - MusicXML preserves notation semantics but is not the analysis source of truth.

2. Keep vocal melody transcription separate from harmony analysis.
   - Use vocals for lead F0.
   - Use accompaniment/mix later for chord, chroma, structure, or rhythm support.
   - Do not use chroma as note transcription; chroma folds octaves.

3. Treat RMVPE/F0 output as evidence, not final notes.
   - Preserve continuous F0, voiced/unvoiced state, confidence, and timestamps.
   - Detect likely octave errors before quantization.
   - Keep slides and vibrato visible in debug artifacts.

4. Build rhythm independently.
   - Beat/downbeat analysis must produce a `RhythmGrid`.
   - Quantization must consume `NoteCandidateSet + RhythmGrid`.
   - Low downbeat confidence should surface as a warning or issue, not hidden correction.

5. Generate score from `ScoreIR` or `ScoreRevision`.
   - MIDI and MusicXML must derive from the same semantic revision.
   - Do not let export code invent musical decisions that are absent from ScoreIR.

## Production Constraints

- Required production stages fail explicitly.
- Missing RMVPE runtime/model is not a successful transcription.
- Vocal separation failure is not a successful lead-vocal MVP.
- Debug artifact failures may warn, but required musical artifacts must not be faked.
- Baseline harmony, structure, or bass guesses must not pollute the lead-vocal MVP.

## Debug Artifacts To Preserve

For meaningful diagnosis, prefer generating or consuming:

- waveform
- spectrogram
- vocals/accompaniment previews
- F0 trajectory with voiced/unvoiced regions
- note candidate timeline
- beat/downbeat grid
- quantized note overlay
- MIDI/MusicXML export metadata

## Review Checklist

Before accepting a transcription change, confirm:

- The input and output representations are explicit.
- F0 evidence remains available after note segmentation.
- Rhythm grid is independent and inspectable.
- Quantization errors can be traced to F0, beat, downbeat, or note segmentation.
- Exports are generated from ScoreIR, not ad hoc from unrelated intermediate data.
