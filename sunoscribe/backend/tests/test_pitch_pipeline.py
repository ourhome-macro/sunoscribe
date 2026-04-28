import unittest
from unittest.mock import patch

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.pipeline import PitchPipeline
from app.modules.pitch.types import Note, PitchPipelineRequest


class TestPitchPipeline(unittest.TestCase):
    def test_run_with_mocks(self):
        pipeline = PitchPipeline()

        mock_notes = [
            Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91),
            Note(pitch="E4", start_time=0.7, end_time=1.2, confidence=0.88),
        ]

        class _BeatResult:
            bpm = 120.0
            beat_times = [0.0, 0.5, 1.0]
            confidence = 0.93

        class _KeyResult:
            key = "C Major"
            confidence = 0.89
            method = "librosa"

        class _DownbeatResult:
            downbeat_times = [0.0]
            method = "librosa"
            confidence = 0.8
            beats_per_bar = 4

        def _detect(_path):
            pipeline.detector.last_detection_artifacts = {
                "backend": "rmvpe",
                "input_audio_path": "dummy.wav",
                "frame_count": 2,
                "f0_track": {
                    "input_audio_path": "dummy.wav",
                    "backend": "rmvpe",
                    "frames": [
                        {"time_sec": 0.1, "frequency_hz": 261.63, "confidence": 0.9, "voiced": True, "pitch_midi": 60.0},
                        {"time_sec": 0.7, "frequency_hz": 329.63, "confidence": 0.88, "voiced": True, "pitch_midi": 64.0},
                    ],
                    "vocal_activity": [
                        {"start_time": 0.0, "end_time": 1.2, "state": "vocal", "voiced_ratio": 1.0, "mean_confidence": 0.89}
                    ],
                    "analysis_info": {"frame_hop_sec": 0.1},
                },
                "warnings": [],
            }
            return mock_notes

        with patch.object(pipeline.detector, "detect", side_effect=_detect), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=12.34
        ):
            result = pipeline.run("dummy.wav")

        self.assertEqual(result.version, "1.4")
        self.assertEqual(result.meta.bpm, 120.0)
        self.assertEqual(result.meta.key, "C Major")
        self.assertEqual(result.meta.duration_sec, 12.34)
        self.assertEqual(result.meta.time_signature, "4/4")
        self.assertIn(result.meta.rhythm_type, {"stable", "unstable", "free"})
        self.assertEqual(len(result.raw_notes), 2)
        self.assertEqual(len(result.lead_notes), 2)
        self.assertGreaterEqual(len(result.measures), 1)
        self.assertEqual(result.raw_notes[0].pitch, "C4")
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["candidate_count"], 2)
        self.assertEqual(result.analysis_info["quantize_mode"], "adaptive")
        self.assertEqual(result.analysis_info["measure_segmentation"], "enabled")
        self.assertIn("has_accompaniment", result.analysis_info)
        self.assertIn("downbeat_method", result.analysis_info)
        self.assertIn("downbeat_confidence", result.analysis_info)
        self.assertIn("downbeat_count", result.analysis_info)
        self.assertEqual(result.analysis_info["measure_boundary_source"], "downbeat_sequence")
        self.assertIn("rhythm_stability", result.analysis_info)
        self.assertEqual(result.analysis_info["key_backend"], "librosa")
        self.assertIsNotNone(result.f0_track)
        self.assertEqual(result.f0_track.backend, "rmvpe")
        self.assertEqual(len(result.f0_track.frames), 2)
        self.assertEqual(len(result.semantic_audio.f0_track.vocal_activity), 1)

    def test_time_signature_and_anacrusis_with_downbeats(self):
        cfg = PitchDetectionConfig(beats_per_bar=3, beat_unit=8)
        pipeline = PitchPipeline(cfg)

        mock_notes = [
            Note(pitch="C4", start_time=0.2, end_time=0.6, confidence=0.91),
            Note(pitch="E4", start_time=1.2, end_time=1.6, confidence=0.88),
        ]

        class _BeatResult:
            bpm = 120.0
            beat_times = [0.0, 0.5, 1.0, 1.5, 2.0]
            confidence = 0.93

        class _KeyResult:
            key = "C Major"
            confidence = 0.89
            method = "librosa_auto_fallback"

        class _DownbeatResult:
            downbeat_times = [0.8, 2.0]
            method = "librosa"
            confidence = 0.8
            beats_per_bar = 3

        with patch.object(pipeline.detector, "detect", return_value=mock_notes), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=3.2
        ):
            result = pipeline.run("dummy.wav")

        self.assertEqual(result.meta.time_signature, "3/8")
        self.assertGreaterEqual(len(result.measures), 1)
        self.assertTrue(result.measures[0]["is_anacrusis"])
        self.assertAlmostEqual(result.measures[0]["start_time"], 0.0, places=3)
        self.assertAlmostEqual(result.measures[0]["end_time"], 0.8, places=3)
        if len(result.measures) >= 2:
            self.assertAlmostEqual(result.measures[1]["start_time"], 0.8, places=3)
            self.assertAlmostEqual(result.measures[1]["end_time"], 2.0, places=3)
        self.assertEqual(result.analysis_info["beats_per_bar"], 3)
        self.assertEqual(result.analysis_info["beat_unit"], 8)
        self.assertEqual(result.analysis_info["key_backend"], "librosa_auto_fallback")
        self.assertTrue(any("Key backend downgraded" in w for w in result.warnings))

    def test_run_keeps_other_outputs_when_key_analysis_fails(self):
        pipeline = PitchPipeline()

        mock_notes = [
            Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91),
            Note(pitch="E4", start_time=0.7, end_time=1.2, confidence=0.88),
        ]

        class _BeatResult:
            bpm = 120.0
            beat_times = [0.0, 0.5, 1.0]
            confidence = 0.93

        class _DownbeatResult:
            downbeat_times = [0.0]
            method = "librosa"
            confidence = 0.8
            beats_per_bar = 4

        with patch.object(pipeline.detector, "detect", return_value=mock_notes), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(
            pipeline.key_analyzer, "analyze", side_effect=RuntimeError("key backend crashed")
        ), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=2.0
        ):
            result = pipeline.run("dummy.wav")

        self.assertEqual(result.meta.key, "Unknown")
        self.assertEqual(result.analysis_info["key_backend"], "key_failed_fallback")
        self.assertEqual(len(result.raw_notes), 2)
        self.assertTrue(any("Key analysis failed" in w for w in result.warnings))

    def test_pipeline_applies_melody_selector_before_quantize(self):
        pipeline = PitchPipeline()

        mock_notes = [
            Note(pitch="C2", start_time=0.0, end_time=0.4, confidence=0.95),
            Note(pitch="C4", start_time=0.5, end_time=0.62, confidence=0.58),
            Note(pitch="D4", start_time=1.0, end_time=1.5, confidence=0.9),
        ]

        class _BeatResult:
            bpm = 120.0
            beat_times = [0.0, 0.5, 1.0, 1.5]
            confidence = 0.93

        class _KeyResult:
            key = "C Major"
            confidence = 0.89
            method = "librosa"

        class _DownbeatResult:
            downbeat_times = [0.0]
            method = "librosa"
            confidence = 0.8
            beats_per_bar = 4

        with patch.object(pipeline.detector, "detect", return_value=mock_notes), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=2.0
        ):
            result = pipeline.run("dummy.wav")

        self.assertEqual(result.analysis_info["detected_note_count"], 3)
        self.assertEqual(result.analysis_info["melody_note_count"], 1)
        self.assertEqual(result.analysis_info["melody_notes_removed"], 2)
        self.assertEqual(len(result.raw_notes), 3)
        self.assertEqual(len(result.lead_notes), 1)
        self.assertEqual(result.lead_notes[0].pitch, "D4")
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["candidate_count"], 3)
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["selected_count"], 1)

    def test_pipeline_uses_split_inputs_for_semantic_roles(self):
        pipeline = PitchPipeline()

        notes_by_path = {
            "vocals.wav": [Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91)],
            "other.wav": [
                Note(pitch="E4", start_time=0.2, end_time=0.8, confidence=0.75),
                Note(pitch="G4", start_time=0.9, end_time=1.4, confidence=0.72),
            ],
            "bass.wav": [Note(pitch="C2", start_time=0.0, end_time=0.9, confidence=0.88)],
        }

        class _BeatResult:
            bpm = 96.0
            beat_times = [0.0, 0.625, 1.25, 1.875]
            confidence = 0.92

        class _KeyResult:
            key = "C Major"
            confidence = 0.83
            method = "librosa"

        class _DownbeatResult:
            downbeat_times = [0.0]
            method = "librosa"
            confidence = 0.81
            beats_per_bar = 4

        request = PitchPipelineRequest(
            lead_audio_path="vocals.wav",
            source_audio_path="mix.wav",
            rhythm_audio_path="drums.wav",
            key_audio_path="other.wav",
            harmony_audio_path="other.wav",
            bass_audio_path="bass.wav",
            source_stems={
                "vocals": "vocals.wav",
                "accompaniment": "accompaniment.wav",
                "drums": "drums.wav",
                "other": "other.wav",
                "bass": "bass.wav",
            },
        )

        with patch.object(
            pipeline.detector,
            "detect",
            side_effect=lambda path: list(notes_by_path.get(path, [])),
        ) as mocked_detect, patch.object(
            pipeline.beat_tracker,
            "track",
            return_value=_BeatResult(),
        ) as mocked_beat, patch.object(
            pipeline.key_analyzer,
            "analyze",
            return_value=_KeyResult(),
        ) as mocked_key, patch.object(
            pipeline.downbeat_tracker,
            "track",
            return_value=_DownbeatResult(),
        ) as mocked_downbeat, patch(
            "app.modules.pitch.pipeline.get_audio_duration",
            return_value=3.0,
        ):
            result = pipeline.run(request)

        self.assertEqual(mocked_detect.call_count, 3)
        self.assertEqual(mocked_beat.call_args.args[0], "drums.wav")
        self.assertEqual(mocked_key.call_args.args[0], "other.wav")
        self.assertEqual(mocked_downbeat.call_args.args[0], "drums.wav")
        self.assertEqual(result.analysis_info["lead_audio_source"], "vocals")
        self.assertEqual(result.analysis_info["rhythm_audio_source"], "drums")
        self.assertEqual(result.analysis_info["key_audio_source"], "other")
        self.assertEqual(result.analysis_info["harmony_candidate_count"], 2)
        self.assertEqual(result.analysis_info["bass_root_candidate_count"], 1)
        self.assertEqual(len(result.raw_notes), 1)
        self.assertEqual(len(result.lead_notes), 1)
        self.assertEqual(len(result.semantic_audio.harmony_candidates.notes), 2)
        self.assertEqual(len(result.semantic_audio.bass_root_candidates.notes), 1)
        self.assertEqual(result.semantic_audio.rhythm_grid.source_stem, "drums")


if __name__ == "__main__":
    unittest.main()
