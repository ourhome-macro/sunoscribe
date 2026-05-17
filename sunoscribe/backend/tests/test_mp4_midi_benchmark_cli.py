from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.benchmark.dataset import BenchmarkSample
from app.modules.benchmark.midi_metrics import MidiMetricConfig
from app.scripts.mp4_midi_benchmark import (
    SampleRunResult,
    _aggregate_metrics_for_reference_status,
    _compute_metrics_stage,
    _quality_gate_stage,
    _reference_review_sample,
    _write_summary_files,
    main,
)


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


def _write_sequence_midi(path: Path, *, start_offset: float = 0.0, note_count: int = 12, duration: float = 1.0, pitch_offset: int = 0) -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(program=0, name="Lead Vocal")
    for index in range(note_count):
        start = start_offset + index * duration
        instrument.notes.append(pretty_midi.Note(velocity=90, pitch=60 + pitch_offset + (index % 3), start=start, end=start + duration))
    midi.instruments.append(instrument)
    midi.write(str(path))


class _FakeAudioAnalysisService:
    produced_midi_source: Path | None = None
    should_raise = False

    def __init__(self, *, projects_root: Path) -> None:
        self.projects_root = Path(projects_root)

    async def process_audio(self, input_path: Path, options: object) -> SimpleNamespace:
        if self.should_raise:
            raise RuntimeError("pipeline exploded")
        project_id = getattr(options, "project_id")
        workspace = self.projects_root / project_id
        export_dir = workspace / "exports"
        revision_dir = workspace / "revisions" / "machine-0001-fake"
        revision_export_dir = revision_dir / "exports"
        preprocess_dir = workspace / "preprocess"
        separation_dir = workspace / "separation"
        pitch_dir = workspace / "pitch"
        for directory in [export_dir, revision_export_dir, preprocess_dir, separation_dir, pitch_dir]:
            directory.mkdir(parents=True, exist_ok=True)
        midi_path = revision_export_dir / "score.mid"
        musicxml_path = revision_export_dir / "score.musicxml"
        manifest_path = revision_dir / "artifact_manifest.json"
        if self.produced_midi_source is None:
            raise RuntimeError("missing produced MIDI fixture")
        midi_path.write_bytes(self.produced_midi_source.read_bytes())
        musicxml_path.write_text("<score-partwise version='3.1'/>", encoding="utf-8")
        manifest_path.write_text(json.dumps({"artifacts": [{"artifact_type": "midi", "path": str(midi_path)}]}), encoding="utf-8")
        print("fake pipeline stdout")
        return SimpleNamespace(
            midi_path=str(midi_path),
            musicxml_path=str(musicxml_path),
            score_revision={"revision_id": "machine-0001-fake", "revision_number": 1, "revision_type": "machine", "score_type": "lead_vocal", "revision_dir": str(revision_dir)},
            artifact_manifest_path=str(manifest_path),
            artifact_manifest=[{"artifact_type": "midi", "path": str(midi_path)}],
            to_dict=lambda: {
                "source_audio_path": str(input_path),
                "normalized_audio_path": str(preprocess_dir / "source.wav"),
                "vocals_path": str(separation_dir / "vocals.wav"),
                "accompaniment_path": str(separation_dir / "accompaniment.wav"),
                "midi_path": str(midi_path),
                "stem_paths": {
                    "vocals": str(separation_dir / "vocals.wav"),
                    "accompaniment": str(separation_dir / "accompaniment.wav"),
                },
                "f0_track": {"frames": []},
                "note_candidates": {"melody_candidates": {}},
                "rhythm_grid": {"beat_times": []},
                "score_data": {"measures": []},
                "warnings": [],
            },
        )


