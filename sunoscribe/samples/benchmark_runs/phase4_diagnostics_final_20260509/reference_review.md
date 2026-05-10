# Benchmark Reference Review

- Run root: `..\samples\benchmark_runs\phase4_diagnostics_final_20260509`
- Created at: `2026-05-10T07:54:28.224342+00:00`
- Reference suspect: `14`
- Likely comparable: `5`
- Needs manual review: `0`

## Reason Counts

- `time_origin_suspect`: `10`
- `dtw_sequence_alignment_suspect`: `5`
- `octave_reference_suspect`: `4`
- `expected_note_count_too_high`: `2`
- `predicted_expected_ratio_too_low`: `2`
- `expected_note_density_too_high`: `1`

## Samples

| Sample | Reference Status | Reasons | Expected | Predicted | Density/sec | Pred/Exp | Recall | Oct Shift | Raw Median Δ | DTW Rec | DTW Lift | DTW Shift | First Delay s | Failed Checks |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| sample_02a359fea9 | reference_suspect | time_origin_suspect | 457 | 236 | 1.6022 | 0.5164 | 0.0066 | 0 | -16.0000 | 0.0481 | 0.0416 | 12 | -18.2682 | note_recall, matched_notes |
| sample_0f83f2cae8 | reference_suspect | expected_note_count_too_high, predicted_expected_ratio_too_low | 1356 | 214 | 4.9464 | 0.1578 | 0.0383 | 12 | -12.0000 | 0.1187 | 0.0804 | 12 | 16.0040 | first_note_delay_sec, note_recall |
| sample_1239cb07a9 | reference_suspect | time_origin_suspect | 331 | 234 | 1.2431 | 0.7069 | 0.0544 | 12 | -11.0000 | 0.2054 | 0.1511 | 12 | 25.6709 | first_note_delay_sec, midi_coverage_ratio |
| sample_188aed17ed | reference_suspect | time_origin_suspect | 253 | 235 | 0.8956 | 0.9289 | 0.0356 | 12 | -11.0000 | 0.2016 | 0.1660 | 12 | 18.6199 | first_note_delay_sec, note_recall, matched_notes |
| sample_18da6890a4 | reference_suspect | octave_reference_suspect | 673 | 141 | 4.2474 | 0.2095 | 0.0089 | 0 | -14.0000 | 0.1070 | 0.0981 | 12 | 8.1942 | note_recall, matched_notes |
| sample_226bff6c39 | reference_suspect | time_origin_suspect | 417 | 170 | 1.3558 | 0.4077 | 0.0144 | 12 | -12.0000 | 0.2614 | 0.2470 | 12 | 26.8196 | first_note_delay_sec, note_recall, matched_notes |
| sample_29307cadb1 | reference_suspect | octave_reference_suspect, time_origin_suspect, dtw_sequence_alignment_suspect | 403 | 211 | 1.4903 | 0.5236 | 0.0000 | 0 | -10.0000 | 0.1017 | 0.1017 | 12 | 31.5445 | first_note_delay_sec, note_recall, matched_notes |
| sample_2ecbfce2ee | reference_suspect | time_origin_suspect | 520 | 176 | 2.5794 | 0.3385 | 0.0192 | 12 | -12.0000 | 0.0904 | 0.0712 | 12 | 27.1949 | first_note_delay_sec, note_recall |
| sample_5656dc6e75 | reference_suspect | octave_reference_suspect, time_origin_suspect, dtw_sequence_alignment_suspect | 251 | 233 | 0.9511 | 0.9283 | 0.0080 | 0 | -9.0000 | 0.1673 | 0.1594 | 12 | -50.8331 | note_recall, matched_notes |
| sample_597318d7b0 | reference_suspect | time_origin_suspect, dtw_sequence_alignment_suspect | 348 | 207 | 1.5757 | 0.5948 | 0.0057 | 0 | 6.0000 | 0.1063 | 0.1006 | 0 | -16.5471 | note_recall, matched_notes |
| sample_5c94ce2fdc | reference_suspect | expected_note_count_too_high, expected_note_density_too_high, predicted_expected_ratio_too_low | 8559 | 170 | 28.6964 | 0.0199 | 0.0074 | 0 | -2.0000 | 0.0174 | 0.0100 | 0 | 13.1161 | note_recall |
| sample_d4c6f8ed2e | reference_suspect | time_origin_suspect, dtw_sequence_alignment_suspect | 394 | 172 | 2.0871 | 0.4365 | 0.0508 | 0 | 0.0000 | 0.3350 | 0.2843 | 0 | -15.3783 |  |
| sample_e95a51680b | reference_suspect | time_origin_suspect | 112 | 290 | 0.4430 | 2.5893 | 0.0000 | 0 | -17.0000 | 0.0982 | 0.0982 | 12 | -73.8552 | midi_coverage_ratio, note_recall, matched_notes |
| see_you_again | reference_suspect | octave_reference_suspect, dtw_sequence_alignment_suspect | 666 | 178 | 2.9699 | 0.2673 | 0.0015 | 0 | -14.0000 | 0.2132 | 0.2117 | 12 | 14.2342 | note_recall, matched_notes |
| mojito | likely_comparable |  | 408 | 169 | 2.3137 | 0.4142 | 0.0907 | 12 | -13.0000 | 0.2941 | 0.2034 | 12 | 1.3956 |  |
| sample_0094cce12b | likely_comparable |  | 279 | 141 | 1.1815 | 0.5054 | 0.0466 | 12 | -12.0000 | 0.0789 | 0.0323 | 12 | 14.6091 | note_recall |
| sample_316051fdf9 | likely_comparable |  | 522 | 138 | 1.8856 | 0.2644 | 0.0153 | 24 | -24.0000 | 0.0747 | 0.0594 | 24 | 10.6745 | midi_coverage_ratio, note_recall, matched_notes |
| sample_76de878917 | likely_comparable |  | 572 | 190 | 2.6708 | 0.3322 | 0.0664 | 24 | -24.0000 | 0.2483 | 0.1818 | 24 | 4.0769 |  |
| sample_f0575baf18 | likely_comparable |  | 425 | 192 | 1.9353 | 0.4518 | 0.0541 | 12 | -12.0000 | 0.3788 | 0.3247 | 12 | -11.7506 |  |
