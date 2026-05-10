# Pitch Distribution Debug: 牛仔很忙

## Scope
- diagnostic_only: true
- no pitch shift or octave correction applied to produced MIDI
- raw metrics and shift metrics are unchanged

## Source Summary
| source | available | events | duration_sec | median | p05-p95 | min-max | top bins |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| expected | true | 673 | 131.225 | C5 / 72 | G4 / 67-G5 / 79 | B3 / 59-C6 / 84 | C5 0.42551, D5 0.222138, E5 0.070299, D#5 0.064298 |
| predicted | true | 141 | 60.6687 | C4 / 60 | C3 / 48-C5 / 72 | C3 / 48-E5 / 76 | C4 0.335525, D3 0.13364, D4 0.10708, B3 0.106313 |
| F0 | true | 16820 | 95.4 | C4 / 59.5091 | C3 / 47.9474-C5 / 71.9855 | A2 / 44.6025-F5 / 77.028 | C4 0.20566, D3 0.130818, C3 0.095388, B3 0.076205 |
| note_candidates_all | true | 195 | 67.26 | C4 / 60 | C3 / 48-C5 / 72 | A2 / 45-F5 / 77 | C4 0.315938, D3 0.146744, D4 0.107939, B3 0.090842 |
| note_candidates_selected | true | 141 | 60.65 | C4 / 60 | C3 / 48-C5 / 72 | C3 / 48-E5 / 76 | C4 0.335532, D3 0.133718, D4 0.107007, B3 0.106348 |
| note_candidates_melody_raw | true | 195 | 67.26 | C4 / 60 | C3 / 48-C5 / 72 | A2 / 45-F5 / 77 | C4 0.315938, D3 0.146744, D4 0.107939, B3 0.090842 |

## Pairwise Pitch Overlap
| pair | raw_overlap | range_iou | median_delta | best_shift | shifted_overlap | gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| expected_vs_predicted | 0.141363 | 0.16129 | -12 | 12 | 0.607775 | 0.466412 |
| expected_vs_f0 | 0.13758 | 0.160552 | -12.4909 | 12 | 0.499946 | 0.362366 |
| expected_vs_note_candidates | 0.138611 | 0.16129 | -12 | 12 | 0.596777 | 0.458166 |
| f0_vs_note_candidates | 0.786545 | 0.997213 | 0.490926 | 0 | 0.786545 | 0 |
| f0_vs_predicted | 0.761383 | 0.997213 | 0.490926 | 0 | 0.761383 | 0 |
| note_candidates_vs_predicted | 0.956864 | 1 | 0 | 0 | 0.956864 | 0 |
| note_candidates_all_vs_selected | 0.956823 | 1 | 0 | 0 | 0.956823 | 0 |
| note_candidates_selected_vs_predicted | 0.999735 | 1 | 0 | 0 | 0.999735 | 0 |

## Candidate Funnel
- F0 voiced duration: 95.4
- note_candidates_all count / duration: 195 / 67.26
- note_candidates_selected count / duration: 141 / 60.65
- predicted MIDI count / duration: 141 / 60.6687
- selected_to_all_count_ratio: 0.723077
- predicted_to_candidate_count_ratio: 0.723077

## Triggered Flags
### possible_f0_octave_or_reference_pitch_mismatch
- confidence: medium
- subtype: ambiguous_octave_or_reference
- evidence:
  - expected_vs_f0 raw_overlap=0.13758
  - expected_vs_f0 median_delta=-12.4909 semitones
  - best_octave_shift=12 overlap=0.499946 gain=0.362366
- interpretation: F0, candidates, or predicted notes may agree with each other while the reference sits an octave-like distance away.

## Non-triggered Flags
- possible_f0_to_note_candidate_loss
- possible_melody_selector_or_filter_loss
- possible_reference_strategy_or_pitch_source_mismatch

## Warnings
- none