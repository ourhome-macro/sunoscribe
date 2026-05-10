from __future__ import annotations

import unittest

from app.modules.pitch.pitch_contours import PitchContourBuilder, PitchContourConfig
from app.modules.pitch.reason_codes import LOW_CONFIDENCE


def _frame(time_sec: float, midi: float | None, *, confidence: float = 0.8, voiced: bool = True) -> dict:
    return {
        "time_sec": time_sec,
        "midi_float": midi,
        "f0_hz": 440.0 if midi is not None else None,
        "confidence": confidence,
        "voiced": voiced,
    }


class TestPitchContourBuilder(unittest.TestCase):
    def test_groups_voiced_frames_into_contour(self) -> None:
        payload = PitchContourBuilder().build({"backend": "rmvpe", "frames": [_frame(0.0, 60.0), _frame(0.01, 60.1), _frame(0.02, 60.0)]})

        self.assertIsNotNone(payload)
        self.assertEqual(payload["summary"]["contour_count"], 1)
        contour = payload["contours"][0]
        self.assertEqual(contour["frame_count"], 3)
        self.assertAlmostEqual(contour["pitch_center_midi"], 60.0, places=1)

    def test_bridges_short_unvoiced_gap(self) -> None:
        builder = PitchContourBuilder(PitchContourConfig(max_unvoiced_gap_sec=0.04))
        payload = builder.build(
            {
                "frames": [
                    _frame(0.00, 60.0),
                    _frame(0.01, None, confidence=0.0, voiced=False),
                    _frame(0.02, 60.2),
                    _frame(0.20, None, confidence=0.0, voiced=False),
                    _frame(0.30, 62.0),
                ]
            }
        )

        self.assertEqual(payload["summary"]["contour_count"], 2)
        self.assertEqual(payload["contours"][0]["frame_count"], 3)

    def test_vibrato_like_motion_stays_single_contour(self) -> None:
        frames = [_frame(index * 0.01, 60.0 + offset) for index, offset in enumerate([0.0, 0.35, 0.0, -0.35, 0.0, 0.35, 0.0, -0.35, 0.0])]
        payload = PitchContourBuilder().build({"frames": frames})

        self.assertEqual(payload["summary"]["contour_count"], 1)
        self.assertTrue(payload["contours"][0]["has_vibrato"])

    def test_low_confidence_contour_is_marked_not_dropped(self) -> None:
        payload = PitchContourBuilder(PitchContourConfig(min_confidence=0.1, low_confidence_threshold=0.5)).build(
            {"frames": [_frame(0.0, 60.0, confidence=0.2), _frame(0.01, 60.0, confidence=0.25)]}
        )

        self.assertEqual(payload["summary"]["contour_count"], 1)
        self.assertIn(LOW_CONFIDENCE, payload["contours"][0]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
