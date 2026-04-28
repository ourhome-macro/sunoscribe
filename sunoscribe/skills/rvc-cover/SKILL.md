---
name: rvc-cover
description: RVC cover workflow guidance for SunoScribe. Use when designing, implementing, or reviewing external RVC service integration, ScoreIR-guided F0 correction, converted vocal artifacts, accompaniment mixing, RVC task APIs, voice model selection, transpose behavior, or RVC quality diagnosis.
---

# RVC Cover

Use this skill when connecting SunoScribe score analysis to an RVC cover workflow.

## Core Rule

RVC is an external service. Do not embed RVC inference into the main backend runtime for the MVP.

```text
vocals.wav + ScoreRevision + F0Track
  -> CorrectedF0Track
  -> external RVC job
  -> converted_vocals.wav
  -> mix with accompaniment.wav
  -> rvc_mix.wav
```

## Inputs

The first production RVC flow should consume:

- `vocals.wav`
- `accompaniment.wav`
- selected `ScoreRevision`
- original `F0Track`
- selected `voice_model_id`
- optional transpose setting

Do not start with MIDI-driven singing synthesis. That is a larger singing synthesis product and should not block the cover MVP.

## F0 Correction

Use gentle correction:

- Align voiced frames to ScoreIR note spans.
- Correct the center pitch toward the note pitch.
- Preserve local slides, vibrato, and expressive deviations.
- Keep unvoiced frames unvoiced.
- Persist the corrected curve as `CorrectedF0Track`.

Avoid hard quantization unless the user explicitly asks for a robotic correction effect.

## External Service Boundary

Backend responsibilities:

- Prepare inputs.
- Create the RVC task.
- Submit files or object URLs to the external RVC service.
- Poll or receive completion.
- Persist returned converted vocals as an artifact.
- Mix converted vocals with accompaniment.
- Persist final mix as an artifact.

External RVC service responsibilities:

- Load voice model.
- Run voice conversion.
- Return converted vocal audio and job metadata.

## Artifact Rules

Persist these artifacts:

- `corrected_f0`
- `rvc_vocal`
- `rvc_mix`
- optional RVC service metadata

Tie every artifact to project, task, and score revision where applicable.

## Validation

Before submitting an RVC job, verify:

- Selected revision exists and has lead-vocal notes.
- `vocals.wav` exists.
- `F0Track` exists and covers the vocal duration.
- Corrected F0 duration matches vocals.
- Voice model ID is valid for the configured external service.
- Required service config is present.

## Failure Handling

Fail explicitly for missing inputs or service configuration. Do not return a fake converted vocal.

When diagnosing quality problems, separate:

- bad source separation
- bad F0 extraction
- bad ScoreIR notes
- too-strong F0 correction
- wrong transpose
- RVC model mismatch
- mix imbalance
