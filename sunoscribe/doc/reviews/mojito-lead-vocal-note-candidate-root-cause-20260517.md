# Mojito lead-vocal NoteCandidateSet ?????2026-05-17?

## ??

- `mojito` ?????????? `PitchContourSet -> NoteCandidateSet v2`?`PitchContourBuilder` ?????????????? contour?`NoteCandidateBuilder` ???? contour ? `stability < 0.55` ? `pitch_range > 2.5` ?????? 36 ???????
- `too_unstable` ?????? frame ??????? vibrato???????/?? contour ???181 ? `too_unstable` ? 135 ?? `suspected_glide`?126 ????? `glide + range > 2.5 + stddev > 0.7`?
- ????????? `NoteCandidateBuilder` ???? `too_unstable` ???? contour ?????????? lineage ?? contour??????????????
- ??? `note_candidates` ? 25 ?? 107?`selected_melody` ? 19 ?? 96???? 36.10s ??? 19.41s????? `quality_failed`????????????/????????? gap?????? 19 ??????

## ??????

- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/f0_track.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/pitch_contours.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/note_candidates.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/selected_melody.json`
- `samples/benchmark_runs/codex_20260517_mojito_real_audio/projects/bench_mojito_221a1473/pitch/quantized_notes.json`

## ?? selected 19 ???? contour

| contour | start | duration | confidence | stability | range | stddev | frames | voiced | source_reasons | glide | vibrato |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pc_00025 | 36.100 | 0.150 | 0.850 | 0.732 | 0.805 | 0.253 | 20 | 16 |  | False | False |
| pc_00029 | 38.440 | 0.180 | 0.859 | 0.563 | 1.310 | 0.430 | 23 | 18 |  | False | False |
| pc_00050 | 50.450 | 0.150 | 0.860 | 0.669 | 0.993 | 0.259 | 20 | 16 |  | False | False |
| pc_00071 | 65.050 | 0.160 | 0.877 | 0.692 | 0.923 | 0.224 | 20 | 16 |  | False | False |
| pc_00072 | 65.300 | 0.190 | 0.844 | 0.654 | 1.038 | 0.251 | 23 | 19 |  | False | False |
| pc_00094 | 97.430 | 0.160 | 0.775 | 0.679 | 0.962 | 0.252 | 20 | 16 |  | False | False |
| pc_00102 | 100.300 | 0.140 | 0.716 | 0.587 | 1.240 | 0.336 | 19 | 15 |  | False | False |
| pc_00126 | 115.130 | 0.190 | 0.833 | 0.627 | 1.120 | 0.265 | 23 | 19 |  | False | False |
| pc_00137 | 123.510 | 0.170 | 0.854 | 0.797 | 0.610 | 0.164 | 21 | 18 |  | False | False |
| pc_00138 | 123.740 | 0.170 | 0.779 | 0.684 | 0.947 | 0.298 | 21 | 17 | suspected_vibrato, uncertain | False | True |
| pc_00141 | 125.050 | 0.190 | 0.835 | 0.627 | 1.119 | 0.225 | 23 | 19 |  | False | False |
| pc_00144 | 125.820 | 0.220 | 0.856 | 0.583 | 1.251 | 0.446 | 27 | 22 | suspected_vibrato, uncertain | False | True |
| pc_00149 | 129.500 | 0.190 | 0.794 | 0.581 | 1.256 | 0.305 | 24 | 19 |  | False | False |
| pc_00163 | 138.340 | 0.120 | 0.871 | 0.759 | 0.724 | 0.216 | 17 | 12 |  | False | False |
| pc_00167 | 140.170 | 0.180 | 0.818 | 0.760 | 0.719 | 0.197 | 23 | 18 |  | False | False |
| pc_00168 | 140.430 | 0.180 | 0.857 | 0.661 | 1.018 | 0.236 | 23 | 19 |  | False | False |
| pc_00192 | 165.480 | 0.180 | 0.850 | 0.600 | 1.201 | 0.310 | 23 | 19 |  | False | False |
| pc_00200 | 170.390 | 0.440 | 0.859 | 0.678 | 0.966 | 0.219 | 49 | 45 | suspected_vibrato, uncertain | False | True |
| pc_00212 | 180.370 | 0.190 | 0.548 | 0.783 | 0.650 | 0.179 | 24 | 21 |  | False | False |

## ? 20 ? too_unstable ????

| contour | start | duration | confidence | stability | range | stddev | frames | voiced | source_reasons | glide | vibrato | class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pc_00001 | 18.790 | 0.140 | 0.601 | 0.398 | 1.807 | 0.702 | 15 | 12 | too_unstable, uncertain | False | False | pitch range 1.5-2.5 + stddev > 0.7 |
| pc_00002 | 19.120 | 0.940 | 0.852 | 0.000 | 8.729 | 2.574 | 95 | 90 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00003 | 20.180 | 0.970 | 0.894 | 0.000 | 8.407 | 1.381 | 98 | 94 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00004 | 21.210 | 0.630 | 0.879 | 0.000 | 3.948 | 1.249 | 64 | 60 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00005 | 22.000 | 0.340 | 0.879 | 0.373 | 1.880 | 0.500 | 35 | 31 | too_unstable, uncertain | False | False | pitch range 1.5-2.5 + stddev 0.45-0.7 |
| pc_00006 | 23.290 | 0.960 | 0.818 | 0.000 | 10.351 | 2.901 | 97 | 92 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00007 | 24.350 | 0.470 | 0.851 | 0.094 | 2.717 | 0.860 | 48 | 43 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00008 | 24.850 | 0.400 | 0.837 | 0.000 | 5.647 | 1.494 | 41 | 37 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00009 | 25.370 | 1.130 | 0.890 | 0.000 | 5.509 | 1.319 | 114 | 111 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00010 | 27.200 | 0.670 | 0.857 | 0.000 | 7.615 | 2.585 | 68 | 63 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00011 | 28.010 | 0.290 | 0.861 | 0.000 | 3.433 | 1.159 | 30 | 25 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00012 | 28.410 | 0.410 | 0.882 | 0.535 | 1.394 | 0.434 | 42 | 39 | suspected_vibrato, uncertain | False | True | ?/?? vibrato |
| pc_00013 | 29.360 | 0.720 | 0.848 | 0.000 | 9.059 | 2.775 | 73 | 68 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00014 | 30.110 | 0.320 | 0.876 | 0.527 | 1.420 | 0.517 | 33 | 28 |  | False | False | stddev 0.45-0.7 |
| pc_00015 | 30.500 | 0.330 | 0.887 | 0.517 | 1.450 | 0.341 | 34 | 30 |  | False | False | ????? |
| pc_00016 | 31.390 | 0.110 | 0.689 | 0.062 | 2.815 | 1.015 | 12 | 8 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00017 | 31.680 | 0.450 | 0.832 | 0.000 | 6.901 | 1.764 | 46 | 41 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00018 | 32.180 | 1.000 | 0.893 | 0.000 | 3.466 | 0.885 | 101 | 96 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |
| pc_00019 | 33.210 | 0.230 | 0.881 | 0.512 | 1.465 | 0.330 | 24 | 19 |  | False | False | ????? |
| pc_00020 | 33.460 | 0.480 | 0.858 | 0.000 | 5.181 | 0.972 | 49 | 47 | too_unstable, suspected_glide, uncertain | True | False | ??? + pitch range > 2.5 + stddev > 0.7 |

## too_unstable ??????

| class | count |
| --- | --- |
| ??? + pitch range > 2.5 + stddev > 0.7 | 128 |
| pitch range 1.5-2.5 + stddev 0.45-0.7 | 19 |
| pitch range 1.5-2.5 + stddev > 0.7 | 7 |
| ??? + pitch range > 2.5 + stddev 0.45-0.7 | 7 |
| stddev 0.45-0.7 | 5 |
| ????? | 5 |
| pitch range 1.5-2.5 | 3 |
| pitch range 1.5-2.5 + stddev > 0.7 + frame ?? | 2 |
| ?/?? vibrato + pitch range 1.5-2.5 + stddev 0.45-0.7 | 2 |
| ?/?? vibrato + pitch range 1.5-2.5 | 2 |
| ?/?? vibrato | 1 |

- `source_reason_codes` ???`{'too_unstable': 170, 'uncertain': 171, 'suspected_glide': 135, 'suspected_vibrato': 5, 'too_short': 2, 'low_confidence': 2}`
- selected vs too_unstable?
  - duration?selected `n=19, min=0.120, p25=0.160, med=0.180, p75=0.190, max=0.440, mean=0.187`?rejected `n=181, min=0.060, p25=0.260, med=0.460, p75=0.700, max=1.600, mean=0.516`
  - confidence?selected `n=19, min=0.548, p25=0.794, med=0.850, p75=0.859, max=0.877, mean=0.818`?rejected `n=181, min=0.459, p25=0.763, med=0.832, p75=0.869, max=0.907, mean=0.798`
  - stability?selected `n=19, min=0.563, p25=0.600, med=0.669, p75=0.732, max=0.797, mean=0.669`?rejected `n=181, min=0.000, p25=0.000, med=0.000, p75=0.167, max=0.543, mean=0.108`
  - pitch range?selected `n=19, min=0.610, p25=0.805, med=0.993, p75=1.201, max=1.310, mean=0.992`?rejected `n=181, min=1.371, p25=2.499, med=3.900, p75=5.889, max=23.801, mean=4.884`
  - stddev?selected `n=19, min=0.164, p25=0.219, med=0.252, p75=0.305, max=0.446, mean=0.267`?rejected `n=181, min=0.318, p25=0.703, med=1.057, p75=1.494, max=5.774, mean=1.314`
  - frames?selected `n=19, min=17.000, p25=20.000, med=23.000, p75=23.000, max=49.000, mean=23.316`?rejected `n=181, min=7.000, p25=27.000, med=47.000, p75=71.000, max=161.000, mean=52.624`

## ???? contour ???

`NoteCandidateBuilder._contour_rejection_reasons` ??????

- `confidence < min_confidence`??????? `0.5`?
- `voiced_ratio < min_voiced_ratio`??????? `0.68`?
- `duration < min_duration_sec`??????? `0.08`?
- `stability < min_stability`??????? `0.55`?????????
- `pitch_range_semitones > max_pitch_range_semitones`??????? `2.5`????????????????

## ???????

- ?? `backend/app/modules/pitch/note_candidate_builder.py`?? `too_unstable` ???????? contour?? `frame_samples` ?????????
- ???????`min_source_duration=0.20s`?`min_subsegment_duration=0.18s`?`max_subsegment_duration=0.75s`?`max_pitch_range=0.80 semitone`?`max_pitch_stddev=0.45 semitone`?`max_frame_gap=0.04s`?
- ?? candidate ?? `candidate_origin=note_candidate_builder.contour_segment`??? `source_contour_ids` ? `source_f0_frame_range`?reason code ? `contour_segmentation_bridge`?
- ???? `backend/tests/test_note_candidate_builder.py::TestNoteCandidateBuilder::test_segments_unstable_long_contour_into_stable_candidates`?

## ?????

- ???`backend/.venv310/Scripts/python.exe -m pytest tests/test_note_candidate_builder.py -q`??? `4 passed`?
- ???? mojito candidate?
  - ???`accepted=25`?`rejected=188`?`too_unstable=181`?selected `19`?quantized `19`??? `36.10s`?
  - ????`accepted=107`?`rejected=126`?`too_unstable=119`?`contour_segment=82`?selected `96`?quantized `93`??? `19.41s`?
- ??? benchmark?`codex_20260517_mojito_segment_fix_tuned` ? `quality_failed`?summary ??

```text
| mojito | quality_failed | reference_suspect | octave_reference_suspect, dtw_sequence_alignment_suspect | 0.0080 | 0.0049 | 0.0399 | 0.0245 | 2 | 10 | 0.1313 | 0.8913 | 61 | 0.1505 | 0.1196 | -0.9430 | 0.1936 | 0.3154 | 79 | 0.1320 | minor_onset_alignment_gain | 1.6701 | 0.0392 | 0.0392 | 0.1936 | 1.0000 | 1.0000 | midi_coverage_too_low, possible_octave_error, timing_or_quantization_failure, time_shift_improves_alignment, dtw_alignment_improves_recall, fragmented_melody_gaps, large_pitch_jumps |  |
```

## ??????????

- `NoteCandidateBuilder` ?????????? 19 ?????????? `gap50_ratio=0.8913`??? F0 contour ? note ???????
- ??????????? `min_stability`???? `PitchContourBuilder` ??? contour ??? `MelodySelection` ? phrase/gap ???????????? pitch slope/onset/?? plateau ?????? note boundary?
- `mojito` benchmark ?? `reference_suspect`?`octave_reference_suspect`, `dtw_sequence_alignment_suspect`???????????????/??????????????????
