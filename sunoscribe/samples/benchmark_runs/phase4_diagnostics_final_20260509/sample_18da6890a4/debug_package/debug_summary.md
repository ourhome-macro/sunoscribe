# Benchmark Debug Package: 牛仔很忙

## Sample
- sample title: 牛仔很忙
- sample_id: sample_18da6890a4
- run_id: phase4_diagnostics_final_20260509
- run_dir: E:\project\sunoscribe\sunoscribe\sunoscribe\samples\benchmark_runs\phase4_diagnostics_final_20260509\sample_18da6890a4
- status: quality_failed
- failed checks: note_recall, matched_notes
- reference strategy: track
- expected note count: 673
- predicted note count: 141

## Raw Metrics
- note_recall: 0.0089153
- note_f1: 0.014742
- matched_note_count: 6
- midi_coverage_ratio: 0.374487
- first_note_delay_sec: 8.19422
- pitch_accuracy: 0.833333

## Alignment Metrics
- pred_to_exp_shift_sec: -4.488
- shift_corrected_recall: 0.0118871
- shift_corrected_f1: 0.019656
- shift_corrected_matched: 8
- shift_recall_gain: 0.00297177
- shift_matched_gain: 2
- alignment_diagnosis: weak_alignment_signal

## Octave And DTW Metrics
- best octave shift: 12
- best octave recall: 0.0430906
- dtw_recall: 0.106984

## Artifact List
- found files:
  - alignment_debug.json
  - debug_summary.md
  - derived_diagnostics.json
  - expected_notes.json
  - f0_track.json
  - match_debug.json
  - mdx_diagnostics.json
  - note_candidates.json
  - pitch_debug.md
  - predicted_notes.json
  - produced.mid
  - score_ir.json
  - timeline_debug.png
  - vocal_activity.json
  - vocals.wav
- missing files:
  - quantized_notes.json

## Derived Diagnostics
### Notes Density / Duration
- expected_note_count: 673
- predicted_note_count: 141
- expected_notes_per_second: 4.2474
- predicted_notes_per_second: 0.916712
- expected_median_duration_sec: 0.1125
- predicted_median_duration_sec: 0.310303
- expected_short_note_ratio: 0.884101
- predicted_short_note_ratio: 0.382979
- pred_exp_note_count_ratio: 0.20951
### Time Overlap
- expected_time_span_sec: 158.45
- predicted_time_span_sec: 153.811
- expected_predicted_time_overlap_ratio: 0.927478
### Pitch Overlap
- expected_pitch_range: [59, 84]
- predicted_pitch_range: [48, 76]
- pitch_range_overlap_ratio: 0.472222
- expected_median_pitch: 74
- predicted_median_pitch: 60
- median_pitch_delta: -14
### F0 Diagnostics
- available: true
- f0_frame_count: 16820
- f0_voiced_frame_count: 9540
- f0_voiced_ratio: 0.567182
- f0_median_confidence: 0.533681
- f0_pitch_range: [44.602509, 77.028028]
- f0_time_span_sec: 168.19
- unavailable_reason: none
### Vocal Activity Diagnostics
- available: true
- vocal_activity_active_ratio: 0.567199
- vocal_activity_segment_count: 575
- vocal_activity_time_span_sec: 168.195
- active_duration_sec: 95.4
- unavailable_reason: none
### Note Candidate Diagnostics
- available: true
- note_candidate_count: 195
- candidate_to_predicted_ratio: 1.38298
- candidate_median_duration_sec: 0.24
- candidate_short_note_ratio: 0.507692
- candidate_pitch_range: [45.0, 77.0]
- unavailable_reason: none
### Match Diagnostics
- raw_matched_count: 6
- shift_matched_count: 8
- unmatched_expected_count: 667
- unmatched_predicted_count: 135
- raw_match_rate_vs_expected: 0.0089153
- raw_match_rate_vs_predicted: 0.0425532
- shift_match_rate_vs_expected: 0.0118871
- shift_match_rate_vs_predicted: 0.0567376
### Pitch Distribution Summary
- preliminary_pitch_diagnosis: possible_f0_octave_or_reference_pitch_mismatch
- triggered_pitch_flags: possible_f0_octave_or_reference_pitch_mismatch
- expected_vs_predicted_pitch_overlap: 0.141363
- expected_vs_f0_pitch_overlap: 0.13758
- expected_vs_candidates_pitch_overlap: 0.138611
- best_octave_shift evidence: expected_vs_f0 shift=12 overlap=0.499946 gain=0.362366
### Rule-Based Stage
- preliminary_failure_stage_v2: possible_short_note_loss

## Preliminary Diagnosis Placeholders
- F0_available: true
- vocal_activity_available: true
- note_candidates_available: true
- predicted_note_density: 0.870345 notes/sec
- expected_note_density: 4.1542 notes/sec
- matched_density: 0.0370359 matches/sec
- possible_failure_stage: possible_pitch_or_segmentation_or_selector
