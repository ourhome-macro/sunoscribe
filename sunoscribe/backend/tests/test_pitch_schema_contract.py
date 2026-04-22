import json
import unittest
from pathlib import Path

from app.modules.pitch.pipeline import PitchPipeline
from app.modules.pitch.types import Note


class TestPitchSchemaContract(unittest.TestCase):
    def setUp(self):
        self.schema_path = (
            Path(__file__).resolve().parents[1] / "docs" / "pitch" / "pitch_p1.schema.json"
        )

    def test_schema_file_exists_and_has_required_sections(self):
        self.assertTrue(self.schema_path.exists(), "Schema 文件不存在")
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema.get("type"), "object")
        required = set(schema.get("required", []))
        self.assertTrue({"version", "meta", "analysis_info", "measures", "warnings"}.issubset(required))

    def test_pipeline_output_contract_keys(self):
        pipeline = PitchPipeline()

        class _BeatResult:
            bpm = 120.0
            beat_times = [0.0, 0.5, 1.0, 1.5]
            confidence = 0.9

        class _KeyResult:
            key = "C Major"
            confidence = 0.88

        class _DownbeatResult:
            downbeat_times = [0.0, 2.0]
            method = "librosa"
            confidence = 0.8
            beats_per_bar = 4

        notes = [
            Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.95),
            Note(pitch="E4", start_time=0.7, end_time=1.1, confidence=0.9),
        ]

        from unittest.mock import patch

        with patch.object(pipeline.detector, "detect", return_value=notes), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch("app.modules.pitch.pipeline.get_audio_duration", return_value=4.0):
            result = pipeline.run("dummy.wav").to_dict()

        for key in ["version", "meta", "analysis_info", "measures", "warnings"]:
            self.assertIn(key, result)

        self.assertIn("lead_notes", result)
        self.assertIn("semantic_audio", result)
        self.assertIn("downbeat_method", result["analysis_info"])
        self.assertIn("measure_boundary_source", result["analysis_info"])
        self.assertIn("quantized_measure_alignment", result["analysis_info"])

        if result["measures"]:
            m = result["measures"][0]
            for key in ["measure_num", "start_time", "end_time", "is_anacrusis", "notes"]:
                self.assertIn(key, m)


if __name__ == "__main__":
    unittest.main()
