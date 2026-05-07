from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.modules.benchmark.dataset import BenchmarkSample
from app.modules.benchmark.midi_metrics import MidiMetricConfig
from app.scripts.mp4_midi_benchmark import _compute_metrics_stage, main


def _write_midi(path: Path) -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(program=0, name="melody")
    instrument.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=0.5))
    midi.instruments.append(instrument)
    midi.write(str(path))


def _write_dual_track_midi(path: Path) -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    lead = pretty_midi.Instrument(program=0, name="Lead Vocal")
    lead.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=0.5))
    hook = pretty_midi.Instrument(program=0, name="Instrumental Hook")
    hook.notes.append(pretty_midi.Note(velocity=90, pitch=72, start=0.0, end=0.5))
    midi.instruments.extend([lead, hook])
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

    def test_doctor_writes_readiness_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _write_manifest_fixture(root)
            output_root = root / "runs"

            exit_code = main(
                [
                    "doctor",
                    "--manifest",
                    str(manifest),
                    "--output-root",
                    str(output_root),
                    "--run-id",
                    "doctor_run",
                    "--skip-checksum",
                ]
            )

            self.assertIn(exit_code, {0, 2})
            self.assertTrue((output_root / "doctor_run" / "readiness_report.json").exists())
            self.assertTrue((output_root / "doctor_run" / "summary.md").exists())

    def test_run_stops_when_readiness_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _write_manifest_fixture(root)
            output_root = root / "runs"

            with patch("app.scripts.mp4_midi_benchmark.build_mvp_readiness_report") as readiness_mock:
                readiness_mock.return_value.status = "fail"
                readiness_mock.return_value.to_dict.return_value = {
                    "status": "fail",
                    "checks": [
                        {
                            "name": "vocal_separator",
                            "status": "fail",
                            "required": True,
                            "message": "missing",
                            "details": {},
                        }
                    ],
                    "blocking_checks": [],
                    "notes": [],
                }

                exit_code = main(
                    [
                        "run",
                        "--manifest",
                        str(manifest),
                        "--output-root",
                        str(output_root),
                        "--run-id",
                        "blocked_run",
                        "--skip-checksum",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertTrue((output_root / "blocked_run" / "readiness_report.json").exists())
            self.assertFalse((output_root / "blocked_run" / "song").exists())

    def test_metrics_stage_reads_produced_lead_track_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = root / "expected.mid"
            produced = root / "produced.mid"
            _write_midi(expected)
            _write_dual_track_midi(produced)
            sample = BenchmarkSample(
                id="song",
                input_mp4=root / "song.mp4",
                expected_midi=expected,
                expected_melody_track=1,
            )

            stage, payload = _compute_metrics_stage(
                sample=sample,
                produced_midi_path=produced,
                metric_config=MidiMetricConfig(onset_tolerance_sec=0.12),
            )

        self.assertEqual(stage.status, "success")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["metrics"]["predicted_note_count"], 1)
        self.assertEqual(payload["metrics"]["note_f1"], 1.0)
        self.assertEqual(payload["instrumental_hook_note_count"], 1)
        self.assertIsNotNone(payload["predicted_lead_track"])


if __name__ == "__main__":
    unittest.main()


def _write_manifest_fixture(root: Path) -> Path:
    samples = root / "samples"
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
    return manifest
