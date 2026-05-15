import unittest
from unittest.mock import patch

import numpy as np

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.detector import PitchDetector
from app.modules.pitch.pipeline import PitchPipeline
from app.modules.pitch.reason_codes import CONTOUR_TO_CANDIDATE_BRIDGE, DP_VITERBI_SEGMENTATION
from app.modules.pitch.types import ArrangementDecision, ArrangementSegmentDecision, F0Frame, F0Track, Note, PitchPipelineRequest


class TestPitchPipeline(unittest.TestCase):
    @staticmethod
    def _frequencies_from_midi(midi_values):
        values = np.asarray(midi_values, dtype=float)
        return 440.0 * (2.0 ** ((values - 69.0) / 12.0))

    @staticmethod
    def _authoritative_f0_track(source_stem: str = "lead", input_audio_path: str = "dummy.wav") -> F0Track:
        return F0Track(
            source_stem=source_stem,
            input_audio_path=input_audio_path,
            backend="rmvpe",
            frames=[
                F0Frame(time_sec=0.1, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.3, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.5, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
            ],
            analysis_info={"extractor": "test_extractor", "authoritative": True},
        )

    def test_frames_to_notes_keeps_moderate_vibrato_phrase(self):
        detector = PitchDetector(PitchDetectionConfig())
        times = np.arange(40, dtype=float) * 0.01
        midi_values = 60.0 + 1.2 * np.sin(np.linspace(0.0, 2.0 * np.pi, times.size))
        frequencies = self._frequencies_from_midi(midi_values)
        confidences = np.full(times.shape, 0.9, dtype=float)

        notes = detector._frames_to_notes(
            times=times,
            frequencies=frequencies,
            confidences=confidences,
            duration_sec=float(times[-1]) + 0.01,
            backend="rmvpe",
        )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].pitch, "C4")
        self.assertGreater(notes[0].end_time - notes[0].start_time, 0.35)
        evidence = notes[0].segmentation_evidence
        self.assertEqual(evidence["backend"], "rmvpe")
        self.assertEqual(evidence["segmentation_strategy"], "dp_viterbi")
        self.assertEqual(evidence["voiced_frame_count"], 40)
        self.assertIn("quality_factor", evidence)
        self.assertIn("adjusted_confidence", evidence)
        self.assertIn(DP_VITERBI_SEGMENTATION, notes[0].reason_codes)

    def test_dp_frames_to_notes_suppresses_short_pitch_spike(self):
        detector = PitchDetector(PitchDetectionConfig())
        times = np.arange(70, dtype=float) * 0.01
        midi_values = np.full(times.shape, 60.0, dtype=float)
        midi_values[30:32] = 66.0
        frequencies = self._frequencies_from_midi(midi_values)
        confidences = np.full(times.shape, 0.9, dtype=float)

        notes = detector._frames_to_notes(
            times=times,
            frequencies=frequencies,
            confidences=confidences,
            duration_sec=float(times[-1]) + 0.01,
            backend="rmvpe",
        )

        self.assertEqual([note.pitch for note in notes], ["C4"])
        self.assertGreater(notes[0].end_time - notes[0].start_time, 0.6)
        self.assertEqual(notes[0].segmentation_evidence["dp_raw_segment_count"], 1)

    def test_dp_frames_to_notes_splits_supported_pitch_change(self):
        detector = PitchDetector(PitchDetectionConfig())
        times = np.arange(80, dtype=float) * 0.01
        midi_values = np.concatenate([np.full(40, 60.0), np.full(40, 64.0)])
        frequencies = self._frequencies_from_midi(midi_values)
        confidences = np.full(times.shape, 0.92, dtype=float)

        notes = detector._frames_to_notes(
            times=times,
            frequencies=frequencies,
            confidences=confidences,
            duration_sec=float(times[-1]) + 0.01,
            backend="rmvpe",
        )

        self.assertEqual([note.pitch for note in notes], ["C4", "E4"])
        self.assertLess(notes[0].end_time, notes[1].start_time + 0.02)

    def test_dp_frames_to_notes_bridges_short_unvoiced_gap(self):
        detector = PitchDetector(PitchDetectionConfig())
        times = np.arange(60, dtype=float) * 0.01
        midi_values = np.full(times.shape, 60.0, dtype=float)
        frequencies = self._frequencies_from_midi(midi_values)
        confidences = np.full(times.shape, 0.9, dtype=float)
        confidences[28:30] = 0.05

        notes = detector._frames_to_notes(
            times=times,
            frequencies=frequencies,
            confidences=confidences,
            duration_sec=float(times[-1]) + 0.01,
            backend="rmvpe",
        )

        self.assertEqual([note.pitch for note in notes], ["C4"])
        self.assertGreater(notes[0].end_time - notes[0].start_time, 0.55)

    def test_dp_frames_to_notes_drops_low_confidence_short_island(self):
        detector = PitchDetector(PitchDetectionConfig())
        times = np.arange(40, dtype=float) * 0.01
        frequencies = np.zeros(times.shape, dtype=float)
        frequencies[12:17] = self._frequencies_from_midi(np.full(5, 60.0))
        confidences = np.full(times.shape, 0.05, dtype=float)
        confidences[12:17] = 0.34

        notes = detector._frames_to_notes(
            times=times,
            frequencies=frequencies,
            confidences=confidences,
            duration_sec=float(times[-1]) + 0.01,
            backend="rmvpe",
        )

        self.assertEqual(notes, [])
    def test_safe_detect_candidates_preserves_note_debug_metadata(self):
        pipeline = PitchPipeline()
        source = Note(
            pitch="C4",
            start_time=0.0,
            end_time=0.4,
            confidence=0.9,
            candidate_id="raw_1",
            reason_codes=[CONTOUR_TO_CANDIDATE_BRIDGE],
            segmentation_evidence={"backend": "rmvpe", "quality_factor": 0.82},
            contour_bridge_evidence={"source_contour_id": "pc_1"},
        )
        cache = {}
        artifacts = {}
        warnings = []

        with patch.object(pipeline, "_detect_with_backend", return_value=[source]):
            first = pipeline._safe_detect_candidates(
                audio_path="dummy.wav",
                cache=cache,
                artifact_cache=artifacts,
                warnings=warnings,
                role="lead",
                backend="rmvpe",
            )
        second = pipeline._safe_detect_candidates(
            audio_path="dummy.wav",
            cache=cache,
            artifact_cache=artifacts,
            warnings=warnings,
            role="lead",
            backend="rmvpe",
        )

        self.assertEqual(first[0].candidate_id, "raw_1")
        self.assertEqual(first[0].segmentation_evidence["quality_factor"], 0.82)
        self.assertEqual(first[0].contour_bridge_evidence["source_contour_id"], "pc_1")
        self.assertEqual(second[0].candidate_id, "raw_1")
        self.assertEqual(second[0].segmentation_evidence["backend"], "rmvpe")

    def test_required_melody_detection_exception_bubbles_with_context(self):
        pipeline = PitchPipeline()

        with patch.object(
            pipeline,
            "_detect_with_backend",
            side_effect=RuntimeError("rmvpe model missing"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "melody_detection_failed:role=melody;backend=rmvpe;path=dummy.wav;reason=rmvpe model missing",
            ):
                pipeline.run("dummy.wav")

    def test_optional_basic_pitch_support_failure_is_warning_and_non_fatal(self):
        pipeline = PitchPipeline()

        lead_notes = [Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91)]
        request = PitchPipelineRequest(
            lead_audio_path="vocals.wav",
            source_audio_path="mix.wav",
        )

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

        def _detect(audio_path, *, backend=None):
            if str(audio_path) == "mix.wav" and str(backend) == "basic-pitch":
                raise RuntimeError("basic pitch support unavailable")
            return list(lead_notes)

        with patch.object(pipeline, "_detect_with_backend", side_effect=_detect), patch.object(
            pipeline.f0_extractor,
            "extract",
            return_value=self._authoritative_f0_track(input_audio_path="vocals.wav"),
        ), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=2.0
        ):
            result = pipeline.run(request)

        self.assertEqual(len(result.lead_notes), 1)
        self.assertTrue(
            any(
                "basic_pitch_support_optional_detection_failed:role=basic_pitch_support;backend=basic-pitch;path=mix.wav;reason=basic pitch support unavailable"
                in warning
                for warning in result.warnings
            )
        )

    def test_pipeline_uses_authoritative_f0_extractor_for_f0_track(self):
        pipeline = PitchPipeline()

        raw_notes = [Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91)]
        authoritative_f0 = F0Track(
            source_stem="lead",
            input_audio_path="dummy.wav",
            backend="rmvpe",
            frames=[
                F0Frame(time_sec=0.1, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.2, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.3, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.4, frequency_hz=261.63, confidence=0.9, voiced=True, pitch_midi=60.0),
            ],
            analysis_info={"extractor": "test_extractor", "authoritative": True},
        )

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

        with patch.object(pipeline, "_detect_with_backend", return_value=raw_notes), patch.object(
            pipeline.f0_extractor,
            "extract",
            return_value=authoritative_f0,
        ) as mocked_extract, patch.object(
            pipeline.beat_tracker,
            "track",
            return_value=_BeatResult(),
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker,
            "track",
            return_value=_DownbeatResult(),
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=2.0
        ):
            result = pipeline.run("dummy.wav")

        mocked_extract.assert_called_once_with("dummy.wav", source_stem="lead")
        self.assertIs(result.f0_track, authoritative_f0)
        self.assertEqual(result.semantic_audio.f0_track.analysis_info["extractor"], "test_extractor")
        self.assertTrue(result.analysis_info["f0_track_available"])

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
                        {"time_sec": 0.3, "frequency_hz": 261.63, "confidence": 0.9, "voiced": True, "pitch_midi": 60.0},
                        {"time_sec": 0.5, "frequency_hz": 261.63, "confidence": 0.9, "voiced": True, "pitch_midi": 60.0},
                        {"time_sec": 0.62, "frequency_hz": 0.0, "confidence": 0.0, "voiced": False, "pitch_midi": None},
                        {"time_sec": 0.7, "frequency_hz": 329.63, "confidence": 0.88, "voiced": True, "pitch_midi": 64.0},
                        {"time_sec": 0.9, "frequency_hz": 329.63, "confidence": 0.88, "voiced": True, "pitch_midi": 64.0},
                        {"time_sec": 1.1, "frequency_hz": 329.63, "confidence": 0.88, "voiced": True, "pitch_midi": 64.0},
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
            pipeline.f0_extractor,
            "extract",
            side_effect=RuntimeError("test extractor disabled"),
        ), patch.object(
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
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["candidate_authority"], "note_candidate_set_v2")
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["candidate_count"], 2)
        self.assertTrue(result.lead_notes[0].source_contour_ids)
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
        self.assertEqual(len(result.f0_track.frames), 7)
        self.assertEqual(len(result.semantic_audio.f0_track.vocal_activity), 1)

    def test_pipeline_builds_authoritative_candidates_from_f0_when_raw_detector_notes_empty(self):
        pipeline = PitchPipeline()

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

        f0_track = F0Track(
            source_stem="vocals",
            input_audio_path="vocals.wav",
            backend="rmvpe",
            frames=[
                F0Frame(time_sec=0.00, frequency_hz=261.63, confidence=0.94, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.05, frequency_hz=261.63, confidence=0.94, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.10, frequency_hz=261.63, confidence=0.94, voiced=True, pitch_midi=60.0),
                F0Frame(time_sec=0.15, frequency_hz=261.63, confidence=0.94, voiced=True, pitch_midi=60.0),
            ],
            analysis_info={"extractor": "test_extractor", "authoritative": True},
        )

        with patch.object(pipeline.detector, "detect", return_value=[]), patch.object(
            pipeline.f0_extractor,
            "extract",
            return_value=f0_track,
        ), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=1.0
        ):
            result = pipeline.run("vocals.wav")

        self.assertEqual(result.raw_notes, [])
        self.assertEqual(len(result.semantic_audio.melody_candidates.notes), 1)
        candidate = result.semantic_audio.melody_candidates.notes[0]
        self.assertEqual(candidate.source_contour_ids, ["pc_00001"])
        self.assertTrue(candidate.source_f0_frame_range)
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["candidate_authority"], "note_candidate_set_v2")
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["raw_candidates_empty"], True)
        self.assertEqual(result.analysis_info["lead_selection_authoritative"], True)
        self.assertEqual(result.lead_notes[0].source_candidate_id, candidate.candidate_id)

    def test_contour_to_candidate_bridge_runs_before_melody_selector_and_raw_artifact(self):
        pipeline = PitchPipeline()

        mock_notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.35, confidence=0.92, candidate_id="left"),
            Note(pitch="E4", start_time=1.00, end_time=1.35, confidence=0.90, candidate_id="right"),
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

        def _detect(_path):
            frames = [
                {"time_sec": 0.05, "frequency_hz": 261.63, "confidence": 0.92, "voiced": True, "pitch_midi": 60.0},
                {"time_sec": 0.40, "frequency_hz": 0.0, "confidence": 0.0, "voiced": False, "pitch_midi": None},
                {"time_sec": 0.60, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.61, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.62, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.63, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.64, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.65, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.66, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.67, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.68, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.69, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.70, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.71, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.72, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.73, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.74, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.75, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.76, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.77, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.78, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.79, "frequency_hz": 293.66, "confidence": 0.88, "voiced": True, "pitch_midi": 62.0},
                {"time_sec": 0.85, "frequency_hz": 0.0, "confidence": 0.0, "voiced": False, "pitch_midi": None},
                {"time_sec": 1.05, "frequency_hz": 329.63, "confidence": 0.90, "voiced": True, "pitch_midi": 64.0},
            ]
            pipeline.detector.last_detection_artifacts = {
                "backend": "rmvpe",
                "input_audio_path": "dummy.wav",
                "frame_count": len(frames),
                "f0_track": {
                    "input_audio_path": "dummy.wav",
                    "backend": "rmvpe",
                    "frames": frames,
                    "vocal_activity": [
                        {"start_time": 0.0, "end_time": 1.4, "state": "vocal", "voiced_ratio": 1.0, "mean_confidence": 0.88}
                    ],
                    "analysis_info": {"frame_hop_sec": 0.01},
                },
                "warnings": [],
            }
            return mock_notes

        with patch.object(pipeline.detector, "detect", side_effect=_detect), patch.object(
            pipeline.f0_extractor,
            "extract",
            side_effect=RuntimeError("test extractor disabled"),
        ), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=2.0
        ):
            result = pipeline.run("dummy.wav")

        bridged_raw = [note for note in result.raw_notes if note.candidate_origin == CONTOUR_TO_CANDIDATE_BRIDGE]
        self.assertEqual(len(bridged_raw), 1)
        self.assertIn(CONTOUR_TO_CANDIDATE_BRIDGE, bridged_raw[0].reason_codes)
        self.assertEqual(bridged_raw[0].contour_bridge_evidence["raw_overlap_duration_sec"], 0.0)
        bridge_summary = result.semantic_audio.melody_candidates.analysis_info["contour_to_candidate_bridge"]
        self.assertEqual(bridge_summary["accepted_count"], 1)
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["contour_bridge_candidate_count"], 1)
        self.assertTrue(any(CONTOUR_TO_CANDIDATE_BRIDGE in note.reason_codes for note in result.lead_notes))

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
            pipeline.f0_extractor,
            "extract",
            return_value=self._authoritative_f0_track(),
        ), patch.object(
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
            pipeline.f0_extractor,
            "extract",
            return_value=self._authoritative_f0_track(),
        ), patch.object(
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
            pipeline.f0_extractor,
            "extract",
            return_value=self._authoritative_f0_track(),
        ), patch.object(
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
        self.assertEqual(result.lead_notes[0].pitch, "C4")
        self.assertEqual(result.lead_notes[0].source_contour_ids, ["pc_00001"])
        self.assertEqual(result.semantic_audio.melody_candidates.analysis_info["candidate_authority"], "note_candidate_set_v2")
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
        ) as mocked_downbeat, patch.object(
            pipeline.f0_extractor,
            "extract",
            return_value=self._authoritative_f0_track(source_stem="vocals", input_audio_path="vocals.wav"),
        ), patch(
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

    def test_analysis_info_exposes_arrangement_decision(self):
        pipeline = PitchPipeline()

        mock_notes = [
            Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91),
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

        request = PitchPipelineRequest(
            lead_audio_path="vocals.wav",
            source_audio_path="mix.wav",
            rhythm_audio_path="mix.wav",
            key_audio_path="mix.wav",
            source_stems={"vocals": "vocals.wav", "accompaniment": "accompaniment.wav"},
        )

        with patch.object(pipeline.detector, "detect", return_value=mock_notes), patch.object(
            pipeline.f0_extractor,
            "extract",
            return_value=self._authoritative_f0_track(source_stem="vocals", input_audio_path="vocals.wav"),
        ), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch.object(
            pipeline.downbeat_tracker, "track", return_value=_DownbeatResult()
        ), patch(
            "app.modules.pitch.pipeline.get_audio_duration", return_value=2.0
        ):
            result = pipeline.run(request)

        decision = result.analysis_info.get("arrangement_decision")
        self.assertIsInstance(decision, dict)
        self.assertEqual(decision["policy"], "deterministic_melody_source_arbitration")
        self.assertEqual(decision["lead_source"], "rmvpe")
        self.assertEqual(decision["lead_source_stem"], "vocals")
        self.assertEqual(decision["lead_note_count"], 1)
        self.assertIn("support_note_count", decision)
        self.assertIn("max_polyphony", decision)

    def test_instrumental_topline_prefers_higher_pitch_on_tie(self):
        pipeline = PitchPipeline(PitchDetectionConfig(arrangement_support_conflict_window_sec=0.08))

        selected = pipeline._select_instrumental_topline(
            [
                Note(pitch="C4", start_time=0.0, end_time=0.6, confidence=0.8),
                Note(pitch="G4", start_time=0.0, end_time=0.6, confidence=0.8),
            ]
        )

        self.assertEqual([note.pitch for note in selected], ["G4"])

    def test_instrumental_topline_caps_duration_for_pedal_bass(self):
        pipeline = PitchPipeline(PitchDetectionConfig(arrangement_support_conflict_window_sec=0.08))

        selected = pipeline._select_instrumental_topline(
            [
                Note(pitch="C2", start_time=0.0, end_time=8.0, confidence=0.5),
                Note(pitch="C5", start_time=0.02, end_time=1.38, confidence=0.95),
            ]
        )

        self.assertEqual([note.pitch for note in selected], ["C5"])

    def test_instrumental_hook_notes_only_use_instrumental_segments(self):
        pipeline = PitchPipeline(PitchDetectionConfig(arrangement_support_conflict_window_sec=0.08))
        decision = ArrangementDecision(
            selected_support_notes=[
                Note(pitch="D5", start_time=0.1, end_time=0.7, confidence=0.9),
                Note(pitch="E5", start_time=2.1, end_time=2.7, confidence=0.9),
            ],
            segment_decisions=[
                ArrangementSegmentDecision(start_time=0.0, end_time=1.0, state="instrumental"),
                ArrangementSegmentDecision(start_time=2.0, end_time=3.0, state="vocal"),
            ],
        )

        notes = pipeline._build_instrumental_hook_notes(
            decision=decision,
            bpm=120.0,
            beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
            boundaries=[0.0, 2.0, 4.0],
            beats_per_bar=4,
        )

        self.assertEqual([note.pitch for note in notes], ["D5"])
        self.assertEqual(notes[0].measure_num, 1)
        self.assertEqual(notes[0].source, "instrumental_hook")


if __name__ == "__main__":
    unittest.main()
