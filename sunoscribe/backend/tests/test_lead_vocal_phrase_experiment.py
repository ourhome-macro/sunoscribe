from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.scripts.lead_vocal_phrase_experiment import main


class LeadVocalPhraseExperimentTests(unittest.TestCase):
    def test_script_writes_multiple_midi_variants(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pitch_dir = root / "pitch"
            pitch_dir.mkdir(parents=True, exist_ok=True)
            (pitch_dir / "selected_melody.json").write_text(
                json.dumps(
                    {
                        "selected_notes": [
                            {
                                "candidate_id": "a",
                                "pitch": "C4",
                                "start_time_sec": 0.0,
                                "end_time_sec": 0.3,
                                "confidence": 0.9,
                                "reason_codes": [],
                                "source_candidate_ids": ["a"],
                                "source_contour_ids": ["pc_1"],
                            },
                            {
                                "candidate_id": "b",
                                "pitch": "C4",
                                "start_time_sec": 0.35,
                                "end_time_sec": 0.7,
                                "confidence": 0.88,
                                "reason_codes": [],
                                "source_candidate_ids": ["b"],
                                "source_contour_ids": ["pc_1"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (pitch_dir / "note_candidates.json").write_text(
                json.dumps(
                    {
                        "melody_candidates": {
                            "notes": [
                                {
                                    "candidate_id": "a",
                                    "pitch": "C4",
                                    "start_time_sec": 0.0,
                                    "end_time_sec": 0.3,
                                    "confidence": 0.9,
                                    "reason_codes": [],
                                    "source_candidate_ids": ["a"],
                                    "source_contour_ids": ["pc_1"],
                                },
                                {
                                    "candidate_id": "b",
                                    "pitch": "C4",
                                    "start_time_sec": 0.35,
                                    "end_time_sec": 0.7,
                                    "confidence": 0.88,
                                    "reason_codes": [],
                                    "source_candidate_ids": ["b"],
                                    "source_contour_ids": ["pc_1"],
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (pitch_dir / "rhythm_grid.json").write_text(
                json.dumps({"bpm": 120.0, "beat_times": [0.0, 0.5, 1.0, 1.5]}),
                encoding="utf-8",
            )
            out_dir = root / "exports"

            exit_code = main(["--pitch-dir", str(pitch_dir), "--output-dir", str(out_dir)])

            self.assertEqual(exit_code, 0)
            summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertIn("baseline_selected", summary["variants"])
            self.assertIn("phrase_sustain_heavy", summary["variants"])
            self.assertIn("listen_same_contour_merge_strict", summary["variants"])
            self.assertTrue((out_dir / "baseline_selected.mid").exists())
            self.assertTrue((out_dir / "phrase_cleanup_aggressive.mid").exists())
            self.assertTrue((out_dir / "listen_same_contour_merge_strict.mid").exists())


if __name__ == "__main__":
    unittest.main()
