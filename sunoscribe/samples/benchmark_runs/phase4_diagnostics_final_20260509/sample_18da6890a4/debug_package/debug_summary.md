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

## Rhythm Diagnostics
- tempo: 123.047 bpm
- tempo_stability: 0.971897
- downbeat_confidence: 0.5995
- off_grid_onset_ratio: 0.496454
- rhythm preliminary diagnosis: mixed_rhythm_issue
- current_candidate_rank: 2
- best_diagnostic_candidate_id: double_tempo_grid
- current_vs_best_score_delta: 0.041134
- rhythm_candidate_warning: none

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
  - note_funnel_debug.json
  - note_funnel_debug.md
  - pitch_debug.md
  - predicted_notes.json
  - produced.mid
  - rhythm_debug.json
  - rhythm_debug.md
  - rhythm_grid.json
  - rhythm_grid_candidates.json
  - rhythm_grid_candidates.md
  - score_ir.json
  - timeline_debug.png
  - vocal_activity.json
  - vocals.wav
- missing files:
  - pitch_contours.json
  - quantized_notes.json
  - selected_melody.json

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
### Pitch Contour Diagnostics
- available: false
- contour_count: missing
- low_confidence_contour_count: missing
- median_contour_duration_sec: missing
- suspected_vibrato_contour_count: missing
- suspected_glide_contour_count: missing
- unavailable_reason: pitch_contours.json missing
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
### Selected Melody Diagnostics
- available: false
- input_candidate_count: missing
- selected_count: missing
- rejected_count: missing
- rejection_reason_counts: missing
- mean_selected_confidence: missing
- mean_rejected_confidence: missing
- unavailable_reason: selected_melody.json missing
### Quantization Diagnostics
- available: false
- quantizer_backend: missing
- requested_quantizer_backend: missing
- fallback_used: false
- fallback_reason: missing
- note_count: missing
- mean_quantize_error_sec: missing
- p95_quantize_error_sec: missing
- max_quantize_error_sec: missing
- uncertain_count: missing
- possible_fragment_pair_count: missing
- fragmentation_risk_score: missing
- possible_overmerge_note_count: missing
- overmerge_overlap_pair_count: missing
- overmerge_risk_score: missing
- unavailable_reason: quantized_notes.json missing
### Rhythm Diagnostics
- available: true
- tempo_bpm: 123.047
- tempo_stability: 0.971897
- beat_count: 334
- beat_gap_mean_sec: 0.485388
- beat_gap_p95_sec: 0.487619
- beat_gap_max_sec: 0.603719
- downbeat_count: 84
- downbeat_confidence: 0.5995
- bar_phase_confidence: 0.819775
- off_grid_onset_ratio: 0.496454
- pickup_likelihood: 0.75
- rubato_likelihood: 0.095676
- grid_uncertain_region_count: 20
- preliminary_rhythm_diagnosis: mixed_rhythm_issue
- rhythm_flags: mixed_rhythm_issue, possible_off_grid_quantization, possible_pickup_or_leading_silence
- rhythm_candidate_count: 7
- best_diagnostic_candidate_id: double_tempo_grid
- current_candidate_rank: 2
- current_vs_best_score_delta: 0.041134
- rhythm_candidate_warning: none
- unavailable_reason: none
### Note Funnel
- f0_voiced_frame_count: 9540
- f0_voiced_duration_sec: 95.4
- note_candidate_count: 195
- selected_note_count: unavailable
- quantized_note_count: unavailable
- score_ir_note_count: 141
- predicted_midi_note_count: 141
- expected_note_count: 673
- candidate_to_selected_count_ratio: missing
- selected_to_quantized_count_ratio: missing
- quantized_to_score_ir_count_ratio: missing
- score_ir_to_predicted_count_ratio: 1
- candidate_to_predicted_count_ratio: 0.723077
- triggered_funnel_flags: possible_candidate_extraction_loss, possible_short_note_loss, possible_overmerge
- primary_attribution: possible_candidate_extraction_loss
- missing_layers: selected_melody, quantized_notes
### Short Note Diagnostics
- available: true
- expected_short_note_count: 595
- predicted_short_note_count: 54
- matched_short_note_count: 1
- missed_short_note_count: 594
- false_positive_short_note_count: 53
- short_note_recall: 0.00168067
- short_note_precision: 0.0185185
- likely_loss_stage: candidate
- loss_stage_counts: {'candidate': 592, 'selector': 0, 'quantizer': 0, 'export': 0, 'unknown': 2}
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
