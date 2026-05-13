from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.debug_package import (
    build_derived_diagnostics,
    _derive_pitch_distribution_diagnostics,
    build_note_funnel_debug,
    _derive_quantized_note_diagnostics,
    _derive_rhythm_diagnostics,
    _derive_short_note_diagnostics,
    build_rhythm_debug,
    build_rhythm_debug_markdown,
    build_rhythm_grid_candidates,
    build_rhythm_grid_candidates_markdown,
    build_pitch_debug_markdown,
    export_benchmark_debug_package,
)
from app.modules.benchmark.midi_metrics import NoteEvent
from app.modules.benchmark.rhythm_candidate_summary import build_rhythm_candidate_summary
from app.scripts.benchmark_debug_package import main as debug_package_main


def _write_midi(path: Path, notes: list[tuple[float, float, int]], *, track_name: str = "Lead Vocal") -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(program=0, name=track_name)
    for start, end, pitch in notes:
        instrument.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end))
    midi.instruments.append(instrument)
    midi.write(str(path))


def _notes(pitches: list[int], *, start: float = 0.0, duration: float = 0.5) -> list[NoteEvent]:
    return [
        NoteEvent(start=start + index * duration, end=start + (index + 1) * duration, pitch=pitch)
        for index, pitch in enumerate(pitches)
    ]


