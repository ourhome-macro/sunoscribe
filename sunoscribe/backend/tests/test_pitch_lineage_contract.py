import unittest

from app.modules.pitch.melody_selection_artifact import RuleBasedMelodySelector
from app.modules.pitch.note_candidate_builder import NoteCandidateBuilder
from app.modules.pitch.quantized_notes_artifact import QuantizedNotesArtifactBuilder


def _frame(time_sec: float, midi: float, *, confidence: float = 0.95, frame_index: int = 0) -> dict:
    return {
        "frame_index": frame_index,
        "time_sec": time_sec,
        "pitch_midi": midi,
        "midi_float": midi,
        "confidence": confidence,
        "voiced": True,
    }


class TestPitchLineageContract(unittest.TestCase):
    def test_candidate_selection_quantization_preserve_f0_lineage(self) -> None:
        f0_track = {
            "backend": "rmvpe",
            "source_stem": "vocals",
            "input_audio_path": "vocals.wav",
            "frames": [
                _frame(0.00, 60.0, frame_index=0),
                _frame(0.05, 60.0, frame_index=1),
                _frame(0.10, 60.01, frame_index=2),
                _frame(0.15, 60.0, frame_index=3),
            ],
        }
        pitch_contours = {
            "version": "pitch_contours_v1",
            "source_f0_track": "rmvpe",
            "contours": [
                {
                    "id": "pc_lineage_1",
                    "start_time_sec": 0.0,
                    "end_time_sec": 0.16,
                    "duration_sec": 0.16,
                    "pitch_center_midi": 60.0,
                    "mean_confidence": 0.95,
                    "voiced_ratio": 1.0,
                    "stability": 0.99,
                    "frame_count": 4,
                    "frame_samples": [
                        {"time_sec": 0.00, "pitch_midi": 60.0, "confidence": 0.95, "voiced": True},
                        {"time_sec": 0.05, "pitch_midi": 60.0, "confidence": 0.95, "voiced": True},
                        {"time_sec": 0.10, "pitch_midi": 60.01, "confidence": 0.95, "voiced": True},
                        {"time_sec": 0.15, "pitch_midi": 60.0, "confidence": 0.95, "voiced": True},
                    ],
                }
            ],
        }

        candidate_set = NoteCandidateBuilder().build(
            f0_track=f0_track,
            pitch_contours=pitch_contours,
            raw_candidates={"melody_candidates": {"notes": []}},
        )
        self.assertEqual(candidate_set["schema_version"], "note_candidate_set_v2")
        candidate = candidate_set["melody_candidates"]["notes"][0]
        self.assertTrue(candidate["candidate_id"])
        self.assertEqual(candidate["source_contour_ids"], ["pc_lineage_1"])
        self.assertEqual(candidate["source_f0_frame_range"]["start_frame_index"], 0)
        self.assertEqual(candidate["source_f0_frame_range"]["end_frame_index"], 3)

        selected = RuleBasedMelodySelector().select(
            note_candidates=candidate_set,
            pitch_contours=pitch_contours,
        )
        self.assertEqual(selected["schema_version"], "selected_melody_v2")
        selected_note = selected["selected_notes"][0]
        self.assertEqual(selected_note["candidate_id"], candidate["candidate_id"])
        self.assertEqual(selected_note["source_candidate_id"], candidate["candidate_id"])
        self.assertIn(candidate["candidate_id"], selected_note["source_candidate_ids"])
        self.assertEqual(selected_note["source_contour_ids"], ["pc_lineage_1"])
        self.assertEqual(selected_note["source_f0_frame_range"], candidate["source_f0_frame_range"])

        quantized = QuantizedNotesArtifactBuilder().build(
            selected_melody=selected,
            rhythm_grid={
                "tempo_bpm": 120.0,
                "bpm": 120.0,
                "beat_times": [0.0, 0.5, 1.0],
                "beats_per_bar": 4,
                "beat_unit": 4,
            },
        )
        self.assertEqual(quantized["schema_version"], "quantized_note_set_v2")
        quantized_note = quantized["notes"][0]
        self.assertEqual(quantized_note["source_candidate_id"], candidate["candidate_id"])
        self.assertIn(candidate["candidate_id"], quantized_note["source_candidate_ids"])
        self.assertEqual(quantized_note["source_contour_ids"], ["pc_lineage_1"])
        self.assertEqual(quantized_note["source_f0_frame_range"], candidate["source_f0_frame_range"])


if __name__ == "__main__":
    unittest.main()
