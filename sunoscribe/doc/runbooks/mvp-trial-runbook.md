# MVP Trial Runbook

This runbook defines the first safe MVP trial path for SunoScribe's backend/audio scope. The goal is to prove `MP4 -> lead-vocal MIDI` with explicit required-stage failures and local deterministic benchmark reports.

## What Can Be Tried Now

- Input MP4/audio is canonicalized through `MediaIngestService` into 44.1 kHz stereo `preprocess/source.wav`.
- `StemService` consumes canonical WAV and is expected to produce `vocals.wav` plus `accompaniment.wav`.
- Production pitch uses RMVPE with fallback disabled.
- The benchmark manifest contains 19 enabled paired samples under `samples/source_mp4` and `samples/source_mid`.
- The benchmark CLI can validate data, check MVP runtime readiness, run one sample, or run all enabled samples.
- Benchmark `success` now means the pipeline completed and the first-pass audibility quality gate passed; pipeline failures and quality failures are separate states.

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

Canonical audio settings for the MVP are:

- `CANONICAL_AUDIO_SAMPLE_RATE=44100`
- `CANONICAL_AUDIO_CHANNELS=2`

RMVPE still resamples internally to its configured 16 kHz model input; do not lower canonical audio to 16 kHz before vocal separation.

Agent/LLM workflow is not part of the core MP4 -> MIDI metric path. If enabled for post-revision ScorePatch assistance, use `AGENT_LLM_MODEL=gpt-5.4-mini` with `OPENAI_API_KEY` kept only in local environment files.

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
.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito
```

Expected per-song outputs:

- `produced.mid`
- `stage_status.json`
- `metrics.json`
- `quality_gate.json`
- `artifacts.json`
- `logs/stdout.log`, `logs/stderr.log`, `logs/python_logging.log`
- `error.json` only when the sample fails

Per-sample project workspaces are always retained under `samples/benchmark_runs/<run_id>/projects/<project_id>/` so `vocals.wav`, `f0_track.json`, `note_candidates.json`, and `score_ir.json` remain available for diagnosis. `--keep-project-workspaces` is kept only as a compatibility no-op.

Required stages are canonical audio, vocals stem, F0 track, note candidates, score data, and MIDI export.

## Step 3: 19-Song Quality-Gated Benchmark

```powershell
.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json
```

Exit codes are intentionally distinct:

- `0`: all selected samples are `success`.
- `1`: at least one sample has a pipeline/program failure.
- `2`: no pipeline failures occurred, but at least one sample is `quality_failed`.

First-pass hard quality gates are `first_note_delay_sec <= 15.0`, `midi_coverage_ratio >= 0.45`, `note_recall >= 0.05`, and `matched_notes >= 10`. `note_f1` is diagnostic-only for now and appears in summaries and quality reports.

Use `alignment.best_octave_shift_note_recall`, `alignment.best_time_shift_note_recall`, `alignment.dtw.dtw_pitch_match_recall_proxy`, and `alignment.reference_track_suspect_reasons` as triage-only signals. If shifted or DTW recall is much higher than base recall, review `expected_melody_track` and the reference MIDI timing/pitch range before tuning F0 extraction, note segmentation, or quantization.

## Failure Reading Order

1. `readiness_report.json`: dependency/model readiness.
2. `dataset_report.json`: manifest, checksum, expected track problems.
3. `<sample_id>/stage_status.json`: stage-level failure.
4. `<sample_id>/quality_gate.json`: quality gate checks when MIDI metrics succeeded.
5. `<sample_id>/metrics.json`: note-level quality, audibility metrics, diagnostics, and suspected failure modes.
6. `<sample_id>/logs/*.log`: captured stdout/stderr/python logging for the sample.
7. `<sample_id>/error.json`: exception type and traceback summary, only for pipeline/program failures.
8. `quality_diagnostics.md`: run-level low-F1, low-coverage, and first-note-delay triage.

## MVP Success Criteria

- At least one MP4 completes `source.wav -> vocals.wav -> F0/note candidates -> Score/MIDI`.
- The generated MIDI is playable and audibly resembles the lead vocal melody for at least part of the song.
- The 19-song run produces stable reports where each failed song has a clear stage/failure category.
- No production run uses CREPE/basic-pitch fallback to hide missing RMVPE or separator dependencies.

