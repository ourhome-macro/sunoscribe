from __future__ import annotations

import importlib
import inspect
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any


def _load_first_attr(*candidates: tuple[str, str]) -> Any:
    errors: list[str] = []
    for module_name, attr_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
            continue
        if hasattr(module, attr_name):
            return getattr(module, attr_name)
        errors.append(f"{module_name}: missing {attr_name}")
    raise AssertionError("No revision export entrypoint found. Tried:\n" + "\n".join(errors))


def _track_windows(instrument) -> list[tuple[int, float, float]]:
    return [
        (int(note.pitch), round(float(note.start), 3), round(float(note.end), 3))
        for note in instrument.notes
    ]


class TestScoreExportServiceContracts(unittest.TestCase):
    def _load_export_entrypoint(self) -> Any:
        return _load_first_attr(
            ("app.services.score_revision_service", "export_score_revision"),
            ("app.services.score_export_service", "export_score_revision"),
            ("app.services.score_service", "export_score_revision"),
        )

    def test_export_entrypoint_is_revision_scoped(self) -> None:
        export_entrypoint = self._load_export_entrypoint()
        params = set(inspect.signature(export_entrypoint).parameters)
        self.assertTrue(
            {"score_revision_id", "revision_id"} & params,
            "revision-scoped export must identify the exact ScoreRevision to export",
        )

    def test_export_entrypoint_keeps_format_selection_but_not_score_level_ambiguity(self) -> None:
        export_entrypoint = self._load_export_entrypoint()
        params = set(inspect.signature(export_entrypoint).parameters)
        self.assertTrue({"export_format", "format", "artifact_type"} & params)
        self.assertFalse(
            "score_id" in params and not ({"score_revision_id", "revision_id"} & params),
            "export should not be scoped only by Score/Project once multiple revisions exist",
        )

    def test_export_entrypoint_contract_exposes_user_access_check(self) -> None:
        export_entrypoint = self._load_export_entrypoint()
        params = set(inspect.signature(export_entrypoint).parameters)
        self.assertTrue({"db", "session"} & params, "export should resolve revisions through persisted lineage")
        self.assertTrue({"user", "current_user"} & params, "export should remain user access scoped")

    def test_revision_export_rejects_score_data_not_derived_from_score_ir(self) -> None:
        from app.models.score_revision import ScoreRevision
        from app.services.render_export_service import RenderExportService

        revision = ScoreRevision(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            score_id=uuid.uuid4(),
            revision_number=1,
            score_ir={"meta": {"bpm": 120.0}, "notes": [{"id": "n1", "pitch": "C4"}], "measures": []},
            score_data={"bpm": 120.0, "measures": [{"measure_num": 1, "notes": []}]},
        )

        with self.assertRaisesRegex(Exception, "not derived from score_ir"):
            RenderExportService()._build_export_payload(revision=revision, format_key="view")

    def test_revision_export_accepts_score_ir_derived_score_data(self) -> None:
        from app.models.score_revision import ScoreRevision
        from app.services.render_export_service import RenderExportService

        score_ir = {
            "meta": {"bpm": 120.0},
            "notes": [
                {
                    "id": "n1",
                    "pitch": "C4",
                    "start_tick": 0,
                    "duration_tick": 480,
                    "measure_num": 1,
                    "beat_position": 1.0,
                    "confidence": 0.4,
                    "reason_codes": ["low_confidence"],
                    "source_candidate_id": "cand1",
                    "quantized_note_id": "qn1",
                }
            ],
            "measures": [],
        }
        revision = ScoreRevision(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            score_id=uuid.uuid4(),
            revision_number=1,
            score_ir=score_ir,
            score_data={"score_ir": score_ir, "source_of_truth": "score_ir", "measures": []},
        )

        artifact_type, filename, mime_type, payload = RenderExportService()._build_export_payload(
            revision=revision,
            format_key="score_view",
        )

        self.assertEqual(artifact_type, "score_view")
        self.assertEqual(filename, "score_view.json")
        self.assertEqual(mime_type, "application/json")
        self.assertIn(b"source_of_truth", payload)
        view_data = json.loads(payload.decode("utf-8"))
        self.assertEqual(view_data["client_summary"]["note_count"], 1)
        self.assertEqual(view_data["client_summary"]["uncertain_note_count"], 1)
        self.assertEqual(view_data["client_summary"]["low_confidence_note_count"], 1)
        self.assertEqual(view_data["client_summary"]["score_notes"][0]["reason_codes"], ["low_confidence", "uncertain"])
        self.assertNotIn("storage_path", view_data["client_summary"])

    def test_revision_export_midi_preserves_lead_vocal_timeline_without_hook_track(self) -> None:
        import pretty_midi

        from app.models.score_revision import ScoreRevision
        from app.services.render_export_service import RenderExportService

        score_ir = {
            "meta": {"bpm": 96.0},
            "notes": [
                {
                    "id": "n1",
                    "pitch": "C4",
                    "start_tick": 0,
                    "duration_tick": 120,
                    "measure_num": 1,
                    "beat_position": 1.0,
                    "confidence": 0.9,
                },
                {
                    "id": "n2",
                    "pitch": "D4",
                    "start_tick": 120,
                    "duration_tick": 480,
                    "measure_num": 1,
                    "beat_position": 1.5,
                    "confidence": 0.88,
                },
                {
                    "id": "n3",
                    "pitch": "E4",
                    "start_tick": 600,
                    "duration_tick": 120,
                    "measure_num": 2,
                    "beat_position": 1.0,
                    "confidence": 0.87,
                },
            ],
            "measures": [],
        }
        revision = ScoreRevision(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            score_id=uuid.uuid4(),
            revision_number=1,
            score_ir=score_ir,
            score_data={
                "bpm": 96.0,
                "source_of_truth": "score_ir",
                "score_ir": score_ir,
                "measures": [
                    {
                        "measure_num": 1,
                        "notes": [
                            {
                                "pitch": "C4",
                                "start_time": 6.0,
                                "end_time": 6.12,
                                "duration_beats": 0.25,
                                "note_type": "sixteenth",
                                "beat_position": 1.0,
                                "confidence": 0.9,
                            },
                            {
                                "pitch": "D4",
                                "start_time": 6.18,
                                "end_time": 6.68,
                                "duration_beats": 1.0,
                                "note_type": "quarter",
                                "beat_position": 1.5,
                                "confidence": 0.88,
                            },
                        ],
                    },
                    {
                        "measure_num": 2,
                        "notes": [
                            {
                                "pitch": "E4",
                                "start_time": 7.25,
                                "end_time": 7.37,
                                "duration_beats": 0.25,
                                "note_type": "sixteenth",
                                "beat_position": 1.0,
                                "confidence": 0.87,
                            }
                        ],
                    },
                ],
                "instrumental_melody_notes": [],
            },
        )

        artifact_type, filename, mime_type, payload = RenderExportService()._build_export_payload(
            revision=revision,
            format_key="midi",
        )

        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / filename
            output_path.write_bytes(payload)
            midi = pretty_midi.PrettyMIDI(str(output_path))

        self.assertEqual(artifact_type, "midi")
        self.assertEqual(filename, "score.mid")
        self.assertEqual(mime_type, "audio/midi")
        self.assertEqual([instrument.name for instrument in midi.instruments], ["Lead Vocal"])
        self.assertNotIn("Instrumental Hook", [instrument.name for instrument in midi.instruments])
        self.assertEqual([note[0] for note in _track_windows(midi.instruments[0])], [60, 62, 64])
        for actual, expected in zip(
            _track_windows(midi.instruments[0]),
            [(60, 6.0, 6.12), (62, 6.18, 6.68), (64, 7.25, 7.37)],
        ):
            self.assertEqual(actual[0], expected[0])
            self.assertAlmostEqual(actual[1], expected[1], delta=0.002)
            self.assertAlmostEqual(actual[2], expected[2], delta=0.002)


if __name__ == "__main__":
    unittest.main()