class Mp4MidiBenchmarkCliTests(unittest.TestCase):
    def test_reference_review_flags_high_expected_note_count(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "dense_reference",
                "status": "quality_failed",
                "metrics": {"expected_note_count": 1200, "predicted_note_count": 150, "note_recall": 0.02},
                "audibility": {"expected_duration_sec": 120.0, "first_note_delay_sec": 0.0},
                "alignment": {"best_time_shift_note_recall": 0.02, "dtw": {"dtw_pitch_match_recall_proxy": 0.03, "best_dtw_octave_shift_semitones": 0}},
                "quality_gate": {"failed_checks": []},
            }
        )

        self.assertEqual(sample["reference_status"], "reference_suspect")
        self.assertIn("expected_note_count_too_high", sample["reference_suspect_reasons"])
        self.assertIn("expected_note_density_too_high", sample["reference_suspect_reasons"])

    def test_reference_review_flags_dtw_and_octave_suspects(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "octave_dtw",
                "status": "quality_failed",
                "metrics": {"expected_note_count": 100, "predicted_note_count": 90, "note_recall": 0.04, "gap50_ratio": 0.1},
                "audibility": {"expected_duration_sec": 80.0, "first_note_delay_sec": 0.0},
                "alignment": {"best_time_shift_note_recall": 0.04, "dtw": {"dtw_pitch_match_recall_proxy": 0.22, "best_dtw_octave_shift_semitones": 12}},
                "quality_gate": {"failed_checks": []},
            }
        )

        self.assertEqual(sample["reference_status"], "reference_suspect")
        self.assertIn("octave_reference_suspect", sample["reference_suspect_reasons"])
        self.assertIn("dtw_sequence_alignment_suspect", sample["reference_suspect_reasons"])

    def test_reference_review_treats_sparse_dtw_lift_as_prediction_diagnostic(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "sparse_dtw",
                "status": "quality_failed",
                "metrics": {
                    "expected_note_count": 408,
                    "predicted_note_count": 93,
                    "note_recall": 0.0392,
                    "gap50_ratio": 0.8913,
                    "octave_shift_applied": 0,
                },
                "audibility": {"expected_duration_sec": 176.3, "first_note_delay_sec": 1.67},
                "alignment": {
                    "best_time_shift_note_recall": 0.0564,
                    "dtw": {"dtw_pitch_match_recall_proxy": 0.1936, "best_dtw_octave_shift_semitones": 0},
                },
                "quality_gate": {"failed_checks": ["midi_coverage_ratio", "note_recall"]},
            }
        )

        self.assertEqual(sample["reference_status"], "likely_comparable")
        self.assertNotIn("dtw_sequence_alignment_suspect", sample["reference_suspect_reasons"])
        self.assertIn("sequence_alignment_improves_fragmented_prediction", sample["prediction_diagnostic_reasons"])

    def test_reference_review_treats_fragmented_dtw_lift_as_prediction_diagnostic(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "fragmented_dtw",
                "status": "quality_failed",
                "metrics": {
                    "expected_note_count": 408,
                    "predicted_note_count": 209,
                    "note_recall": 0.0686,
                    "note_f1": 0.0908,
                    "gap50_ratio": 0.7163,
                    "octave_shift_applied": 0,
                },
                "audibility": {"expected_duration_sec": 176.3, "first_note_delay_sec": 1.4},
                "alignment": {
                    "pred_to_exp_shift_sec": -0.942,
                    "shift_corrected_f1": 0.5932,
                    "best_time_shift_note_recall": 0.1152,
                    "dtw": {"dtw_pitch_match_recall_proxy": 0.3799, "best_dtw_octave_shift_semitones": 0},
                },
                "quality_gate": {"failed_checks": ["midi_coverage_ratio"]},
            }
        )

        self.assertEqual(sample["reference_status"], "likely_comparable")
        self.assertNotIn("dtw_sequence_alignment_suspect", sample["reference_suspect_reasons"])
        self.assertIn("sequence_alignment_improves_fragmented_prediction", sample["prediction_diagnostic_reasons"])

    def test_reference_review_flags_near_threshold_first_note_offset(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "late_vocal_reference",
                "status": "quality_failed",
                "metrics": {"expected_note_count": 666, "predicted_note_count": 174, "note_recall": 0.0015},
                "audibility": {"expected_duration_sec": 224.25, "first_note_delay_sec": 14.23},
                "alignment": {"best_time_shift_note_recall": 0.031, "dtw": {"dtw_pitch_match_recall_proxy": 0.20, "best_dtw_octave_shift_semitones": 12}},
                "quality_gate": {"failed_checks": ["note_recall"]},
            }
        )

        self.assertEqual(sample["reference_status"], "reference_suspect")
        self.assertIn("first_note_offset_suspect", sample["reference_suspect_reasons"])
        self.assertIn("time_origin_needs_review", sample["reference_suspect_reasons"])
        self.assertEqual(sample["first_note_delay_sec"], 14.23)

    def test_reference_review_accepts_auto_corrected_octave_shift(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "auto_octave",
                "status": "success",
                "metrics": {
                    "expected_note_count": 408,
                    "predicted_note_count": 169,
                    "note_recall": 0.0907,
                    "octave_shift_applied": 12,
                    "octave_shift_target": "predicted",
                    "median_pitch_delta_raw": -13.0,
                },
                "audibility": {"expected_duration_sec": 176.3, "first_note_delay_sec": 1.39},
                "alignment": {
                    "best_time_shift_note_recall": 0.0539,
                    "dtw": {"dtw_pitch_match_recall_proxy": 0.2941, "best_dtw_octave_shift_semitones": 12},
                },
                "quality_gate": {"failed_checks": []},
            }
        )

        self.assertEqual(sample["reference_status"], "likely_comparable")
        self.assertNotIn("octave_reference_suspect", sample["reference_suspect_reasons"])
        self.assertNotIn("dtw_sequence_alignment_suspect", sample["reference_suspect_reasons"])

    def test_reference_review_keeps_comparable_sample_clean(self) -> None:
        sample = _reference_review_sample(
            {
                "sample_id": "clean",
                "status": "success",
                "metrics": {"expected_note_count": 80, "predicted_note_count": 75, "note_recall": 0.2},
                "audibility": {"expected_duration_sec": 80.0, "first_note_delay_sec": 1.0},
                "alignment": {"best_time_shift_note_recall": 0.2, "dtw": {"dtw_pitch_match_recall_proxy": 0.22, "best_dtw_octave_shift_semitones": 0}},
                "quality_gate": {"failed_checks": []},
            }
        )

        self.assertEqual(sample["reference_status"], "likely_comparable")
        self.assertEqual(sample["reference_suspect_reasons"], [])

    def test_aggregate_metrics_filters_reference_suspects(self) -> None:
        rows = [
            {
                "sample_id": "clean",
                "reference_status": "likely_comparable",
                "metrics": {"note_precision": 0.6, "note_recall": 0.5, "note_f1": 0.55},
                "audibility": {"midi_coverage_ratio": 0.7, "first_note_delay_sec": 1.0},
            },
            {
                "sample_id": "dirty_reference",
                "reference_status": "reference_suspect",
                "metrics": {"note_precision": 0.0, "note_recall": 0.01, "note_f1": 0.02},
                "audibility": {"midi_coverage_ratio": 0.1, "first_note_delay_sec": 31.0},
            },
        ]

        aggregate = _aggregate_metrics_for_reference_status(rows, reference_status="likely_comparable")
        unfiltered = _aggregate_metrics_for_reference_status(rows, reference_status=None)

        self.assertEqual(aggregate["reference_status_filter"], "likely_comparable")
        self.assertEqual(aggregate["metric_sample_count"], 1)
        self.assertEqual(aggregate["excluded_metric_sample_count"], 1)
        self.assertEqual(aggregate["overall_f1"], 0.55)
        self.assertEqual(aggregate["metric_sample_ids"], ["clean"])
        self.assertEqual(unfiltered["metric_sample_count"], 2)
        self.assertAlmostEqual(unfiltered["overall_f1"], 0.285)

    def test_quality_gate_uses_dynamic_coverage_threshold(self) -> None:
        _, payload = _quality_gate_stage(
            metrics_payload={
                "produced_midi": "produced.mid",
                "metrics": {
                    "expected_note_count": 408,
                    "predicted_note_count": 169,
                    "note_recall": 0.0907,
                    "matched_note_count": 37,
                    "note_f1": 0.1282,
                    "note_precision": 0.2189,
                    "pitch_accuracy": 0.4594,
                    "octave_error_rate": 0.0,
                },
                "audibility": {"first_note_delay_sec": 1.39, "midi_coverage_ratio": 0.3540},
                "suspected_failure_modes": [],
            }
        )

        coverage_check = next(check for check in payload["checks"] if check["name"] == "midi_coverage_ratio")
        self.assertEqual(payload["status"], "success")
        self.assertTrue(coverage_check["passed"])
        self.assertAlmostEqual(coverage_check["threshold"], (169 / 408) * 0.85)
        self.assertEqual(payload["effective_thresholds"]["midi_coverage_ratio_min"], coverage_check["threshold"])


    def test_quality_gate_uses_octave_normalized_pitch_match_metrics(self) -> None:
        _, payload = _quality_gate_stage(
            metrics_payload={
                "produced_midi": "produced.mid",
                "metrics": {
                    "expected_note_count": 12,
                    "predicted_note_count": 12,
                    "note_recall": 0.0,
                    "note_f1": 0.0,
                    "matched_note_count": 0,
                    "pitch_accuracy": 0.0,
                    "octave_normalized_note_recall": 1.0,
                    "octave_normalized_note_f1": 1.0,
                    "octave_normalized_matched_note_count": 12,
                    "octave_normalized_pitch_accuracy": 1.0,
                },
                "audibility": {"first_note_delay_sec": 0.0, "midi_coverage_ratio": 1.0},
                "suspected_failure_modes": [],
            }
        )

        self.assertEqual(payload["status"], "success")
        recall_check = next(check for check in payload["checks"] if check["name"] == "note_recall")
        matched_check = next(check for check in payload["checks"] if check["name"] == "matched_notes")
        self.assertTrue(recall_check["passed"])
        self.assertEqual(recall_check["actual"], 1.0)
        self.assertEqual(recall_check["details"]["raw_value"], 0.0)
        self.assertTrue(matched_check["passed"])
        self.assertEqual(matched_check["actual"], 12)
        self.assertEqual(matched_check["details"]["raw_value"], 0)

    def test_quality_gate_keeps_timing_failures_despite_octave_normalized_pitch(self) -> None:
        _, payload = _quality_gate_stage(
            metrics_payload={
                "produced_midi": "produced.mid",
                "metrics": {
                    "expected_note_count": 12,
                    "predicted_note_count": 12,
                    "note_recall": 0.0,
                    "note_f1": 0.0,
                    "matched_note_count": 0,
                    "pitch_accuracy": 0.0,
                    "octave_normalized_note_recall": 1.0,
                    "octave_normalized_note_f1": 1.0,
                    "octave_normalized_matched_note_count": 12,
                    "octave_normalized_pitch_accuracy": 1.0,
                },
                "audibility": {"first_note_delay_sec": 30.0, "midi_coverage_ratio": 1.0},
                "suspected_failure_modes": [],
            }
        )

        self.assertEqual(payload["status"], "quality_failed")
        self.assertEqual([check["name"] for check in payload["failed_checks"]], ["first_note_delay_sec"])

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

            self.assertEqual(exit_code, 1)
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
        self.assertIn("audibility", payload)
        self.assertIn("alignment", payload)
        self.assertIn("dtw", payload["alignment"])
        self.assertIn("diagnostics", payload)
        self.assertIn("alignment", payload["diagnostics"])
        self.assertIn("dtw", payload["diagnostics"]["alignment"])
        self.assertIn("suspected_failure_modes", payload)
        self.assertEqual(payload["instrumental_hook_note_count"], 1)
        self.assertIsNotNone(payload["predicted_lead_track"])

    def test_manifest_loads_reference_pitch_shift(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _write_manifest_fixture(root, reference_pitch_shift=-12)
            from app.modules.benchmark.dataset import load_manifest

            sample = load_manifest(manifest).samples[0]

        self.assertEqual(sample.expected_reference_pitch_shift_semitones, -12)
        self.assertEqual(sample.to_dict()["expected_reference_pitch_shift_semitones"], -12)

    def test_metrics_stage_records_octave_normalization(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = root / "expected.mid"
            produced = root / "produced.mid"
            _write_sequence_midi(expected, note_count=12)
            _write_sequence_midi(produced, note_count=6)
            sample = BenchmarkSample(
                id="octave_song",
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
        self.assertEqual(payload["metrics"]["octave_shift_applied"], 0)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = root / "expected.mid"
            produced = root / "produced.mid"
            _write_sequence_midi(expected, note_count=12)
            _write_sequence_midi(produced, note_count=6, pitch_offset=-12)
            sample = BenchmarkSample(
                id="octave_song",
                input_mp4=root / "song.mp4",
                expected_midi=expected,
                expected_melody_track=1,
                expected_reference_pitch_shift_semitones=-12,
            )

            stage, payload = _compute_metrics_stage(
                sample=sample,
                produced_midi_path=produced,
                metric_config=MidiMetricConfig(onset_tolerance_sec=0.12),
            )

        self.assertEqual(stage.status, "success")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["expected_reference_pitch_shift_semitones"], -12)
        self.assertEqual(payload["expected_reference_extraction"]["details"]["pitch_shift_semitones"], -12)
        self.assertEqual(payload["metrics"]["octave_shift_applied"], 0)
        self.assertIsNone(payload["metrics"]["octave_shift_target"])
        self.assertEqual(payload["metrics"]["note_recall"], 0.5)
        self.assertEqual(payload["metrics"]["octave_normalized_note_recall"], 0.5)
        self.assertEqual(payload["metrics"]["octave_normalized_matched_note_count"], 6)
        self.assertEqual(payload["diagnostics"]["octave_shift_applied"], 0)
        self.assertEqual(payload["diagnostics"]["octave_normalized_note_recall"], 0.5)

    def test_quality_gate_uses_octave_normalized_matched_notes_for_diagnostics(self) -> None:
        _, payload = _quality_gate_stage(
            metrics_payload={
                "metrics": {
                    "note_recall": 0.01,
                    "octave_normalized_note_recall": 0.08,
                    "matched_note_count": 1,
                    "octave_normalized_matched_note_count": 12,
                },
                "audibility": {"first_note_delay_sec": 0.0, "midi_coverage_ratio": 0.5},
                "continuity": {},
            }
        )

        self.assertEqual(payload["status"], "success")
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertEqual(checks["note_recall"]["actual"], 0.08)
        self.assertEqual(checks["matched_notes"]["actual"], 12)
        self.assertEqual(checks["matched_notes"]["details"]["raw_value"], 1)
        self.assertEqual(checks["matched_notes"]["details"]["octave_normalized_value"], 12)

    def test_run_marks_quality_failed_as_diagnostic_and_keeps_workspace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _write_manifest_fixture(root, expected_writer=lambda path: _write_sequence_midi(path, note_count=12))
            produced = root / "low_quality.mid"
            _write_sequence_midi(produced, start_offset=30.0, note_count=12)
            output_root = root / "runs"
            _FakeAudioAnalysisService.produced_midi_source = produced
            _FakeAudioAnalysisService.should_raise = False

            with patch("app.scripts.mp4_midi_benchmark.AudioAnalysisService", _FakeAudioAnalysisService):
                exit_code = main(
                    [
                        "run",
                        "--manifest",
                        str(manifest),
                        "--output-root",
                        str(output_root),
                        "--run-id",
                        "quality_run",
                        "--skip-checksum",
                        "--ignore-readiness",
                    ]
                )

            run_root = output_root / "quality_run"
            summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
            summary_markdown = (run_root / "summary.md").read_text(encoding="utf-8")
            stage_status = json.loads((run_root / "song" / "stage_status.json").read_text(encoding="utf-8"))
            metrics_payload = json.loads((run_root / "song" / "metrics.json").read_text(encoding="utf-8"))
            quality_gate = json.loads((run_root / "song" / "quality_gate.json").read_text(encoding="utf-8"))
            quality_diagnostics = json.loads((run_root / "quality_diagnostics.json").read_text(encoding="utf-8"))
            reference_review = json.loads((run_root / "reference_review.json").read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["results"][0]["status"], "quality_failed")
            self.assertIn("alignment", summary["results"][0])
            self.assertIn("dtw", summary["results"][0]["alignment"])
            self.assertIn("pred_to_exp_shift_sec", summary["results"][0]["alignment"])
            self.assertIn("shift_corrected_recall", summary["results"][0]["alignment"])
            self.assertIn("shift_corrected_f1", summary["results"][0]["alignment"])
            self.assertIn("shift_corrected_matched", summary["results"][0]["alignment"])
            self.assertIn("shift_corrected_coverage", summary["results"][0]["alignment"])
            self.assertIn("alignment_diagnosis", summary["results"][0]["alignment"])
            self.assertIn("Raw F1", summary_markdown)
            self.assertIn("Gap50", summary_markdown)
            self.assertIn("Short Notes", summary_markdown)
            self.assertIn("Large Jumps", summary_markdown)
            self.assertIn("Shift Recall", summary_markdown)
            self.assertIn("Shift Diagnosis", summary_markdown)
            self.assertIn("reference_status", summary["results"][0])
            self.assertIn("reference_suspect_reasons", summary["results"][0])
            self.assertIn("reference_review", summary)
            self.assertEqual(summary["aggregate_metrics"]["reference_status_filter"], "likely_comparable")
            self.assertIn("aggregate_metrics_unfiltered", summary)
            self.assertEqual(quality_diagnostics["aggregate_metrics"]["reference_status_filter"], "likely_comparable")
            self.assertIn("aggregate_metrics_unfiltered", quality_diagnostics)
            self.assertTrue((run_root / "reference_review.md").exists())
            self.assertEqual(reference_review["samples"][0]["sample_id"], "song")
            self.assertEqual(quality_gate["status"], "quality_failed")
            self.assertTrue(quality_gate["export_policy"]["exports_available"])
            self.assertEqual(quality_gate["export_policy"]["export_scope"], "diagnostic_review")
            self.assertFalse(quality_gate["export_policy"]["quality_gate_blocks_exports"])
            self.assertTrue((run_root / "song" / "produced.mid").exists())
            self.assertIn("continuity", metrics_payload)
            self.assertIn("gap50_ratio", metrics_payload["continuity"])
            self.assertIn("gap50_ratio", metrics_payload["diagnostics"]["continuity"])
            self.assertIn("gap50_ratio", quality_gate["diagnostic_only"])
            self.assertNotIn("gap50_ratio", [check["name"] for check in quality_gate["failed_checks"]])
            self.assertNotIn("reference_status", quality_gate)
            self.assertNotIn("reference_suspect_reasons", quality_gate)
            self.assertFalse((run_root / "song" / "error.json").exists())
            self.assertTrue(Path(stage_status["workspace_path"]).exists())
            self.assertTrue((run_root / "song" / "logs" / "stdout.log").exists())
            self.assertTrue((run_root / "song" / "logs" / "stderr.log").exists())
            self.assertTrue((run_root / "song" / "logs" / "python_logging.log").exists())
            self.assertTrue((run_root / "quality_diagnostics.json").exists())

    def test_run_pipeline_failure_uses_exit_1(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _write_manifest_fixture(root, expected_writer=lambda path: _write_sequence_midi(path, note_count=12))
            output_root = root / "runs"
            _FakeAudioAnalysisService.should_raise = True

            with patch("app.scripts.mp4_midi_benchmark.AudioAnalysisService", _FakeAudioAnalysisService):
                exit_code = main(
                    [
                        "run",
                        "--manifest",
                        str(manifest),
                        "--output-root",
                        str(output_root),
                        "--run-id",
                        "failed_run",
                        "--skip-checksum",
                        "--ignore-readiness",
                    ]
                )

            run_root = output_root / "failed_run"
            summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(summary["results"][0]["status"], "failed")
            self.assertTrue((run_root / "song" / "error.json").exists())

    def test_run_pipeline_failure_still_takes_precedence_over_quality_failed_exit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples = root / "samples"
            (samples / "source_mp4").mkdir(parents=True)
            (samples / "source_mid").mkdir()
            (samples / "source_mp4" / "Good.mp4").write_bytes(b"not real mp4")
            (samples / "source_mp4" / "Bad.mp4").write_bytes(b"not real mp4")
            _write_sequence_midi(samples / "source_mid" / "Good.mid", note_count=12)
            _write_sequence_midi(samples / "source_mid" / "Bad.mid", note_count=12)
            manifest = samples / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "root": ".",
                        "samples": [
                            {"id": "quality", "input_mp4": "source_mp4/Good.mp4", "expected_midi": "source_mid/Good.mid", "expected_melody_track": 1},
                            {"id": "failed", "input_mp4": "source_mp4/Bad.mp4", "expected_midi": "source_mid/Bad.mid", "expected_melody_track": 1},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            produced = root / "low_quality.mid"
            _write_sequence_midi(produced, start_offset=30.0, note_count=12)
            output_root = root / "runs"

            async def fake_run_sample(**kwargs):
                from app.scripts.mp4_midi_benchmark import SampleRunResult

                sample = kwargs["sample"]
                run_dir = kwargs["run_root"] / sample.id
                run_dir.mkdir(parents=True, exist_ok=True)
                status = "failed" if sample.id == "failed" else "quality_failed"
                return SampleRunResult(sample_id=sample.id, status=status, run_dir=run_dir, produced_midi_path=None, metrics=None, stage_records=[])

            with patch("app.scripts.mp4_midi_benchmark._run_sample", fake_run_sample):
                exit_code = main(
                    [
                        "run",
                        "--manifest",
                        str(manifest),
                        "--output-root",
                        str(output_root),
                        "--run-id",
                        "mixed_run",
                        "--skip-checksum",
                        "--ignore-readiness",
                    ]
                )

            self.assertEqual(exit_code, 1)

    def test_run_success_uses_exit_0(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _write_manifest_fixture(root, expected_writer=lambda path: _write_sequence_midi(path, note_count=12))
            produced = root / "good.mid"
            _write_sequence_midi(produced, note_count=12)
            output_root = root / "runs"
            _FakeAudioAnalysisService.produced_midi_source = produced
            _FakeAudioAnalysisService.should_raise = False

            with patch("app.scripts.mp4_midi_benchmark.AudioAnalysisService", _FakeAudioAnalysisService):
                exit_code = main(
                    [
                        "run",
                        "--manifest",
                        str(manifest),
                        "--output-root",
                        str(output_root),
                        "--run-id",
                        "success_run",
                        "--skip-checksum",
                        "--ignore-readiness",
                    ]
                )

            summary = json.loads((output_root / "success_run" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["results"][0]["status"], "success")

    def test_summary_metrics_include_quality_gate_audibility_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "run"
            run_root.mkdir()
            manifest = _write_manifest_fixture(root)
            from app.modules.benchmark.dataset import load_manifest

            loaded_manifest = load_manifest(manifest)
            dataset_report = {
                "mp4_count": 1,
                "midi_count": 1,
                "paired_count": 1,
                "enabled_count": 1,
                "mp4_only": [],
                "midi_only": [],
            }
            result = SampleRunResult(
                sample_id="song",
                status="quality_failed",
                run_dir=run_root / "song",
                produced_midi_path=run_root / "song" / "produced.mid",
                metrics={
                    "metrics": {
                        "note_f1": 0.25,
                        "note_recall": 0.125,
                        "matched_note_count": 5,
                        "pitch_accuracy": 0.75,
                    },
                    "audibility": {
                        "midi_coverage_ratio": 0.36379859079787524,
                        "first_note_delay_sec": 31.54450561818182,
                    },
                    "continuity": {
                        "gap50_ratio": 0.8392857142857143,
                        "big_gap_count": 51,
                        "short_note_ratio": 0.21301775147928995,
                        "large_jump_ratio": 0.13095238095238096,
                        "median_pitch": 62.0,
                        "pitch_range": [50, 74],
                    },
                    "alignment": {},
                    "suspected_failure_modes": [],
                },
                stage_records=[],
                quality_gate={
                    "status": "quality_failed",
                    "failed_checks": [
                        {"name": "midi_coverage_ratio", "actual": 0.36379859079787524},
                        {"name": "first_note_delay_sec", "actual": 31.54450561818182},
                    ],
                },
            )

            _write_summary_files(
                run_root=run_root,
                manifest=loaded_manifest,
                results=[result],
                dataset_report=dataset_report,
            )

            summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
            markdown = (run_root / "summary.md").read_text(encoding="utf-8")
            metrics = summary["results"][0]["metrics"]

            self.assertEqual(metrics["midi_coverage_ratio"], 0.36379859079787524)
            self.assertEqual(metrics["first_note_delay_sec"], 31.54450561818182)
            self.assertEqual(metrics["gap50_ratio"], 0.8392857142857143)
            self.assertEqual(metrics["big_gap_count"], 51)
            self.assertEqual(metrics["short_note_ratio"], 0.21301775147928995)
            self.assertEqual(metrics["large_jump_ratio"], 0.13095238095238096)
            self.assertEqual(metrics["median_pitch"], 62.0)
            self.assertEqual(metrics["pitch_range"], [50, 74])
            self.assertIn("0.3638", markdown)
            self.assertIn("31.5445", markdown)
            self.assertIn("0.8393", markdown)
            self.assertIn("0.2130", markdown)
            self.assertIn("0.1310", markdown)


if __name__ == "__main__":
    unittest.main()


def _write_manifest_fixture(root: Path, *, expected_writer=_write_midi, reference_pitch_shift: int | None = None) -> Path:
    samples = root / "samples"
    (samples / "source_mp4").mkdir(parents=True)
    (samples / "source_mid").mkdir()
    (samples / "source_mp4" / "Song.mp4").write_bytes(b"not real mp4")
    expected_writer(samples / "source_mid" / "Song.mid")
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
                        **(
                            {"expected_reference_pitch_shift_semitones": reference_pitch_shift}
                            if reference_pitch_shift is not None
                            else {}
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest
