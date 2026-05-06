# MVP Trial Runbook

This runbook defines the first safe MVP trial path for SunoScribe's backend/audio scope. The goal is to prove `MP4 -> lead-vocal MIDI` with explicit required-stage failures and local deterministic benchmark reports.

## What Can Be Tried Now

- Input MP4/audio is canonicalized through `MediaIngestService` into `preprocess/source.wav`.
- `StemService` consumes canonical WAV and is expected to produce `vocals.wav` plus `accompaniment.wav`.
- Production pitch uses RMVPE with fallback disabled.
- The benchmark manifest contains 19 enabled paired samples under `samples/source_mp4` and `samples/source_mid`.
- The benchmark CLI can validate data, check MVP runtime readiness, run one sample, or run all enabled samples.

## Step 0: Runtime Doctor

Run from the backend directory:

```powershell
.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark doctor --manifest ..\samples\manifest.v1.json
```

Expected output files:

- `samples/benchmark_runs/<run_id>/readiness_report.json`
- `samples/benchmark_runs/<run_id>/dataset_report.json`
- `samples/benchmark_runs/<run_id>/summary.md`

The doctor checks:

- Python runtime recommendation.
- `ffmpeg` availability for MP4/audio canonicalization.
- MIDI/analysis libraries: `pretty_midi`, `mido`, `librosa`, `soundfile`.
- RMVPE production readiness with fallback disabled.
- Vocal separator package and cached MDX-Net model readiness.

If doctor fails, fix dependencies instead of enabling fallback output.

## Step 1: Dataset Validation

```powershell
.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark validate --manifest ..\samples\manifest.v1.json
```

Expected v1 dataset state:

- 22 MP4 files.
- 23 MIDI files.
- 19 paired and enabled samples.
- 0 manifest validation errors.

## Step 2: Single-Song Smoke

Run one short sample first:

```powershell
.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito --keep-project-workspaces
```

Expected per-song outputs:

- `produced.mid`
- `stage_status.json`
- `metrics.json`
- `artifacts.json`
- `error.json` only when the sample fails

Required stages are canonical audio, vocals stem, F0 track, note candidates, score data, and MIDI export.

## Step 3: 19-Song Observe-Only Benchmark

```powershell
.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json
```

Use the first successful full run as an observation baseline. Do not set hard `note_f1` gates until at least two or three stable runs exist.

## Failure Reading Order

1. `readiness_report.json`: dependency/model readiness.
2. `dataset_report.json`: manifest, checksum, expected track problems.
3. `<sample_id>/stage_status.json`: stage-level failure.
4. `<sample_id>/error.json`: exception type and traceback summary.
5. `<sample_id>/metrics.json`: note-level quality, only if MIDI export succeeded.

## MVP Success Criteria

- At least one MP4 completes `source.wav -> vocals.wav -> F0/note candidates -> Score/MIDI`.
- The generated MIDI is playable and audibly resembles the lead vocal melody for at least part of the song.
- The 19-song run produces stable reports where each failed song has a clear stage/failure category.
- No production run uses CREPE/basic-pitch fallback to hide missing RMVPE or separator dependencies.
