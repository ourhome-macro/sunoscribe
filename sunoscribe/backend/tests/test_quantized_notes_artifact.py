from __future__ import annotations

import unittest

from app.modules.pitch.quantized_notes_artifact import QuantizedNotesArtifactBuilder, QuantizerArtifactConfig


class TestQuantizedNotesArtifactBuilder(unittest.TestCase):
    def test_builds_quantized_notes_summary(self) -> None:
        artifact = QuantizedNotesArtifactBuilder().build(
            selected_melody={
                "selected_notes": [
                    {"candidate_id": "c1", "start_time_sec": 0.01, "end_time_sec": 0.51, "pitch_center_midi": 60.0, "confidence": 0.9},
                    {"candidate_id": "c2", "start_time_sec": 0.5, "end_time_sec": 0.75, "pitch_center_midi": 62.2, "confidence": 0.8},
                ]
            },
            rhythm_grid={"bpm": 120.0, "beats_per_bar": 4, "beat_unit": 4},
        )

        self.assertEqual(artifact["quantizer_backend"], "dp_v1")
        self.assertFalse(artifact["fallback_used"])
        self.assertEqual(artifact["summary"]["note_count"], 2)
        self.assertEqual(artifact["notes"][0]["source_candidate_id"], "c1")
        self.assertGreaterEqual(artifact["notes"][0]["start_tick"], 0)
        self.assertEqual(artifact["summary"]["max_quantize_error_sec"], 0.01)
        self.assertIn("p95_quantize_error_sec", artifact["summary"])
        self.assertIn("fragmentation", artifact["diagnostics"])
        self.assertIn("overmerge", artifact["diagnostics"])

    def test_can_explicitly_use_local_snap_backend(self) -> None:
        artifact = QuantizedNotesArtifactBuilder(QuantizerArtifactConfig(backend="local_snap")).build(
            selected_melody={
                "selected_notes": [
                    {"candidate_id": "c1", "start_time_sec": 0.01, "end_time_sec": 0.51, "pitch_center_midi": 60.0, "confidence": 0.9},
                ]
            },
            rhythm_grid={"bpm": 120.0, "beats_per_bar": 4, "beat_unit": 4},
        )

        self.assertEqual(artifact["quantizer_backend"], "local_snap")
        self.assertFalse(artifact["fallback_used"])

    def test_dp_v1_fails_explicitly_without_rhythm_grid_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "rhythm grid unavailable"):
            QuantizedNotesArtifactBuilder().build(
                selected_melody={
                    "selected_notes": [
                        {"candidate_id": "c1", "start_time_sec": 0.01, "end_time_sec": 0.51, "pitch_center_midi": 60.0, "confidence": 0.9},
                    ]
                },
                rhythm_grid=None,
            )

    def test_dp_v1_can_fallback_explicitly_without_rhythm_grid(self) -> None:
        artifact = QuantizedNotesArtifactBuilder(QuantizerArtifactConfig(allow_required_fallback=True)).build(
            selected_melody={
                "selected_notes": [
                    {"candidate_id": "c1", "start_time_sec": 0.01, "end_time_sec": 0.51, "pitch_center_midi": 60.0, "confidence": 0.9},
                ]
            },
            rhythm_grid=None,
        )

        self.assertEqual(artifact["quantizer_backend"], "local_snap")
        self.assertTrue(artifact["fallback_used"])
        self.assertEqual(artifact["fallback_reason"], "rhythm_grid_unavailable")
        self.assertIn("dp_fallback", artifact["notes"][0]["reason_codes"])

    def test_dp_v1_uses_global_path_to_avoid_overlap(self) -> None:
        artifact = QuantizedNotesArtifactBuilder().build(
            selected_melody={
                "selected_notes": [
                    {"candidate_id": "long", "start_time_sec": 0.0, "end_time_sec": 0.85, "pitch_center_midi": 60.0, "confidence": 0.9},
                    {"candidate_id": "next", "start_time_sec": 0.76, "end_time_sec": 1.01, "pitch_center_midi": 62.0, "confidence": 0.9},
                ]
            },
            rhythm_grid={"bpm": 120.0, "beat_times": [0.0, 0.5, 1.0, 1.5], "beats_per_bar": 4, "beat_unit": 4},
        )

        self.assertEqual(artifact["quantizer_backend"], "dp_v1")
        self.assertGreaterEqual(artifact["notes"][0]["quantized_duration_sec"], 0.68)
        self.assertLessEqual(artifact["notes"][0]["quantized_end_time_sec"], artifact["notes"][1]["quantized_start_time_sec"])

    def test_dp_v1_protects_duration_from_over_short_quantization(self) -> None:
        artifact = QuantizedNotesArtifactBuilder(
            QuantizerArtifactConfig(allowed_durations_beats=[0.25, 0.5, 1.0], min_quantized_duration_ratio=0.8)
        ).build(
            selected_melody={
                "selected_notes": [
                    {
                        "candidate_id": "sung_long",
                        "start_time_sec": 0.0,
                        "end_time_sec": 0.80,
                        "pitch_center_midi": 60.0,
                        "confidence": 0.9,
                    },
                ]
            },
            rhythm_grid={"bpm": 120.0, "beat_times": [0.0, 0.5, 1.0, 1.5], "beats_per_bar": 4, "beat_unit": 4},
        )

        self.assertGreaterEqual(artifact["notes"][0]["quantized_duration_sec"], 0.64)
        self.assertNotIn("quantized_duration_too_short", artifact["notes"][0]["reason_codes"])

    def test_marks_high_error_uncertain(self) -> None:
        artifact = QuantizedNotesArtifactBuilder(QuantizerArtifactConfig(high_error_sec=0.001)).build(
            selected_melody={"selected_notes": [{"candidate_id": "late", "start_time_sec": 0.38, "end_time_sec": 0.88, "pitch_center_midi": 60.0, "confidence": 0.9}]},
            rhythm_grid={"bpm": 120.0},
        )

        self.assertTrue(artifact["notes"][0]["uncertain"])
        self.assertEqual(artifact["summary"]["uncertain_count"], 1)


if __name__ == "__main__":
    unittest.main()

