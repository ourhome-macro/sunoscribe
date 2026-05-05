from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.dataset import (
    build_dataset_report,
    compute_sha256,
    discover_sample_pairs,
    load_manifest,
    normalize_sample_key,
)


class BenchmarkDatasetTests(unittest.TestCase):
    def test_normalize_sample_key_handles_unicode_spaces_and_case(self) -> None:
        self.assertEqual(normalize_sample_key("  See   You Again "), "see you again")
        self.assertEqual(normalize_sample_key("枫 "), "枫")

    def test_discover_pairs_reports_unpaired_and_duplicate_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mp4_dir = root / "source_mp4"
            mid_dir = root / "source_mid"
            mp4_dir.mkdir()
            mid_dir.mkdir()
            (mp4_dir / "Song.mp4").write_bytes(b"mp4")
            (mp4_dir / "Song .mp4").write_bytes(b"duplicate")
            (mp4_dir / "OnlyVideo.mp4").write_bytes(b"mp4")
            (mid_dir / "Song.mid").write_bytes(b"mid")
            (mid_dir / "OnlyMidi.mid").write_bytes(b"mid")

            report = discover_sample_pairs(root)

            self.assertEqual(report["paired_count"], 1)
            self.assertEqual(len(report["mp4_only"]), 1)
            self.assertEqual(len(report["midi_only"]), 1)
            self.assertIn("song", report["duplicate_mp4_keys"])

    def test_manifest_loading_and_checksum_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples = root / "samples"
            (samples / "source_mp4").mkdir(parents=True)
            (samples / "source_mid").mkdir()
            mp4 = samples / "source_mp4" / "Song.mp4"
            midi = samples / "source_mid" / "Song.mid"
            mp4.write_bytes(b"mp4")
            midi.write_bytes(b"mid")
            manifest_path = samples / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "root": ".",
                        "samples": [
                            {
                                "id": "song",
                                "input_mp4": "source_mp4/Song.mp4",
                                "expected_midi": "source_mid/Song.mid",
                                "expected_melody_track": 0,
                                "input_sha256": compute_sha256(mp4),
                                "expected_sha256": compute_sha256(midi),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manifest = load_manifest(manifest_path)
            report = build_dataset_report(samples_root=samples, manifest=manifest, manifest_path=manifest_path)

            self.assertEqual(len(manifest.samples), 1)
            self.assertEqual(report.enabled_count, 1)
            self.assertFalse(report.errors)


if __name__ == "__main__":
    unittest.main()
