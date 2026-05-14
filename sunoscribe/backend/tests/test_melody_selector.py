import unittest

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.contour_candidate_bridge import ContourToCandidateBridge
from app.modules.pitch.melody_selector import MelodySelector
from app.modules.pitch.reason_codes import (
    BRIDGE_FROM_F0_CONTOUR,
    BRIDGE_OVERLAPS_RAW_CANDIDATE,
    CONTOUR_CANDIDATE_CONTEXT_GUARDED,
    CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT,
    CONTOUR_CANDIDATE_SPLITS_BIG_GAP,
    CONTOUR_SEGMENTATION_ALL_SEGMENTS_REJECTED,
    CONTOUR_SEGMENTATION_BRIDGE,
    CONTOUR_SEGMENTATION_NO_STABLE_SUBSEGMENT,
    CONTOUR_TO_CANDIDATE_BRIDGE,
    LOW_CONFIDENCE,
    LOW_VOICED_RATIO,
    OCTAVE_JUMP_CORRECTED,
    OUTSIDE_VOCAL_RANGE,
    PRESELECTOR_LOW_OCTAVE_CORRECTED,
    SHORT_GAP_BRIDGED,
    SHORT_NOTE_ABSORBED,
    TOO_SHORT,
    TOO_UNSTABLE,
)
from app.modules.pitch.types import Note, VocalActivitySegment