def _write_f0(path: Path, pitches: list[float], *, hop: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "analysis_info": {"frame_hop_sec": hop},
                "frames": [
                    {"time_sec": index * hop, "pitch_midi": pitch, "confidence": 0.9, "voiced": True}
                    for index, pitch in enumerate(pitches)
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_candidates(path: Path, raw_pitches: list[int], *, selected_pitches: list[int] | None = None, duration: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "melody_candidates": {
            "notes": [
                {"start_time": index * duration, "duration_sec": duration, "midi_pitch": pitch}
                for index, pitch in enumerate(raw_pitches)
            ]
        }
    }
    if selected_pitches is not None:
        payload["melody_candidates"]["selected_notes"] = [
            {"start_time": index * duration, "duration_sec": duration, "midi_pitch": pitch}
            for index, pitch in enumerate(selected_pitches)
        ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_batch_debug_fixture(root: Path, *, sample_ids: list[str]) -> tuple[Path, Path]:
    samples_root = root / "samples"
    source_mp4 = samples_root / "source_mp4"
    source_mid = samples_root / "source_mid"
    source_mp4.mkdir(parents=True)
    source_mid.mkdir(parents=True)
    manifest_samples = []
    run_root = samples_root / "benchmark_runs" / "debug_run"
    results = []
    for sample_id in sample_ids:
        source_name = f"{sample_id}.mp4"
        midi_name = f"{sample_id}.mid"
        (source_mp4 / source_name).write_bytes(b"mock mp4")
        _write_midi(source_mid / midi_name, [(0.0, 0.5, 60), (0.5, 1.0, 62)], track_name="melody")
        manifest_samples.append(
            {
                "id": sample_id,
                "title": sample_id,
                "enabled": True,
                "input_mp4": f"source_mp4/{source_name}",
                "expected_midi": f"source_mid/{midi_name}",
                "expected_melody_track": 1,
                "expected_reference_strategy": "track",
            }
        )
        sample_dir = run_root / sample_id
        workspace = run_root / "projects" / f"bench_{sample_id}"
        (workspace / "pitch").mkdir(parents=True, exist_ok=True)
        (workspace / "separation").mkdir(parents=True, exist_ok=True)
        sample_dir.mkdir(parents=True, exist_ok=True)
        _write_midi(sample_dir / "produced.mid", [(0.0, 0.5, 60), (0.5, 1.0, 62)], track_name="Lead Vocal")
        (workspace / "separation" / "mdx_diagnostics.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
        (workspace / "pitch" / "rhythm_grid.json").write_text(
            json.dumps({"bpm": 120.0, "beats_per_bar": 4, "beat_times": [0.0, 0.5, 1.0, 1.5], "downbeat_times": [0.0]}),
            encoding="utf-8",
        )
        (sample_dir / "artifacts.json").write_text(json.dumps({"workspace_path": str(workspace)}), encoding="utf-8")
        (sample_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "sample_id": sample_id,
                    "expected_reference_strategy": "track",
                    "expected_melody_track": 1,
                    "produced_midi": str(sample_dir / "produced.mid"),
                    "predicted_lead_track": 1,
                    "metrics": {"expected_note_count": 2, "predicted_note_count": 2, "matched_note_count": 2, "note_recall": 1.0, "note_f1": 1.0},
                    "audibility": {"midi_coverage_ratio": 1.0, "first_note_delay_sec": 0.0, "expected_duration_sec": 1.0, "predicted_duration_sec": 1.0},
                    "alignment": {"dtw": {"dtw_pitch_match_recall_proxy": 1.0}, "smart_onset_alignment": {"shift_corrected_recall": 1.0, "shift_corrected_f1": 1.0, "shift_corrected_matched": 2}},
                }
            ),
            encoding="utf-8",
        )
        (sample_dir / "quality_gate.json").write_text(json.dumps({"status": "success", "failed_checks": []}), encoding="utf-8")
        results.append({"sample_id": sample_id, "status": "success", "quality_gate": {"failed_checks": []}})
    manifest = samples_root / "manifest.json"
    manifest.write_text(json.dumps({"version": 1, "root": ".", "samples": manifest_samples}), encoding="utf-8")
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "summary.json").write_text(json.dumps({"manifest": {"samples": manifest_samples}, "results": results}), encoding="utf-8")
    return run_root, manifest


class BenchmarkDebugPackageTests(unittest.TestCase):
    def test_export_debug_package_writes_notes_summary_missing_and_timeline(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples_root = root / "samples"
            source_mp4 = samples_root / "source_mp4"
            source_mid = samples_root / "source_mid"
            source_mp4.mkdir(parents=True)
            source_mid.mkdir(parents=True)
            (source_mp4 / "Song.mp4").write_bytes(b"mock mp4")
            _write_midi(
                source_mid / "Song.mid",
                [(0.0, 0.5, 60), (1.0, 1.5, 62), (2.0, 2.5, 64)],
                track_name="melody",
            )
            manifest = samples_root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "root": ".",
                        "samples": [
                            {
                                "id": "song",
                                "title": "Song",
                                "enabled": True,
                                "input_mp4": "source_mp4/Song.mp4",
                                "expected_midi": "source_mid/Song.mid",
                                "expected_melody_track": 1,
                                "expected_reference_strategy": "track",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            run_root = samples_root / "benchmark_runs" / "debug_run"
            sample_dir = run_root / "song"
            workspace = run_root / "projects" / "bench_song"
            (workspace / "separation").mkdir(parents=True)
            (workspace / "pitch").mkdir(parents=True)
            sample_dir.mkdir(parents=True)
            _write_midi(sample_dir / "produced.mid", [(0.03, 0.53, 60), (1.03, 1.53, 62)], track_name="Lead Vocal")
            (workspace / "separation" / "mdx_diagnostics.json").write_text(
                json.dumps({"status": "success"}),
                encoding="utf-8",
            )
            (workspace / "pitch" / "f0_track.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            {"time_sec": 0.0, "pitch_midi": 60.0, "confidence": 0.8, "voiced": True},
                            {"time_sec": 0.5, "pitch_midi": 62.0, "confidence": 0.7, "voiced": True},
                            {"time_sec": 1.0, "pitch_midi": 0.0, "confidence": 0.1, "voiced": False},
                            {"time_sec": 1.5, "frequency_hz": 329.63, "probability": 0.9, "voiced": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "pitch" / "pitch_contours.json").write_text(
                json.dumps(
                    {
                        "contours": [
                            {
                                "id": "pc_00001",
                                "duration_sec": 0.5,
                                "mean_confidence": 0.8,
                                "has_vibrato": True,
                                "has_glide": False,
                                "reason_codes": ["suspected_vibrato"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "pitch" / "vocal_activity.json").write_text(
                json.dumps(
                    {
                        "segments": [
                            {"start_time": 0.0, "end_time": 1.0, "state": "active"},
                            {"start_time": 1.0, "end_time": 2.0, "state": "inactive"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "pitch" / "note_candidates.json").write_text(
                json.dumps(
                    {
                        "melody_candidates": {
                            "notes": [
                                {"start_time": 0.0, "end_time": 0.2, "pitch": "C4"},
                                {"start_time": 0.3, "duration_sec": 0.4, "midi_pitch": 62},
                                {"start_time": 1.0, "end_time": 1.3, "pitch_midi": 64},
                                {"start_time": 1.5, "end_time": 1.7, "frequency_hz": 349.23},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "pitch" / "rhythm_grid.json").write_text(
                json.dumps({"bpm": 120.0, "beat_times": [0.0, 0.5, 1.0], "downbeat_times": [0.0]}),
                encoding="utf-8",
            )
            (workspace / "pitch" / "selected_melody.json").write_text(
                json.dumps(
                    {
                        "selected_notes": [{"candidate_id": "c1", "confidence": 0.9}],
                        "rejected_candidates": [{"candidate_id": "c2", "confidence": 0.2, "reason_codes": ["low_confidence"]}],
                        "summary": {
                            "input_candidate_count": 2,
                            "selected_count": 1,
                            "rejected_count": 1,
                            "rejection_reason_counts": {"low_confidence": 1},
                            "mean_selected_confidence": 0.9,
                            "mean_rejected_confidence": 0.2,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "pitch" / "quantized_notes.json").write_text(
                json.dumps(
                    {
                        "quantizer_backend": "local_snap",
                        "notes": [{"id": "qn_00001", "quantize_error_sec": 0.01, "uncertain": False}],
                        "summary": {
                            "note_count": 1,
                            "mean_quantize_error_sec": 0.01,
                            "max_quantize_error_sec": 0.01,
                            "uncertain_count": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (sample_dir / "artifacts.json").write_text(
                json.dumps({"workspace_path": str(workspace)}),
                encoding="utf-8",
            )
            (sample_dir / "metrics.json").write_text(
                json.dumps(
                    {
                        "sample_id": "song",
                        "expected_reference_strategy": "track",
                        "expected_melody_track": 1,
                        "produced_midi": str(sample_dir / "produced.mid"),
                        "predicted_lead_track": 1,
                        "metrics": {
                            "expected_note_count": 3,
                            "predicted_note_count": 2,
                            "matched_note_count": 2,
                            "note_recall": 2 / 3,
                            "note_f1": 0.8,
                            "pitch_accuracy": 1.0,
                        },
                        "audibility": {
                            "midi_coverage_ratio": 0.4,
                            "first_note_delay_sec": 0.03,
                            "expected_duration_sec": 2.5,
                            "predicted_duration_sec": 1.53,
                        },
                        "alignment": {
                            "best_octave_shift_semitones": 0,
                            "best_octave_shift_note_recall": 2 / 3,
                            "dtw": {"dtw_pitch_match_recall_proxy": 2 / 3},
                            "smart_onset_alignment": {
                                "pred_to_exp_shift_sec": 0.0,
                                "shift_corrected_recall": 2 / 3,
                                "shift_corrected_f1": 0.8,
                                "shift_corrected_matched": 2,
                                "shift_recall_gain": 0.0,
                                "shift_matched_gain": 0,
                                "alignment_diagnosis": "no_significant_offset",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (sample_dir / "quality_gate.json").write_text(
                json.dumps({"status": "success", "failed_checks": []}),
                encoding="utf-8",
            )
            (run_root / "summary.json").write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "sample_id": "song",
                                "status": "success",
                                "metrics": {
                                    "note_recall": 2 / 3,
                                    "note_f1": 0.8,
                                    "matched_note_count": 2,
                                    "midi_coverage_ratio": 0.4,
                                    "first_note_delay_sec": 0.03,
                                    "pitch_accuracy": 1.0,
                                },
                                "quality_gate": {"status": "success", "failed_checks": []},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = export_benchmark_debug_package(run_root=run_root, manifest_path=manifest, sample_id="song")
            debug_dir = Path(result.debug_dir)

            self.assertTrue((debug_dir / "debug_summary.md").exists())
            self.assertTrue((debug_dir / "expected_notes.json").exists())
            self.assertTrue((debug_dir / "predicted_notes.json").exists())
            self.assertTrue((debug_dir / "match_debug.json").exists())
            self.assertTrue((debug_dir / "alignment_debug.json").exists())
            self.assertTrue((debug_dir / "derived_diagnostics.json").exists())
            self.assertTrue((debug_dir / "rhythm_debug.json").exists())
            self.assertTrue((debug_dir / "rhythm_debug.md").exists())
            self.assertTrue((debug_dir / "rhythm_grid_candidates.json").exists())
            self.assertTrue((debug_dir / "rhythm_grid_candidates.md").exists())
            self.assertTrue((debug_dir / "timeline_debug.png").exists())
            self.assertTrue((debug_dir / "mdx_diagnostics.json").exists())

            expected_payload = json.loads((debug_dir / "expected_notes.json").read_text(encoding="utf-8"))
            predicted_payload = json.loads((debug_dir / "predicted_notes.json").read_text(encoding="utf-8"))
            self.assertEqual(expected_payload["reference_strategy"], "track")
            self.assertEqual(expected_payload["note_count"], 3)
            self.assertEqual(predicted_payload["note_count"], 2)

            derived = json.loads((debug_dir / "derived_diagnostics.json").read_text(encoding="utf-8"))
            self.assertEqual(derived["notes"]["expected_note_count"], 3)
            self.assertEqual(derived["notes"]["predicted_note_count"], 2)
            self.assertAlmostEqual(derived["notes"]["pred_exp_note_count_ratio"], 2 / 3)
            self.assertEqual(derived["notes"]["expected_pitch_range"], [60, 64])
            self.assertEqual(derived["notes"]["predicted_pitch_range"], [60, 62])
            self.assertAlmostEqual(derived["notes"]["pitch_range_overlap_ratio"], 0.5)
            self.assertIn("continuity", derived)
            self.assertEqual(derived["continuity"]["note_count"], 2)
            self.assertEqual(derived["continuity"]["gap50_count"], 1)
            self.assertAlmostEqual(derived["continuity"]["gap50_ratio"], 1.0)
            self.assertEqual(derived["notes"]["predicted_gap50_count"], 1)
            self.assertAlmostEqual(derived["notes"]["predicted_gap50_ratio"], 1.0)
            self.assertEqual(derived["match"]["raw_matched_count"], 2)
            self.assertAlmostEqual(derived["match"]["raw_match_rate_vs_expected"], 2 / 3)
            self.assertEqual(derived["f0"]["f0_frame_count"], 4)
            self.assertEqual(derived["f0"]["f0_voiced_frame_count"], 3)
            self.assertAlmostEqual(derived["f0"]["f0_voiced_ratio"], 0.75)
            self.assertEqual(derived["vocal_activity"]["vocal_activity_segment_count"], 2)
            self.assertAlmostEqual(derived["vocal_activity"]["vocal_activity_active_ratio"], 0.5)
            self.assertEqual(derived["note_candidates"]["note_candidate_count"], 4)
            self.assertAlmostEqual(derived["note_candidates"]["candidate_to_predicted_ratio"], 2.0)
            self.assertTrue(derived["rhythm"]["available"])
            self.assertEqual(derived["rhythm"]["tempo_bpm"], 120.0)
            self.assertEqual(derived["rhythm"]["beat_count"], 3)
            self.assertIn("preliminary_rhythm_diagnosis", derived["rhythm"])
            self.assertIn("candidates", derived["rhythm"])
            self.assertIn("best_diagnostic_candidate_id", derived["rhythm"])
            self.assertIn("current_candidate_rank", derived["rhythm"])
            rhythm_grid_payload = json.loads((debug_dir / "rhythm_grid.json").read_text(encoding="utf-8"))
            self.assertEqual(rhythm_grid_payload["diagnostics"]["diagnostic_only"], True)
            rhythm_debug_markdown = (debug_dir / "rhythm_debug.md").read_text(encoding="utf-8")
            self.assertIn("RhythmGrid Debug", rhythm_debug_markdown)
            self.assertIn("quantizer behavior unchanged", rhythm_debug_markdown)
            rhythm_candidates_markdown = (debug_dir / "rhythm_grid_candidates.md").read_text(encoding="utf-8")
            self.assertIn("RhythmGrid Candidate Diagnostics", rhythm_candidates_markdown)
            self.assertIn("diagnostic_only: true", rhythm_candidates_markdown)

            summary = (debug_dir / "debug_summary.md").read_text(encoding="utf-8")
            self.assertIn("sample_id: song", summary)
            self.assertIn("f0_track.json", summary)
            self.assertIn("vocal_activity.json", summary)
            self.assertIn("rhythm_grid.json", summary)
            self.assertIn("Pitch Contour Diagnostics", summary)
            self.assertIn("Selected Melody Diagnostics", summary)
            self.assertIn("Quantization Diagnostics", summary)
            self.assertIn("Rhythm Diagnostics", summary)
            self.assertIn("Continuity Diagnostics", summary)
            self.assertIn("gap50_ratio", summary)
            self.assertIn("large_jump_ratio", summary)
            self.assertIn("best_diagnostic_candidate_id", summary)
            self.assertIn("Short Note Diagnostics", summary)
            self.assertIn("## Derived Diagnostics", summary)
            self.assertIn("preliminary_failure_stage_v2", summary)
            self.assertNotIn("f0_track.json", result.missing_files)
            self.assertNotIn("rhythm_grid.json", result.missing_files)
            self.assertNotIn("pitch_contours.json", result.missing_files)
            self.assertNotIn("selected_melody.json", result.missing_files)
            self.assertNotIn("quantized_notes.json", result.missing_files)
            self.assertIn("timeline_debug.png", result.found_files)

    def test_export_debug_package_marks_optional_diagnostics_unavailable_when_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples_root = root / "samples"
            (samples_root / "source_mp4").mkdir(parents=True)
            (samples_root / "source_mid").mkdir(parents=True)
            (samples_root / "source_mp4" / "Song.mp4").write_bytes(b"mock mp4")
            _write_midi(samples_root / "source_mid" / "Song.mid", [(0.0, 0.5, 60)], track_name="melody")
            manifest = samples_root / "manifest.json"
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
                                "expected_reference_strategy": "track",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            run_root = samples_root / "benchmark_runs" / "debug_run"
            sample_dir = run_root / "song"
            sample_dir.mkdir(parents=True)
            _write_midi(sample_dir / "produced.mid", [(0.02, 0.52, 60)], track_name="Lead Vocal")

            result = export_benchmark_debug_package(run_root=run_root, manifest_path=manifest, sample_id="song")
            debug_dir = Path(result.debug_dir)
            derived = json.loads((debug_dir / "derived_diagnostics.json").read_text(encoding="utf-8"))

            self.assertFalse(derived["f0"]["available"])
            self.assertFalse(derived["vocal_activity"]["available"])
            self.assertFalse(derived["note_candidates"]["available"])
            self.assertIn("f0_track.json", result.missing_files)
            self.assertIn("vocal_activity.json", result.missing_files)
            self.assertIn("note_candidates.json", result.missing_files)
            self.assertIn("rhythm_grid.json", result.missing_files)
            self.assertIn("pitch_contours.json", result.missing_files)
            self.assertIn("selected_melody.json", result.missing_files)
            self.assertIn("quantized_notes.json", result.missing_files)
            self.assertTrue((debug_dir / "timeline_debug.png").exists())

    def test_pitch_distribution_histograms_cover_all_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            candidates_path = root / "note_candidates.json"
            _write_f0(f0_path, [60, 62, 64])
            _write_candidates(candidates_path, [60, 62, 64], selected_pitches=[62, 64])

            diagnostics = _derive_pitch_distribution_diagnostics(
                expected_notes=_notes([60, 62, 64]),
                predicted_notes=_notes([60, 62]),
                f0_track_path=f0_path,
                note_candidates_path=candidates_path,
            )

            for source in [
                "expected_notes",
                "predicted_notes",
                "f0_frames",
                "note_candidates_all",
                "note_candidates_selected",
                "note_candidates_melody_raw",
            ]:
                self.assertTrue(diagnostics[source]["available"], source)
                self.assertTrue(diagnostics[source]["histogram"]["count_by_midi"])
            self.assertIn("expected_vs_f0", diagnostics["pairwise"])

    def test_pitch_distribution_uses_duration_weighted_median(self) -> None:
        diagnostics = _derive_pitch_distribution_diagnostics(
            expected_notes=[
                NoteEvent(start=0.0, end=4.0, pitch=60),
                NoteEvent(start=4.0, end=4.1, pitch=72),
                NoteEvent(start=4.1, end=4.2, pitch=74),
                NoteEvent(start=4.2, end=4.3, pitch=76),
            ],
            predicted_notes=[],
            f0_track_path=None,
            note_candidates_path=None,
        )

        self.assertEqual(diagnostics["expected_notes"]["weight_type"], "duration_sec")
        self.assertEqual(diagnostics["expected_notes"]["median_pitch"], 60.0)

    def test_octave_or_reference_pitch_mismatch_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            f0_path = Path(temp_dir) / "f0_track.json"
            candidates_path = Path(temp_dir) / "note_candidates.json"
            _write_f0(f0_path, [48, 50, 52, 53, 55, 57])
            _write_candidates(candidates_path, [48, 50, 52, 53, 55, 57])

            diagnostics = _derive_pitch_distribution_diagnostics(
                expected_notes=_notes([60, 62, 64, 65, 67, 69]),
                predicted_notes=_notes([48, 50, 52, 53, 55, 57]),
                f0_track_path=f0_path,
                note_candidates_path=candidates_path,
            )

            flag = diagnostics["flags"]["possible_f0_octave_or_reference_pitch_mismatch"]
            self.assertTrue(flag["triggered"])
            self.assertEqual(flag["subtype"], "ambiguous_octave_or_reference")
            self.assertEqual(diagnostics["pairwise"]["expected_vs_f0"]["best_octave_shift"], 12)

    def test_f0_to_note_candidate_loss_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            candidates_path = root / "note_candidates.json"
            _write_f0(f0_path, [60, 62, 64, 65, 67, 69])
            _write_candidates(candidates_path, [])

            diagnostics = _derive_pitch_distribution_diagnostics(
                expected_notes=_notes([60, 62, 64, 65, 67, 69]),
                predicted_notes=[],
                f0_track_path=f0_path,
                note_candidates_path=candidates_path,
            )

            flag = diagnostics["flags"]["possible_f0_to_note_candidate_loss"]
            self.assertTrue(flag["triggered"])
            self.assertEqual(flag["subtype"], "candidate_extraction_loss")

    def test_melody_selector_or_filter_loss_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            candidates_path = root / "note_candidates.json"
            pitches = [60, 62, 64, 65, 67, 69]
            _write_f0(f0_path, pitches)
            _write_candidates(candidates_path, pitches, selected_pitches=[60])

            diagnostics = _derive_pitch_distribution_diagnostics(
                expected_notes=_notes(pitches),
                predicted_notes=_notes([60]),
                f0_track_path=f0_path,
                note_candidates_path=candidates_path,
            )

            flag = diagnostics["flags"]["possible_melody_selector_or_filter_loss"]
            self.assertTrue(flag["triggered"])
            self.assertEqual(flag["subtype"], "melody_selector_loss")

    def test_reference_strategy_or_pitch_source_mismatch_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            candidates_path = root / "note_candidates.json"
            _write_f0(f0_path, [60, 62, 64, 65, 67, 69])
            _write_candidates(candidates_path, [60, 62, 64, 65, 67, 69])

            diagnostics = _derive_pitch_distribution_diagnostics(
                expected_notes=_notes([96, 98, 100, 101, 103, 105]),
                predicted_notes=_notes([60, 62, 64, 65, 67, 69]),
                f0_track_path=f0_path,
                note_candidates_path=candidates_path,
            )

            flag = diagnostics["flags"]["possible_reference_strategy_or_pitch_source_mismatch"]
            self.assertTrue(flag["triggered"])

    def test_pitch_debug_markdown_written(self) -> None:
        diagnostics = _derive_pitch_distribution_diagnostics(
            expected_notes=_notes([60, 62, 64, 65, 67, 69]),
            predicted_notes=_notes([48, 50, 52, 53, 55, 57]),
            f0_track_path=None,
            note_candidates_path=None,
        )

        markdown = build_pitch_debug_markdown(
            sample_id="song",
            sample_title="Song",
            pitch_distribution=diagnostics,
        )

        self.assertIn("# Pitch Distribution Debug: Song", markdown)
        self.assertIn("## Source Summary", markdown)
        self.assertIn("## Pairwise Pitch Overlap", markdown)
        self.assertIn("## Candidate Funnel", markdown)
        self.assertIn("## Triggered Flags", markdown)

    def test_missing_pitch_inputs_do_not_crash(self) -> None:
        diagnostics = _derive_pitch_distribution_diagnostics(
            expected_notes=_notes([60, 62, 64]),
            predicted_notes=_notes([60]),
            f0_track_path=None,
            note_candidates_path=None,
        )

        self.assertTrue(diagnostics["available"])
        self.assertFalse(diagnostics["f0_frames"]["available"])
        self.assertFalse(diagnostics["note_candidates_all"]["available"])
        self.assertIn("f0_track.json missing", diagnostics["warnings"])

    def test_quantized_note_diagnostics_include_dp_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quantized_notes.json"
            path.write_text(
                json.dumps(
                    {
                        "quantizer_backend": "dp_v1",
                        "requested_quantizer_backend": "dp_v1",
                        "fallback_used": False,
                        "fallback_reason": None,
                        "summary": {
                            "note_count": 2,
                            "mean_quantize_error_sec": 0.01,
                            "p95_quantize_error_sec": 0.02,
                            "max_quantize_error_sec": 0.03,
                            "uncertain_count": 1,
                            "fragmentation": {"possible_fragment_pair_count": 1, "risk_score": 1.0},
                            "overmerge": {"possible_overmerge_note_count": 1, "overlap_pair_count": 0, "risk_score": 0.5},
                        },
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = _derive_quantized_note_diagnostics(path)

            self.assertEqual(diagnostics["quantizer_backend"], "dp_v1")
            self.assertFalse(diagnostics["fallback_used"])
            self.assertEqual(diagnostics["p95_quantize_error_sec"], 0.02)
            self.assertEqual(diagnostics["fragmentation"]["possible_fragment_pair_count"], 1)
            self.assertEqual(diagnostics["overmerge"]["possible_overmerge_note_count"], 1)

    def test_rhythm_debug_reports_grid_diagnostics(self) -> None:
        with TemporaryDirectory() as temp_dir:
            rhythm_grid_path = Path(temp_dir) / "rhythm_grid.json"
            rhythm_grid_path.write_text(
                json.dumps(
                    {
                        "bpm": 120.0,
                        "bpm_confidence": 0.8,
                        "beats_per_bar": 4,
                        "beat_times": [0.0, 0.5, 1.0, 1.8, 2.3],
                        "downbeat_times": [0.0, 1.8],
                        "analysis_info": {"downbeat_confidence": 0.3},
                    }
                ),
                encoding="utf-8",
            )

            rhythm_debug = build_rhythm_debug(
                rhythm_grid_path=rhythm_grid_path,
                predicted_notes=[
                    NoteEvent(start=0.0, end=0.2, pitch=60),
                    NoteEvent(start=0.74, end=0.95, pitch=62),
                    NoteEvent(start=1.45, end=1.6, pitch=64),
                ],
            )
            markdown = build_rhythm_debug_markdown(sample_id="song", sample_title="Song", rhythm_debug=rhythm_debug)

            self.assertTrue(rhythm_debug["available"])
            self.assertEqual(rhythm_debug["tempo_bpm"], 120.0)
            self.assertEqual(rhythm_debug["beat_count"], 5)
            self.assertEqual(rhythm_debug["downbeat_count"], 2)
            self.assertIn(rhythm_debug["preliminary_rhythm_diagnosis"], {
                "possible_downbeat_uncertainty",
                "possible_bar_phase_error",
                "possible_off_grid_quantization",
                "mixed_rhythm_issue",
            })
            self.assertIn("RhythmGrid Debug", markdown)
            self.assertIn("preliminary_rhythm_diagnosis", markdown)

    def test_missing_rhythm_grid_is_unavailable_without_crashing(self) -> None:
        rhythm_debug = build_rhythm_debug(rhythm_grid_path=None, predicted_notes=[])

        self.assertFalse(rhythm_debug["available"])
        self.assertEqual(rhythm_debug["unavailable_reason"], "rhythm_grid.json missing")
        rhythm_candidates = build_rhythm_grid_candidates(rhythm_grid_path=None, predicted_notes=[])
        self.assertFalse(rhythm_candidates["available"])
        self.assertEqual(rhythm_candidates["unavailable_reason"], "rhythm_grid.json missing")

        with TemporaryDirectory() as temp_dir:
            diagnostics = _derive_rhythm_diagnostics(Path(temp_dir) / "missing.json")

        self.assertFalse(diagnostics["available"])

    def test_rhythm_grid_candidates_include_tempo_and_phase_variants(self) -> None:
        with TemporaryDirectory() as temp_dir:
            rhythm_grid_path = Path(temp_dir) / "rhythm_grid.json"
            rhythm_grid_path.write_text(
                json.dumps(
                    {
                        "bpm": 120.0,
                        "beats_per_bar": 4,
                        "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
                        "downbeat_times": [0.5, 2.5],
                        "analysis_info": {"downbeat_confidence": 0.6, "ioi_bpm": 118.0, "raw_bpm": 121.0},
                    }
                ),
                encoding="utf-8",
            )

            candidates = build_rhythm_grid_candidates(
                rhythm_grid_path=rhythm_grid_path,
                predicted_notes=[
                    NoteEvent(start=0.0, end=0.2, pitch=60),
                    NoteEvent(start=0.5, end=0.7, pitch=62),
                    NoteEvent(start=1.0, end=1.2, pitch=64),
                ],
            )
            markdown = build_rhythm_grid_candidates_markdown(
                sample_id="song",
                sample_title="Song",
                rhythm_candidates=candidates,
            )
            by_id = {candidate["candidate_id"]: candidate for candidate in candidates["candidates"]}

            self.assertTrue(candidates["available"])
            self.assertTrue(candidates["diagnostic_only"])
            self.assertIn("current_grid", by_id)
            self.assertIn("half_tempo_grid", by_id)
            self.assertIn("double_tempo_grid", by_id)
            for phase in range(4):
                self.assertIn(f"downbeat_phase_shift_{phase}", by_id)
            self.assertEqual(by_id["half_tempo_grid"]["beat_count"], 4)
            self.assertEqual(by_id["double_tempo_grid"]["beat_count"], 15)
            self.assertEqual(by_id["downbeat_phase_shift_1"]["downbeat_count"], 2)
            self.assertIn("candidate_score", by_id["current_grid"])
            self.assertIn("score_breakdown", by_id["current_grid"])
            self.assertIn("best_diagnostic_candidate_id", candidates)
            self.assertIn("current_candidate_rank", candidates)
            self.assertIn("candidate comparison", markdown.lower())
            self.assertIn("possible half/double tempo suspicion", markdown)

    def test_debug_package_cli_single_sample_still_works(self) -> None:
        with TemporaryDirectory() as temp_dir:
            run_root, manifest = _write_batch_debug_fixture(Path(temp_dir), sample_ids=["song_a"])

            exit_code = debug_package_main([
                "--run-root",
                str(run_root),
                "--manifest",
                str(manifest),
                "--sample-id",
                "song_a",
            ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((run_root / "song_a" / "debug_package" / "rhythm_grid_candidates.json").exists())
            self.assertTrue((run_root / "song_a" / "debug_package" / "note_funnel_debug.json").exists())

    def test_debug_package_cli_all_enabled_writes_batch_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            run_root, manifest = _write_batch_debug_fixture(Path(temp_dir), sample_ids=["song_a", "song_b"])

            exit_code = debug_package_main([
                "--run-root",
                str(run_root),
                "--manifest",
                str(manifest),
                "--all-enabled",
            ])

            self.assertEqual(exit_code, 0)
            summary_path = run_root / "debug_package_batch_summary.json"
            markdown_path = run_root / "debug_package_batch_summary.md"
            self.assertTrue(summary_path.exists())
            self.assertTrue(markdown_path.exists())
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["total_requested"], 2)
            self.assertEqual(payload["generated_count"], 2)
            self.assertEqual(payload["failed_count"], 0)
            gap_summary_path = run_root / "gap_attribution_summary.json"
            gap_markdown_path = run_root / "gap_attribution_summary.md"
            self.assertTrue(gap_summary_path.exists())
            self.assertTrue(gap_markdown_path.exists())
            gap_payload = json.loads(gap_summary_path.read_text(encoding="utf-8"))
            self.assertTrue(gap_payload["diagnostic_only"])
            self.assertEqual(gap_payload["sample_count"], 2)
            by_id = {row["sample_id"]: row for row in payload["per_sample"]}
            for sample_id in ["song_a", "song_b"]:
                self.assertTrue((run_root / sample_id / "debug_package" / "rhythm_grid_candidates.json").exists())
                self.assertTrue((run_root / sample_id / "debug_package" / "note_funnel_debug.json").exists())
                self.assertTrue((run_root / sample_id / "debug_package" / "note_funnel_debug.md").exists())
                self.assertTrue((run_root / sample_id / "debug_package" / "gap_attribution.json").exists())
                self.assertTrue((run_root / sample_id / "debug_package" / "gap_attribution.md").exists())
                self.assertIn("note_funnel_debug.json", by_id[sample_id]["generated_files"])
                self.assertIn("gap_attribution.json", by_id[sample_id]["generated_files"])
                self.assertIn("gap_attribution.md", by_id[sample_id]["generated_files"])

            rhythm_summary = build_rhythm_candidate_summary(run_root)
            self.assertEqual(len(rhythm_summary["samples"]), 2)
            self.assertNotEqual(rhythm_summary["aggregate_counts"]["Candidate Diagnostics Missing"], 2)

    def test_debug_package_cli_batch_continues_after_sample_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            run_root, manifest = _write_batch_debug_fixture(Path(temp_dir), sample_ids=["song_a", "song_b"])
            (run_root / "song_b" / "produced.mid").unlink()

            exit_code = debug_package_main([
                "--run-root",
                str(run_root),
                "--manifest",
                str(manifest),
                "--all-enabled",
            ])

            self.assertEqual(exit_code, 0)
            payload = json.loads((run_root / "debug_package_batch_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["total_requested"], 2)
            self.assertEqual(payload["generated_count"], 2)
            self.assertEqual(payload["failed_count"], 0)
            self.assertTrue((run_root / "gap_attribution_summary.json").exists())
            by_id = {row["sample_id"]: row for row in payload["per_sample"]}
            self.assertIn("rhythm_grid_candidates.json", by_id["song_a"]["generated_files"])
            self.assertIn("predicted_notes.json", by_id["song_b"]["missing_files"])


    def test_note_funnel_debug_reports_retention_and_missing_quantized(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            candidates_path = root / "note_candidates.json"
            selected_path = root / "selected_melody.json"
            score_ir_path = root / "score_ir.json"
            _write_f0(f0_path, [60, 61, 62], hop=0.1)
            candidates_path.write_text(
                json.dumps(
                    {
                        "melody_candidates": {
                            "notes": [
                                {"start_time": index * 0.2, "duration_sec": 0.18, "midi_pitch": 60 + index}
                                for index in range(4)
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            selected_path.write_text(
                json.dumps(
                    {
                        "selected_notes": [
                            {"start_time_sec": index * 0.2, "end_time_sec": index * 0.2 + 0.18, "pitch_center_midi": 60 + index}
                            for index in range(2)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            score_ir_path.write_text(
                json.dumps(
                    {
                        "notes": [
                            {"start_time": 0.0, "duration_sec": 0.36, "pitch_midi": 60},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = build_note_funnel_debug(
                expected_notes=[NoteEvent(start=0.0, end=0.18, pitch=60) for _ in range(4)],
                predicted_notes=[NoteEvent(start=0.0, end=0.36, pitch=60)],
                f0_track_path=f0_path,
                note_candidates_path=candidates_path,
                selected_melody_path=selected_path,
                quantized_notes_path=root / "missing_quantized_notes.json",
                score_ir_path=score_ir_path,
            )

            self.assertEqual(diagnostics["f0_voiced_frame_count"], 3)
            self.assertEqual(diagnostics["note_candidate_count"], 4)
            self.assertEqual(diagnostics["selected_note_count"], 2)
            self.assertEqual(diagnostics["quantized_note_count"], "unavailable")
            self.assertEqual(diagnostics["score_ir_note_count"], 1)
            self.assertEqual(diagnostics["predicted_midi_note_count"], 1)
            self.assertEqual(diagnostics["retention"]["candidate_to_selected_count_ratio"], 0.5)
            self.assertIn("quantized_notes", diagnostics["missing_layers"])

    def test_note_funnel_short_note_loss_and_overmerge_flags(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidates_path = root / "note_candidates.json"
            selected_path = root / "selected_melody.json"
            quantized_path = root / "quantized_notes.json"
            score_ir_path = root / "score_ir.json"
            candidates = [
                {"start_time": index * 0.12, "duration_sec": 0.10, "midi_pitch": 60 + (index % 3)}
                for index in range(20)
            ]
            predicted = [NoteEvent(start=index * 0.5, end=index * 0.5 + 0.5, pitch=60 + (index % 3)) for index in range(8)]
            candidates_path.write_text(json.dumps({"melody_candidates": {"notes": candidates}}), encoding="utf-8")
            selected_path.write_text(json.dumps({"selected_notes": candidates}), encoding="utf-8")
            quantized_path.write_text(json.dumps({"notes": candidates[:8]}), encoding="utf-8")
            score_ir_path.write_text(
                json.dumps({"notes": [{"start_time": note.start, "duration_sec": note.duration, "pitch_midi": note.pitch} for note in predicted]}),
                encoding="utf-8",
            )

            diagnostics = build_note_funnel_debug(
                expected_notes=[NoteEvent(start=index * 0.12, end=index * 0.12 + 0.10, pitch=60 + (index % 3)) for index in range(20)],
                predicted_notes=predicted,
                f0_track_path=None,
                note_candidates_path=candidates_path,
                selected_melody_path=selected_path,
                quantized_notes_path=quantized_path,
                score_ir_path=score_ir_path,
            )
            flags = diagnostics["loss_attribution"]["flags"]

            self.assertTrue(flags["possible_short_note_loss"]["triggered"])
            self.assertTrue(flags["possible_overmerge"]["triggered"])
            self.assertIn("possible_quantization_overmerge", diagnostics["loss_attribution"]["triggered_flags"])

    def test_note_funnel_export_loss_and_fragmentation_flags(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidates_path = root / "note_candidates.json"
            selected_path = root / "selected_melody.json"
            quantized_path = root / "quantized_notes.json"
            score_ir_path = root / "score_ir.json"
            notes = [
                {"start_time": index * 0.25, "duration_sec": 0.20, "midi_pitch": 60 + (index % 5)}
                for index in range(20)
            ]
            for path, payload in [
                (candidates_path, {"melody_candidates": {"notes": notes}}),
                (selected_path, {"selected_notes": notes}),
                (quantized_path, {"notes": notes}),
                (score_ir_path, {"notes": notes}),
            ]:
                path.write_text(json.dumps(payload), encoding="utf-8")

            export_loss = build_note_funnel_debug(
                expected_notes=[NoteEvent(start=index * 0.25, end=index * 0.25 + 0.20, pitch=60) for index in range(20)],
                predicted_notes=[NoteEvent(start=0.0, end=0.2, pitch=60)],
                f0_track_path=None,
                note_candidates_path=candidates_path,
                selected_melody_path=selected_path,
                quantized_notes_path=quantized_path,
                score_ir_path=score_ir_path,
            )
            self.assertTrue(export_loss["loss_attribution"]["flags"]["possible_export_loss"]["triggered"])

            fragmentation = build_note_funnel_debug(
                expected_notes=[NoteEvent(start=index * 0.5, end=index * 0.5 + 0.5, pitch=60) for index in range(10)],
                predicted_notes=[NoteEvent(start=index * 0.1, end=index * 0.1 + 0.08, pitch=60) for index in range(20)],
                f0_track_path=None,
                note_candidates_path=candidates_path,
                selected_melody_path=selected_path,
                quantized_notes_path=quantized_path,
                score_ir_path=score_ir_path,
            )
            self.assertTrue(fragmentation["loss_attribution"]["flags"]["possible_fragmentation"]["triggered"])

    def test_short_note_loss_attribution_reports_quantizer_stage(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidates_path = root / "note_candidates.json"
            selected_path = root / "selected_melody.json"
            quantized_path = root / "quantized_notes.json"
            candidates_path.write_text(
                json.dumps({"melody_candidates": {"notes": [{"start_time": 0.0, "duration_sec": 0.12, "midi_pitch": 60}]}}),
                encoding="utf-8",
            )
            selected_path.write_text(
                json.dumps({"selected_notes": [{"start_time_sec": 0.0, "end_time_sec": 0.12, "pitch_center_midi": 60}]}),
                encoding="utf-8",
            )
            quantized_path.write_text(
                json.dumps({"notes": []}),
                encoding="utf-8",
            )

            diagnostics = _derive_short_note_diagnostics(
                [NoteEvent(start=0.0, end=0.12, pitch=60)],
                [],
                note_candidates_path=candidates_path,
                selected_melody_path=selected_path,
                quantized_notes_path=quantized_path,
            )

            self.assertEqual(diagnostics["loss_attribution"]["likely_loss_stage"], "quantizer")
            self.assertEqual(diagnostics["loss_attribution"]["stage_counts"]["quantizer"], 1)

    def test_derived_diagnostics_marks_reference_alignment_as_diagnostic_only(self) -> None:
        diagnostics = build_derived_diagnostics(
            expected_notes=[NoteEvent(start=float(index), end=float(index) + 0.5, pitch=72) for index in range(20)],
            predicted_notes=[NoteEvent(start=14.0 + float(index), end=14.5 + float(index), pitch=60) for index in range(8)],
            f0_track_path=None,
            vocal_activity_path=None,
            note_candidates_path=None,
            match_debug={"matched_count": 0},
            alignment_debug={"best_time_shift_sec": -14.0},
            metrics_payload={
                "metrics": {
                    "note_recall": 0.0,
                    "octave_normalized_note_recall": 0.08,
                    "octave_normalized_recall_lift": 0.08,
                    "median_pitch_delta_raw": -12.0,
                },
                "audibility": {
                    "expected_first_note_time_sec": 0.0,
                    "predicted_first_note_time_sec": 14.0,
                    "first_note_delay_sec": 14.0,
                },
                "alignment": {
                    "best_time_shift_sec": -14.0,
                    "best_time_shift_note_recall": 0.12,
                    "best_octave_shift_semitones": 12,
                    "best_octave_shift_note_recall": 0.10,
                    "smart_onset_alignment": {"pred_to_exp_shift_sec": -14.0, "shift_corrected_recall": 0.12},
                    "dtw": {"dtw_pitch_match_recall_proxy": 0.20},
                },
            },
        )

        reference_alignment = diagnostics["reference_alignment"]
        self.assertTrue(reference_alignment["diagnostic_only"])
        self.assertTrue(reference_alignment["reference_suspect"])
        self.assertIn("reference_first_note_offset_suspect", reference_alignment["reason_codes"])
        self.assertIn("possible_global_time_offset", reference_alignment["reason_codes"])
        self.assertIn("possible_octave_or_reference_pitch_mismatch", reference_alignment["reason_codes"])
        self.assertEqual(reference_alignment["first_note_delay_sec"], 14.0)
        self.assertEqual(reference_alignment["possible_global_time_offset_sec"], -14.0)

    def test_selected_melody_postprocess_diagnostics_are_reported(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected_path = root / "selected_melody.json"
            selected_path.write_text(
                json.dumps(
                    {
                        "selected_notes": [
                            {
                                "candidate_id": "a+b",
                                "start_time_sec": 0.0,
                                "end_time_sec": 0.7,
                                "pitch_center_midi": 60,
                                "confidence": 0.9,
                                "reason_codes": ["short_gap_bridged"],
                            }
                        ],
                        "summary": {
                            "input_candidate_count": 2,
                            "pre_postprocess_selected_count": 2,
                            "selected_count": 1,
                            "rejected_count": 0,
                            "postprocess_action_counts": {"short_gap_bridge": 1},
                            "postprocess_reason_code_counts": {"short_gap_bridged": 1},
                        },
                        "postprocess": {
                            "enabled": True,
                            "input_note_count": 2,
                            "output_note_count": 1,
                            "iteration_count": 1,
                            "action_count": 1,
                            "action_counts": {"short_gap_bridge": 1},
                            "reason_code_counts": {"short_gap_bridged": 1},
                            "actions": [
                                {
                                    "action": "short_gap_bridge",
                                    "reason_code": "short_gap_bridged",
                                    "note_ids": ["a", "b"],
                                    "output_note_id": "a+b",
                                    "start_time_sec": 0.0,
                                    "end_time_sec": 0.7,
                                    "pitch_before_midi": 60,
                                    "pitch_after_midi": 60,
                                    "details": {"mode": "merge_no_insert"},
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = build_derived_diagnostics(
                expected_notes=[],
                predicted_notes=[],
                f0_track_path=None,
                vocal_activity_path=None,
                note_candidates_path=None,
                selected_melody_path=selected_path,
                match_debug=None,
                alignment_debug=None,
                metrics_payload={},
            )

            postprocess = diagnostics["selected_melody"]["postprocess"]
            self.assertTrue(postprocess["enabled"])
            self.assertEqual(postprocess["action_count"], 1)
            self.assertEqual(postprocess["action_counts"]["short_gap_bridge"], 1)
            self.assertEqual(postprocess["reason_code_counts"]["short_gap_bridged"], 1)
            self.assertEqual(postprocess["actions"][0]["details"]["mode"], "merge_no_insert")
            self.assertEqual(diagnostics["pitch_distribution"]["melody_postprocess"]["action_count"], 1)
            self.assertTrue(diagnostics["pitch_distribution"]["melody_postprocess"]["enabled"])
            self.assertEqual(diagnostics["pitch_distribution"]["melody_postprocess"]["actions"][0]["note_ids"], ["a", "b"])



if __name__ == "__main__":
    unittest.main()
