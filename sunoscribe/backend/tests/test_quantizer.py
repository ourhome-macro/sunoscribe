import unittest

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.quantizer import NoteQuantizer
from app.modules.pitch.types import Note, NoteType


class TestNoteQuantizer(unittest.TestCase):
    def test_quantize_assigns_note_type_and_measure(self):
        cfg = PitchDetectionConfig(quantize_mode="adaptive", quantize_precision=0.25)
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.9),
            Note(pitch="E4", start_time=2.0, end_time=2.5, confidence=0.8),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5])

        self.assertEqual(len(quantized), 2)
        self.assertEqual(quantized[0].duration_beats, 1.0)
        self.assertEqual(quantized[0].note_type, NoteType.QUARTER)
        self.assertEqual(quantized[0].measure_num, 1)
        self.assertEqual(quantized[1].measure_num, 2)

    def test_quantize_with_invalid_bpm_returns_empty(self):
        cfg = PitchDetectionConfig()
        quantizer = NoteQuantizer(cfg)
        notes = [Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.9)]

        quantized = quantizer.quantize(notes, bpm=0.0, beat_times=[])
        self.assertEqual(quantized, [])

    def test_measure_location_uses_configured_beats_per_bar(self):
        cfg = PitchDetectionConfig(beats_per_bar=3, quantize_precision=0.25)
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.9),
            Note(pitch="D4", start_time=1.6, end_time=2.1, confidence=0.9),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5, 2.0])

        self.assertEqual(quantized[0].measure_num, 1)
        self.assertEqual(quantized[1].measure_num, 2)

    def test_filters_very_short_notes_by_min_duration(self):
        cfg = PitchDetectionConfig(quantize_min_duration_beats=0.25, quantize_precision=0.125)
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.06, confidence=0.9),  # 0.12 beat @ 120 BPM
            Note(pitch="D4", start_time=0.1, end_time=0.35, confidence=0.9),  # 0.5 beat
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].pitch, "D4")

    def test_adaptive_tolerance_for_triplet_and_dotted(self):
        cfg = PitchDetectionConfig(
            quantize_mode="adaptive",
            quantize_precision=0.01,
            adaptive_triplet_tolerance_beats=0.08,
            adaptive_dotted_tolerance_beats=0.12,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.71, confidence=0.9),   # ≈1.42 beats -> dotted quarter window
            Note(pitch="E4", start_time=0.8, end_time=1.13, confidence=0.9),  # ≈0.66 beats -> triplet window
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5])

        self.assertEqual(len(quantized), 2)
        self.assertEqual(quantized[0].note_type, NoteType.DOTTED_QUARTER)
        self.assertEqual(quantized[1].note_type, NoteType.TRIPLET)

    def test_filters_low_confidence_noise_notes(self):
        cfg = PitchDetectionConfig(
            quantize_noise_confidence_floor=0.6,
            quantize_min_duration_beats=0.125,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.55),
            Note(pitch="D4", start_time=0.6, end_time=1.1, confidence=0.85),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].pitch, "D4")

    def test_merges_adjacent_same_pitch_notes(self):
        cfg = PitchDetectionConfig(
            quantize_merge_same_pitch_enabled=True,
            quantize_merge_same_pitch_gap_sec=0.08,
            quantize_merge_min_confidence=0.5,
            quantize_precision=0.125,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="A4", start_time=0.0, end_time=0.4, confidence=0.9),
            Note(pitch="A4", start_time=0.44, end_time=0.9, confidence=0.88),
            Note(pitch="G4", start_time=1.0, end_time=1.4, confidence=0.9),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5])

        self.assertEqual(len(quantized), 2)
        self.assertEqual(quantized[0].pitch, "A4")
        self.assertAlmostEqual(quantized[0].start_time, 0.0, places=3)
        self.assertAlmostEqual(quantized[0].end_time, 0.9, places=3)

    def test_resolves_overlapped_notes(self):
        cfg = PitchDetectionConfig(
            quantize_overlap_resolution_enabled=True,
            quantize_overlap_min_gap_sec=0.01,
            quantize_merge_same_pitch_enabled=False,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.6, confidence=0.95),
            Note(pitch="E4", start_time=0.4, end_time=0.9, confidence=0.6),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 2)
        self.assertLessEqual(quantized[0].end_time, quantized[1].start_time)


    def test_merge_preserves_combined_lineage(self):
        cfg = PitchDetectionConfig(
            quantize_merge_same_pitch_enabled=True,
            quantize_merge_same_pitch_gap_sec=0.08,
            quantize_merge_min_confidence=0.5,
            quantize_precision=0.125,
        )
        quantizer = NoteQuantizer(cfg)
        notes = [
            Note(
                pitch="C4",
                start_time=0.0,
                end_time=0.4,
                confidence=0.9,
                candidate_id="cand_a",
                source_candidate_id="cand_a",
                source_candidate_ids=["cand_a"],
                source_contour_ids=["pc_a"],
                source_f0_frame_range={"start_frame_index": 1, "end_frame_index": 4},
                candidate_origin="contour_seed",
                segmentation_evidence={"left": True},
            ),
            Note(
                pitch="C4",
                start_time=0.44,
                end_time=0.9,
                confidence=0.88,
                candidate_id="cand_b",
                source_candidate_id="cand_b",
                source_candidate_ids=["cand_b"],
                source_contour_ids=["pc_b"],
                source_f0_frame_range={"start_frame_index": 5, "end_frame_index": 9},
                candidate_origin="contour_seed",
                segmentation_evidence={"right": True},
            ),
        ]

        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].source_candidate_id, "cand_a")
        self.assertEqual(quantized[0].source_candidate_ids, ["cand_a", "cand_b"])
        self.assertEqual(quantized[0].source_contour_ids, ["pc_a", "pc_b"])
        self.assertEqual(quantized[0].source_f0_frame_range["start_frame_index"], 1)
        self.assertEqual(quantized[0].source_f0_frame_range["end_frame_index"], 9)
        self.assertEqual(quantized[0].segmentation_evidence["left"], True)
        self.assertEqual(quantized[0].segmentation_evidence["right"], True)

    def test_overlap_trim_preserves_lineage(self):
        cfg = PitchDetectionConfig(
            quantize_overlap_resolution_enabled=True,
            quantize_overlap_min_gap_sec=0.01,
            quantize_merge_same_pitch_enabled=False,
        )
        quantizer = NoteQuantizer(cfg)
        notes = [
            Note(
                pitch="C4",
                start_time=0.0,
                end_time=0.6,
                confidence=0.95,
                candidate_id="cand_a",
                source_candidate_id="cand_a",
                source_candidate_ids=["cand_a"],
                source_contour_ids=["pc_a"],
                source_f0_frame_range={"start_frame_index": 0, "end_frame_index": 6},
            ),
            Note(
                pitch="E4",
                start_time=0.4,
                end_time=0.9,
                confidence=0.6,
                candidate_id="cand_b",
                source_candidate_id="cand_b",
                source_candidate_ids=["cand_b"],
                source_contour_ids=["pc_b"],
                source_f0_frame_range={"start_frame_index": 4, "end_frame_index": 9},
            ),
        ]

        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 2)
        self.assertLessEqual(quantized[0].end_time, quantized[1].start_time)
        self.assertEqual(quantized[0].source_candidate_ids, ["cand_a"])
        self.assertEqual(quantized[0].source_contour_ids, ["pc_a"])
        self.assertEqual(quantized[0].source_f0_frame_range["end_frame_index"], 6)
        self.assertEqual(quantized[1].source_candidate_ids, ["cand_b"])
        self.assertEqual(quantized[1].source_contour_ids, ["pc_b"])
        self.assertEqual(quantized[1].source_f0_frame_range["start_frame_index"], 4)

    def test_optional_near_pitch_merge(self):
        cfg = PitchDetectionConfig(
            quantize_merge_same_pitch_enabled=True,
            quantize_merge_near_pitch_enabled=True,
            quantize_merge_near_pitch_max_semitone=1,
            quantize_merge_same_pitch_gap_sec=0.06,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.9),
            Note(pitch="C#4", start_time=0.34, end_time=0.7, confidence=0.88),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].pitch, "C4")
        self.assertAlmostEqual(quantized[0].end_time, 0.7, places=3)

    def test_merge_preserves_combined_lineage(self):
        cfg = PitchDetectionConfig(
            quantize_merge_same_pitch_enabled=True,
            quantize_merge_same_pitch_gap_sec=0.08,
            quantize_merge_min_confidence=0.45,
            quantize_precision=0.125,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(
                pitch="A4",
                start_time=0.0,
                end_time=0.4,
                confidence=0.9,
                candidate_id="cand_a",
                source_candidate_id="cand_a",
                source_candidate_ids=["cand_a"],
                source_contour_ids=["pc_a"],
                segmentation_evidence={
                    "source_f0_frame_range": {"start_frame_index": 0, "end_frame_index": 4, "frame_count": 5}
                },
            ),
            Note(
                pitch="A4",
                start_time=0.44,
                end_time=0.9,
                confidence=0.88,
                candidate_id="cand_b",
                source_candidate_id="cand_b",
                source_candidate_ids=["cand_b"],
                source_contour_ids=["pc_b"],
                segmentation_evidence={
                    "source_f0_frame_range": {"start_frame_index": 5, "end_frame_index": 9, "frame_count": 5}
                },
            ),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].source_candidate_id, "cand_a")
        self.assertEqual(quantized[0].source_candidate_ids, ["cand_a", "cand_b"])
        self.assertEqual(quantized[0].source_contour_ids, ["pc_a", "pc_b"])
        frame_range = quantized[0].segmentation_evidence["source_f0_frame_range"]
        self.assertEqual(frame_range["start_frame_index"], 0)
        self.assertEqual(frame_range["end_frame_index"], 9)
        self.assertEqual(frame_range["frame_count"], 10)

    def test_overlap_trim_preserves_lineage(self):
        cfg = PitchDetectionConfig(
            quantize_overlap_resolution_enabled=True,
            quantize_overlap_min_gap_sec=0.01,
            quantize_merge_same_pitch_enabled=False,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(
                pitch="C4",
                start_time=0.0,
                end_time=0.6,
                confidence=0.95,
                candidate_id="cand_c",
                source_candidate_id="cand_c",
                source_candidate_ids=["cand_c"],
                source_contour_ids=["pc_c"],
                segmentation_evidence={
                    "source_f0_frame_range": {"start_frame_index": 0, "end_frame_index": 6, "frame_count": 7}
                },
            ),
            Note(
                pitch="E4",
                start_time=0.4,
                end_time=0.9,
                confidence=0.6,
                candidate_id="cand_e",
                source_candidate_id="cand_e",
                source_candidate_ids=["cand_e"],
                source_contour_ids=["pc_e"],
                segmentation_evidence={
                    "source_f0_frame_range": {"start_frame_index": 4, "end_frame_index": 9, "frame_count": 6}
                },
            ),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 2)
        self.assertLessEqual(quantized[0].end_time, quantized[1].start_time)
        self.assertEqual(quantized[0].source_candidate_ids, ["cand_c"])
        self.assertEqual(quantized[0].source_contour_ids, ["pc_c"])
        self.assertEqual(quantized[1].source_candidate_ids, ["cand_e"])
        self.assertEqual(quantized[1].source_contour_ids, ["pc_e"])


if __name__ == "__main__":
    unittest.main()
