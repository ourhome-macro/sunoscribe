# Benchmark Reference Review

- Run root: `E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\codex_20260508_phase2_octave_mojito`
- Created at: `2026-05-08T06:40:32.890464+00:00`
- Reference suspect: `1`
- Likely comparable: `0`
- Needs manual review: `0`

## Reason Counts

- `dtw_sequence_alignment_suspect`: `1`
- `octave_reference_suspect`: `1`

## Samples

| Sample | Reference Status | Reasons | Expected | Predicted | Density/sec | Pred/Exp | Recall | Oct Shift | Raw Median Δ | DTW Rec | DTW Lift | DTW Shift | First Delay s | Failed Checks |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| mojito | reference_suspect | octave_reference_suspect, dtw_sequence_alignment_suspect | 408 | 169 | 2.3137 | 0.4142 | 0.0907 | 12 | -13.0000 | 0.2941 | 0.2034 | 12 | 1.3956 | midi_coverage_ratio |