class TestMelodySelector(unittest.TestCase):
    def test_contour_to_candidate_bridge_creates_raw_candidate_for_missing_voiced_gap(self):
        bridge = ContourToCandidateBridge()
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_bridge",
                    "start_time_sec": 0.55,
                    "end_time_sec": 0.78,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.88,
                    "voiced_ratio": 1.0,
                    "stability": 0.86,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.4, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=1.0, end_time=1.35, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=0.9, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        bridged = [note for note in result.notes if note.candidate_origin == CONTOUR_TO_CANDIDATE_BRIDGE]
        self.assertEqual(len(bridged), 1)
        self.assertEqual(bridged[0].pitch, "D4")
        self.assertIn(CONTOUR_TO_CANDIDATE_BRIDGE, bridged[0].reason_codes)
        self.assertIn(BRIDGE_FROM_F0_CONTOUR, bridged[0].reason_codes)
        self.assertIn(CONTOUR_CANDIDATE_CONTEXT_GUARDED, bridged[0].reason_codes)
        self.assertEqual(bridged[0].contour_bridge_evidence["source_contour_id"], "pc_bridge")
        self.assertEqual(bridged[0].contour_bridge_evidence["raw_overlap_duration_sec"], 0.0)
        self.assertEqual(result.summary["accepted_count"], 1)

    def test_contour_to_candidate_bridge_rejects_long_glide_contour(self):
        bridge = ContourToCandidateBridge()
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_long_glide",
                    "start_time_sec": 0.5,
                    "end_time_sec": 3.2,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.94,
                    "voiced_ratio": 1.0,
                    "stability": 0.9,
                    "has_glide": True,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=3.5, end_time=3.9, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=3.25, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        self.assertEqual(result.summary["accepted_count"], 0)
        self.assertIn(TOO_UNSTABLE, result.rejected_candidates[0]["contour_bridge_guard_reason_codes"])

    def test_contour_to_candidate_bridge_rejects_raw_overlap(self):
        bridge = ContourToCandidateBridge()
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_overlap",
                    "start_time_sec": 0.45,
                    "end_time_sec": 0.8,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.9,
                    "voiced_ratio": 1.0,
                    "stability": 0.9,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.4, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=0.6, end_time=0.9, confidence=0.88, candidate_id="raw_overlap"),
                Note(pitch="E4", start_time=1.2, end_time=1.6, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.4, end_time=1.0, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        self.assertEqual(result.summary["accepted_count"], 0)
        self.assertIn(BRIDGE_OVERLAPS_RAW_CANDIDATE, result.rejected_candidates[0]["contour_bridge_guard_reason_codes"])

    def test_contour_to_candidate_bridge_rejects_confidence_duration_range_and_voiced_guards(self):
        bridge = ContourToCandidateBridge()
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_guarded",
                    "start_time_sec": 0.5,
                    "end_time_sec": 0.6,
                    "pitch_center_midi": 90,
                    "mean_confidence": 0.4,
                    "voiced_ratio": 0.5,
                    "stability": 0.9,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.92, candidate_id="left"),
                Note(pitch="E4", start_time=1.0, end_time=1.3, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=0.8, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        reasons = set(result.rejected_candidates[0]["contour_bridge_guard_reason_codes"])
        self.assertIn(LOW_CONFIDENCE, reasons)
        self.assertIn(LOW_VOICED_RATIO, reasons)
        self.assertIn(TOO_SHORT, reasons)
        self.assertIn(OUTSIDE_VOCAL_RANGE, reasons)

    def test_contour_to_candidate_bridge_rejects_without_context_or_when_splitting_big_gap(self):
        bridge = ContourToCandidateBridge()

        no_context = bridge.bridge(
            contours=[
                {
                    "id": "pc_no_context",
                    "start_time_sec": 1.0,
                    "end_time_sec": 1.3,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.9,
                    "voiced_ratio": 1.0,
                    "stability": 0.9,
                }
            ],
            raw_candidates=[Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.92, candidate_id="left")],
            vocal_activity=[VocalActivitySegment(start_time=0.9, end_time=1.4, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )
        self.assertIn(CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT, no_context.rejected_candidates[0]["contour_bridge_guard_reason_codes"])

        split = bridge.bridge(
            contours=[
                {
                    "id": "pc_split",
                    "start_time_sec": 0.95,
                    "end_time_sec": 1.15,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.9,
                    "voiced_ratio": 1.0,
                    "stability": 0.9,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.2, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=2.0, end_time=2.3, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.9, end_time=1.2, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )
        self.assertIn(CONTOUR_CANDIDATE_SPLITS_BIG_GAP, split.rejected_candidates[0]["contour_bridge_guard_reason_codes"])

    def test_contour_to_candidate_bridge_segments_stable_subspan_from_long_contour(self):
        bridge = ContourToCandidateBridge()
        frames = []
        for index in range(120):
            time_sec = round(0.5 + index * 0.01, 2)
            if 80 <= index < 110:
                pitch = 62.0 + (0.05 if index % 2 else 0.0)
                confidence = 0.9
            else:
                pitch = 67.0 + (index * 0.03)
                confidence = 0.5
            frames.append({"time_sec": time_sec, "pitch_midi": pitch, "confidence": confidence, "voiced": True})

        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_long_segmented",
                    "start_time_sec": 0.5,
                    "end_time_sec": 3.5,
                    "duration_sec": 3.0,
                    "pitch_center_midi": 66,
                    "mean_confidence": 0.86,
                    "voiced_ratio": 1.0,
                    "stability": 0.0,
                    "has_glide": True,
                    "frame_samples": frames,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.45, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=1.9, end_time=2.3, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=1.8, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        segmented = [note for note in result.notes if note.candidate_id == "contour_segment_bridge:pc_long_segmented:seg_01"]
        self.assertEqual(len(segmented), 1)
        self.assertIn(CONTOUR_SEGMENTATION_BRIDGE, segmented[0].reason_codes)
        self.assertIn(CONTOUR_TO_CANDIDATE_BRIDGE, segmented[0].reason_codes)
        self.assertEqual(segmented[0].contour_bridge_evidence["source_contour_id"], "pc_long_segmented")
        self.assertEqual(segmented[0].contour_bridge_evidence["segmentation_evidence"]["segment_frame_count"], 30)
        self.assertEqual(result.summary["accepted_count"], 1)

    def test_contour_to_candidate_bridge_summarizes_rejected_segmentation_attempts(self):
        bridge = ContourToCandidateBridge()
        frames = [
            {"time_sec": round(0.5 + index * 0.01, 2), "pitch_midi": 62.0, "confidence": 0.9, "voiced": True}
            for index in range(30)
        ]
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_rejected_segmented",
                    "start_time_sec": 0.5,
                    "end_time_sec": 3.5,
                    "duration_sec": 3.0,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.9,
                    "voiced_ratio": 1.0,
                    "stability": 0.0,
                    "frame_samples": frames,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=6.0, end_time=6.4, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=0.9, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        full_rejection = result.rejected_candidates[0]
        summary = full_rejection["evidence"]["segmentation_attempt_summary"]
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["accepted_count"], 0)
        self.assertIn(CONTOUR_SEGMENTATION_ALL_SEGMENTS_REJECTED, summary["reason_codes"])
        self.assertIn(CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT, summary["guard_reason_counts"])
        self.assertEqual(summary["attempts"][0]["segmentation_evidence"]["segment_frame_count"], 30)

    def test_contour_to_candidate_bridge_summarizes_missing_stable_segmentation(self):
        bridge = ContourToCandidateBridge()
        frames = [
            {"time_sec": round(0.5 + index * 0.01, 2), "pitch_midi": 60.0 + index * 2.0, "confidence": 0.9, "voiced": True}
            for index in range(30)
        ]
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_no_stable_segment",
                    "start_time_sec": 0.5,
                    "end_time_sec": 3.5,
                    "duration_sec": 3.0,
                    "pitch_center_midi": 62,
                    "mean_confidence": 0.9,
                    "voiced_ratio": 1.0,
                    "stability": 0.0,
                    "frame_samples": frames,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.92, candidate_id="left"),
                Note(pitch="D4", start_time=4.5, end_time=4.9, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=0.9, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        summary = result.rejected_candidates[0]["evidence"]["segmentation_attempt_summary"]
        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(summary["attempted_count"], 0)
        self.assertIn(CONTOUR_SEGMENTATION_NO_STABLE_SUBSEGMENT, summary["reason_codes"])
    def test_contour_to_candidate_bridge_low_octave_correction_records_evidence(self):
        bridge = ContourToCandidateBridge()
        result = bridge.bridge(
            contours=[
                {
                    "id": "pc_low_octave",
                    "start_time_sec": 0.48,
                    "end_time_sec": 0.7,
                    "pitch_center_midi": 47,
                    "mean_confidence": 0.9,
                    "voiced_ratio": 1.0,
                    "stability": 0.9,
                }
            ],
            raw_candidates=[
                Note(pitch="C4", start_time=0.0, end_time=0.35, confidence=0.92, candidate_id="left"),
                Note(pitch="C4", start_time=0.9, end_time=1.2, confidence=0.9, candidate_id="right"),
            ],
            vocal_activity=[VocalActivitySegment(start_time=0.45, end_time=0.75, state="vocal", voiced_ratio=1.0, mean_confidence=0.9)],
        )

        bridged = [note for note in result.notes if note.candidate_origin == CONTOUR_TO_CANDIDATE_BRIDGE]
        self.assertEqual(len(bridged), 1)
        self.assertEqual(bridged[0].pitch, "B3")
        self.assertIn(PRESELECTOR_LOW_OCTAVE_CORRECTED, bridged[0].reason_codes)
        correction = bridged[0].contour_bridge_evidence["octave_correction"]
        self.assertEqual(correction["original_pitch"], 47)
        self.assertEqual(correction["shift"], 12)

    def test_second_pass_low_octave_rescue_can_chain_local_candidates_without_adding_big_gaps(self):
        selector = MelodySelector(PitchDetectionConfig())
        result = selector.select(
            [
                Note(pitch="A#3", start_time=0.0, end_time=0.3, confidence=0.9, candidate_id="left"),
                Note(pitch="A#2", start_time=0.8, end_time=1.1, confidence=0.7, candidate_id="low_a"),
                Note(pitch="A#2", start_time=1.55, end_time=1.85, confidence=0.72, candidate_id="low_b"),
                Note(pitch="A#3", start_time=2.25, end_time=2.55, confidence=0.9, candidate_id="right"),
            ]
        )

        rescued = [note for note in result.notes if note.candidate_id in {"low_a", "low_b"}]
        self.assertEqual([note.pitch for note in rescued], ["A#3", "A#3"])
        for note in rescued:
            self.assertIn(PRESELECTOR_LOW_OCTAVE_CORRECTED, note.reason_codes)

    def test_second_pass_low_octave_rescue_revisits_candidates_after_later_context(self):
        selector = MelodySelector(PitchDetectionConfig())
        result = selector.select(
            [
                Note(pitch="A#3", start_time=0.0, end_time=0.3, confidence=0.9, candidate_id="left"),
                Note(pitch="A#2", start_time=1.0, end_time=1.3, confidence=0.7, candidate_id="low_a"),
                Note(pitch="A#2", start_time=1.75, end_time=2.05, confidence=0.72, candidate_id="low_b"),
                Note(pitch="A#3", start_time=2.55, end_time=2.85, confidence=0.9, candidate_id="right"),
            ]
        )

        rescued = [note for note in result.notes if note.candidate_id in {"low_a", "low_b"}]
        self.assertEqual([note.candidate_id for note in rescued], ["low_a", "low_b"])
        self.assertEqual([note.pitch for note in rescued], ["A#3", "A#3"])
        self.assertEqual(result.removed_pitch_range, 0)
        for note in rescued:
            self.assertIn(PRESELECTOR_LOW_OCTAVE_CORRECTED, note.reason_codes)

    def test_rescues_short_high_confidence_low_octave_when_it_can_merge_into_context(self):
        selector = MelodySelector(PitchDetectionConfig())
        result = selector.select(
            [
                Note(pitch="A#3", start_time=0.0, end_time=0.3, confidence=0.9, candidate_id="left"),
                Note(pitch="A#2", start_time=0.34, end_time=0.44, confidence=0.7, candidate_id="short_low"),
                Note(pitch="A#3", start_time=0.48, end_time=0.8, confidence=0.9, candidate_id="right"),
            ]
        )

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.removed_pitch_range, 0)
        self.assertAlmostEqual(result.notes[0].start_time, 0.0, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.8, places=3)
        self.assertIn("short_low", result.notes[0].source_candidate_ids)
        self.assertIn(PRESELECTOR_LOW_OCTAVE_CORRECTED, result.notes[0].reason_codes)

    def test_rejects_short_low_octave_below_short_note_confidence(self):
        selector = MelodySelector(PitchDetectionConfig())
        result = selector.select(
            [
                Note(pitch="A#3", start_time=0.0, end_time=0.3, confidence=0.9, candidate_id="left"),
                Note(pitch="A#2", start_time=0.34, end_time=0.44, confidence=0.61, candidate_id="short_low"),
                Note(pitch="A#3", start_time=0.48, end_time=0.8, confidence=0.9, candidate_id="right"),
            ]
        )

        self.assertNotIn("short_low", result.notes[0].source_candidate_ids)
        self.assertEqual(result.removed_pitch_range, 1)

    def test_short_low_octave_rescue_still_rejects_two_big_gap_split(self):
        selector = MelodySelector(PitchDetectionConfig())
        result = selector.select(
            [
                Note(pitch="A#3", start_time=0.0, end_time=0.3, confidence=0.9, candidate_id="left"),
                Note(pitch="A#2", start_time=1.0, end_time=1.1, confidence=0.7, candidate_id="short_low"),
                Note(pitch="A#3", start_time=2.0, end_time=2.3, confidence=0.9, candidate_id="right"),
            ]
        )

        self.assertEqual([note.candidate_id for note in result.notes], ["left", "right"])
        self.assertEqual(result.removed_pitch_range, 1)

    def test_merge_preserves_contour_bridge_evidence(self):
        selector = MelodySelector(PitchDetectionConfig(melody_merge_gap_sec=0.08, melody_merge_pitch_tolerance_semitones=1))
        notes = [
            Note(
                pitch="C4",
                start_time=0.0,
                end_time=0.3,
                confidence=0.9,
                candidate_id="left",
            ),
            Note(
                pitch="C4",
                start_time=0.34,
                end_time=0.62,
                confidence=0.88,
                reason_codes=[CONTOUR_TO_CANDIDATE_BRIDGE, BRIDGE_FROM_F0_CONTOUR],
                candidate_id="contour_bridge:pc_merge",
                source_candidate_id="contour_bridge:pc_merge",
                candidate_origin=CONTOUR_TO_CANDIDATE_BRIDGE,
                contour_bridge_evidence={"source_contour_id": "pc_merge", "raw_overlap_duration_sec": 0.0},
                contour_bridge_guard_reason_codes=[CONTOUR_CANDIDATE_CONTEXT_GUARDED],
            ),
        ]

        merged, merge_count = selector._merge_adjacent(notes)

        self.assertEqual(merge_count, 1)
        self.assertEqual(len(merged), 1)
        self.assertIn(CONTOUR_TO_CANDIDATE_BRIDGE, merged[0].reason_codes)
        self.assertEqual(merged[0].candidate_origin, CONTOUR_TO_CANDIDATE_BRIDGE)
        self.assertEqual(merged[0].contour_bridge_evidence["source_contour_id"], "pc_merge")
        self.assertIn(CONTOUR_CANDIDATE_CONTEXT_GUARDED, merged[0].contour_bridge_guard_reason_codes)

    def test_selection_preserves_segmentation_evidence_for_unmerged_note(self):
        selector = MelodySelector(PitchDetectionConfig())
        result = selector.select(
            [
                Note(
                    pitch="C4",
                    start_time=0.0,
                    end_time=0.4,
                    confidence=0.9,
                    segmentation_evidence={"quality_factor": 0.82, "voiced_frame_count": 40},
                )
            ]
        )

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].segmentation_evidence["quality_factor"], 0.82)
        self.assertEqual(result.notes[0].segmentation_evidence["voiced_frame_count"], 40)

    def test_postprocessor_defaults_are_conservative(self):
        selector = MelodySelector(PitchDetectionConfig())

        self.assertFalse(selector.postprocessor.config.remove_isolated_fragments_enabled)
        self.assertTrue(selector.postprocessor.config.sustain_short_gaps_enabled)

    def test_filters_low_confidence_short_and_out_of_range_notes(self):
        selector = MelodySelector(PitchDetectionConfig())
        notes = [
            Note(pitch="C2", start_time=0.0, end_time=0.4, confidence=0.9),
            Note(pitch="C4", start_time=0.5, end_time=0.58, confidence=0.9),
            Note(pitch="D4", start_time=0.7, end_time=1.1, confidence=0.4),
            Note(pitch="E4", start_time=1.2, end_time=1.6, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.detected_count, 4)
        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "E4")
        self.assertEqual(result.removed_pitch_range, 1)
        self.assertEqual(result.removed_short, 1)
        self.assertEqual(result.removed_low_confidence, 1)

    def test_rescues_low_octave_candidate_with_local_context(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.52,
                melody_min_duration_sec=0.12,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="A#3", start_time=0.00, end_time=0.30, confidence=0.88),
            Note(pitch="A#2", start_time=0.62, end_time=1.04, confidence=0.68),
            Note(pitch="A#3", start_time=2.00, end_time=2.30, confidence=0.86),
        ]

        result = selector.select(notes)

        self.assertEqual(result.removed_pitch_range, 0)
        rescued = [note for note in result.notes if note.start_time == 0.62]
        self.assertEqual(len(rescued), 1)
        self.assertEqual(rescued[0].pitch, "A#3")
        self.assertIn(PRESELECTOR_LOW_OCTAVE_CORRECTED, rescued[0].reason_codes)

    def test_does_not_rescue_low_octave_without_context(self):
        selector = MelodySelector(PitchDetectionConfig())
        notes = [
            Note(pitch="A#2", start_time=1.00, end_time=1.42, confidence=0.68),
            Note(pitch="F4", start_time=10.00, end_time=10.50, confidence=0.90),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "F4")
        self.assertEqual(result.removed_pitch_range, 1)

    def test_does_not_rescue_low_octave_when_it_splits_one_big_gap_into_two(self):
        selector = MelodySelector(PitchDetectionConfig())
        notes = [
            Note(pitch="A#3", start_time=0.00, end_time=0.30, confidence=0.88),
            Note(pitch="A#2", start_time=1.00, end_time=1.42, confidence=0.68),
            Note(pitch="A#3", start_time=2.00, end_time=2.30, confidence=0.86),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 2)
        self.assertEqual([note.pitch for note in result.notes], ["A#3", "A#3"])
        self.assertEqual(result.removed_pitch_range, 1)

    def test_merges_adjacent_near_pitch_fragments(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="A4", start_time=0.0, end_time=0.30, confidence=0.85),
            Note(pitch="A#4", start_time=0.34, end_time=0.62, confidence=0.82),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertAlmostEqual(result.notes[0].start_time, 0.0, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.62, places=3)
        self.assertGreaterEqual(result.merged_count, 1)

    def test_removes_isolated_big_leap_spike(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_large_jump_semitones=12,
                melody_isolated_note_max_duration_sec=0.25,
                melody_isolated_note_min_confidence=0.62,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.35, confidence=0.9),
            Note(pitch="C6", start_time=0.40, end_time=0.52, confidence=0.58),
            Note(pitch="D4", start_time=0.60, end_time=0.95, confidence=0.9),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 2)
        self.assertEqual([n.pitch for n in result.notes], ["C4", "D4"])
        self.assertEqual(result.removed_big_leap, 1)


    def test_bridge_short_gap_records_reason_code(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=0,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.30, confidence=0.90),
            Note(pitch="C4", start_time=0.35, end_time=0.70, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertIn(SHORT_GAP_BRIDGED, result.notes[0].reason_codes)
        self.assertEqual(result.merged_count, 1)


    def test_retains_high_confidence_bridge_short_note_to_avoid_big_gap(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_min_duration_sec=0.12,
                melody_short_note_min_confidence=0.5,
                melody_bridge_note_retention_enabled=True,
                melody_bridge_note_gap_threshold_sec=0.5,
                melody_bridge_note_small_gap_sec=0.05,
            )
        )
        notes = [
            Note(pitch="A3", start_time=0.00, end_time=0.30, confidence=0.90),
            Note(pitch="C4", start_time=0.48, end_time=0.59, confidence=0.82),
            Note(pitch="E4", start_time=0.86, end_time=1.16, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 3)
        self.assertIn(SHORT_GAP_BRIDGED, result.notes[1].reason_codes)
        self.assertEqual(result.postprocess_action_counts["bridge_note_retention"], 1)

    def test_absorbs_short_note_between_same_pitch_phrase(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.30, confidence=0.92),
            Note(pitch="D4", start_time=0.33, end_time=0.40, confidence=0.56),
            Note(pitch="C4", start_time=0.43, end_time=0.78, confidence=0.90),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "C4")
        self.assertAlmostEqual(result.notes[0].start_time, 0.00, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.78, places=3)
        self.assertIn(SHORT_NOTE_ABSORBED, result.notes[0].reason_codes)
        self.assertEqual(result.postprocess_action_counts["short_note_absorb"], 1)

    def test_corrects_octave_spike_within_phrase(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
                melody_large_jump_semitones=12,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.30, confidence=0.90),
            Note(pitch="C5", start_time=0.33, end_time=0.41, confidence=0.54),
            Note(pitch="C4", start_time=0.44, end_time=0.79, confidence=0.91),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "C4")
        self.assertAlmostEqual(result.notes[0].end_time, 0.79, places=3)
        self.assertIn(OCTAVE_JUMP_CORRECTED, result.postprocess_reason_code_counts)

    def test_smooths_short_inner_pitch_outlier_without_deleting_note(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="E4", start_time=0.00, end_time=0.28, confidence=0.89),
            Note(pitch="F#4", start_time=0.31, end_time=0.43, confidence=0.57),
            Note(pitch="E4", start_time=0.46, end_time=0.76, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "E4")
        self.assertAlmostEqual(result.notes[0].start_time, 0.00, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.76, places=3)


if __name__ == "__main__":
    unittest.main()
