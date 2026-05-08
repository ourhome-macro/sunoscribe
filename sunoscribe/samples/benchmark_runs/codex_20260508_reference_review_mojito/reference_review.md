# Benchmark Reference Review

- Run root: `E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\codex_20260508_reference_review_mojito`
- Created at: `2026-05-08T00:58:42.003035+00:00`
- Reference suspect: `1`
- Likely comparable: `0`
- Needs manual review: `0`

## Reason Counts

- `dtw_sequence_alignment_suspect`: `1`
- `octave_reference_suspect`: `1`

## Samples

| Sample | Reference Status | Reasons | Expected | Predicted | Density/sec | Pred/Exp | Recall | DTW Rec | DTW Lift | DTW Shift | First Delay s | Failed Checks |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| mojito | reference_suspect | octave_reference_suspect, dtw_sequence_alignment_suspect | 408 | 169 | 2.3137 | 0.4142 | 0.0441 | 0.2941 | 0.2500 | 12 | 1.3956 | midi_coverage_ratio, note_recall |
