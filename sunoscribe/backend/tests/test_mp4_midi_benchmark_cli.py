from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.scripts.mp4_midi_benchmark import main


def _write_midi(path: Path) -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(program=0, name="melody")
    instrument.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=0.5))
    midi.instruments.append(instrument)
    midi.write(str(path))


class Mp4MidiBenchmarkCliTests(unittest.TestCase):
    def test_validate_writes_dataset_and_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples = root / "samples"
            output_root = root / "runs"
            (samples / "source_mp4").mkdir(parents=True)
            (samples / "source_mid").mkdir()
            (samples / "source_mp4" / "Song.mp4").write_bytes(b"not real mp4")
            _write_midi(samples / "source_mid" / "Song.mid")
            manifest = samples / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "root": ".",
                        "samples": [
                            {
                                "id": "song",
                                "input_mp4": "source_mp4/Song.mp4",
                                "expected_midi": "source_mid/Song.mid",
                                "expected_melody_track": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "validate",
                    "--manifest",
                    str(manifest),
                    "--output-root",
                    str(output_root),
                    "--run-id",
                    "test_run",
                    "--skip-checksum",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_root / "test_run" / "dataset_report.json").exists())
            self.assertTrue((output_root / "test_run" / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
