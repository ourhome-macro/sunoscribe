from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.modules.pitch.types import F0Frame, F0Track, MetaInfo, Note, NoteCandidateSet, PitchAnalysisResult, PitchPipelineRequest, RhythmGrid, SemanticAudioResult, VocalActivitySegment
from app.modules.score_ir import ScoreIR, ScoreIRBuilder, ScoreIRSerializer, ScoreMeasure, ScoreMeta, ScoreNote
from app.modules.pitch import MidiExporter
from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisService
from app.services.melody_transcription_service import MelodyTranscriptionService
from app.services.media_ingest_service import MediaIngestService
from app.services.workspace import ProjectWorkspace


class _FakeSeparator:
    def __init__(self, stems: dict[str, Path]) -> None:
        self._stems = stems
        self.calls = []

    def separate(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        return type("SeparationResult", (), {"stem_paths": {name: str(path) for name, path in self._stems.items()}})()


class _PassthroughAudioProcessor:
    def __init__(self) -> None:
        self.calls = []

    def convert(self, source_path: str, _output_path: str) -> str:
        self.calls.append((source_path, _output_path))
        return source_path


class _FakeNormalizingAudioProcessor:
    def __init__(self) -> None:
        self.calls = []

    def convert(self, source_path: str, output_path: str) -> str:
        self.calls.append((source_path, output_path))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(Path(source_path).read_bytes())
        return output_path


class _CapturePitchPipeline:
    def __init__(self) -> None:
        self.last_request = None

    def run(self, request):
        self.last_request = request
        assert isinstance(request, PitchPipelineRequest)
        return PitchAnalysisResult(
            version="test",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                rhythm_type="stable",
                duration_sec=3.0,
                time_signature="4/4",
            ),
            measures=[
                {
                    "measure_num": 1,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "notes": [
                        {
                            "pitch": "A3",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            lead_notes=[],
            raw_notes=[],
            f0_track=F0Track(
                source_stem="vocals",
                input_audio_path=str(request.lead_audio_path),
                backend="rmvpe",
                frames=[
                    F0Frame(time_sec=0.1, frequency_hz=220.0, confidence=0.9, voiced=True, pitch_midi=57.0),
                    F0Frame(time_sec=0.2, frequency_hz=220.0, confidence=0.9, voiced=True, pitch_midi=57.0),
                    F0Frame(time_sec=0.3, frequency_hz=220.0, confidence=0.9, voiced=True, pitch_midi=57.0),
                ],
                vocal_activity=[
                    VocalActivitySegment(
                        start_time=0.0,
                        end_time=0.5,
                        state="vocal",
                        voiced_ratio=1.0,
                        mean_confidence=0.9,
                        source_stem="vocals",
                    )
                ],
            ),
            semantic_audio=SemanticAudioResult(
                source_stems=dict(request.source_stems),
                rhythm_grid=RhythmGrid(
                    source_stem="drums",
                    input_audio_path="drums.wav",
                    bpm=120.0,
                    beat_times=[0.0, 0.5, 1.0, 1.5],
                    beats_per_bar=4,
                    beat_unit=4,
                ),
            ),
        )


class _EmptyPitchPipeline:
    def __init__(self) -> None:
        self.last_request = None

    def run(self, request):
        self.last_request = request
        return PitchAnalysisResult(
            version="test",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                rhythm_type="stable",
                duration_sec=3.0,
                time_signature="4/4",
            ),
            analysis_info={
                "detected_note_count": 0,
                "melody_note_count": 0,
            },
            measures=[],
            lead_notes=[],
            raw_notes=[],
            warnings=["No melody candidates detected from lead audio."],
        )


class _SemanticCandidatePitchPipeline:
    def __init__(self) -> None:
        self.last_request = None

    def run(self, request):
        self.last_request = request
        return PitchAnalysisResult(
            version="test",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                rhythm_type="stable",
                duration_sec=3.0,
                time_signature="4/4",
            ),
            measures=[
                {
                    "measure_num": 1,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "notes": [
                        {
                            "pitch": "A3",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            lead_notes=[],
            raw_notes=[],
            f0_track=F0Track(
                source_stem="vocals",
                input_audio_path=str(request.lead_audio_path),
                backend="rmvpe",
                frames=[
                    F0Frame(time_sec=0.10, frequency_hz=220.0, confidence=0.92, voiced=True, pitch_midi=57.0),
                    F0Frame(time_sec=0.18, frequency_hz=220.0, confidence=0.92, voiced=True, pitch_midi=57.0),
                    F0Frame(time_sec=0.26, frequency_hz=220.0, confidence=0.92, voiced=True, pitch_midi=57.0),
                    F0Frame(time_sec=0.34, frequency_hz=220.0, confidence=0.92, voiced=True, pitch_midi=57.0),
                ],
            ),
            semantic_audio=SemanticAudioResult(
                source_stems=dict(request.source_stems),
                melody_candidates=NoteCandidateSet(
                    role="melody_candidates",
                    source_stem="vocals",
                    input_audio_path=str(request.lead_audio_path),
                    notes=[
                        Note(
                            pitch="A3",
                            start_time=0.10,
                            end_time=0.34,
                            confidence=0.88,
                            candidate_id="sem_raw_1",
                        )
                    ],
                    selected_notes=[
                        Note(
                            pitch="A3",
                            start_time=0.10,
                            end_time=0.34,
                            confidence=0.93,
                            candidate_id="sem_selected_1",
                        )
                    ],
                    analysis_info={"backend": "semantic_detector_v1"},
                ),
                rhythm_grid=RhythmGrid(
                    source_stem="drums",
                    input_audio_path="drums.wav",
                    bpm=120.0,
                    beat_times=[0.0, 0.5, 1.0, 1.5],
                    beats_per_bar=4,
                    beat_unit=4,
                ),
            ),
        )


class _CaptureMelodySelector:
    def __init__(self) -> None:
        self.last_kwargs = None

    def select(self, **kwargs):
        self.last_kwargs = kwargs
        return {
            "version": "selected_melody_v1",
            "selected_notes": [
                {
                    "candidate_id": "sel_1",
                    "source_candidate_id": "sel_1",
                    "start_time_sec": 0.1,
                    "end_time_sec": 0.3,
                    "pitch_center_midi": 57,
                    "confidence": 0.9,
                    "source_contour_ids": ["pc_00001"],
                    "source_candidate_ids": ["sel_1"],
                    "source_f0_frame_range": {"start_frame_index": 0, "end_frame_index": 2},
                    "reason_codes": [],
                }
            ],
        }


class _FakeScoreIRBuilder:
    def __init__(self) -> None:
        self.last_args = None
        self.last_kwargs = None
        self._delegate = ScoreIRBuilder()

    def build(self, *args, **kwargs):
        self.last_args = args
        self.last_kwargs = kwargs
        if args:
            return self._delegate.build(*args, **kwargs)
        return ScoreIR(
            meta=ScoreMeta(
                source_version="test",
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                duration_sec=3.0,
                time_signature="4/4",
                rhythm_type="stable",
                total_measures=0,
                has_anacrusis=False,
            ),
            notes=[
                ScoreNote(
                    id="n1",
                    pitch="C4",
                    pitch_midi=60,
                    start_time=0.0,
                    end_time=0.5,
                    duration_sec=0.5,
                    duration_beats=1.0,
                    note_type="quarter",
                    measure_num=1,
                    beat_position=1.0,
                    confidence=0.9,
                    lyric=None,
                    is_raw=False,
                    is_candidate_ornament=False,
                    tie_candidate=False,
                    source="test",
                )
            ],
            measures=[ScoreMeasure(measure_num=1, start_time=0.0, end_time=2.0, duration_sec=2.0, is_anacrusis=False, note_ids=["n1"])],
        )


class TestAudioAnalysisService(unittest.TestCase):
    def test_default_audio_processor_uses_mvp_canonical_format(self) -> None:
        service = AudioAnalysisService(
            audio_processor=_FakeNormalizingAudioProcessor(),
            vocal_separator=None,
            lyrics_recognizer=None,
            pitch_pipeline=None,
            analysis_inferencer=None,
            midi_exporter=None,
        )

        processor = service._try_make_audio_processor()

        self.assertIsNotNone(processor)
        self.assertEqual(processor.default_config.sample_rate, 44100)
        self.assertEqual(processor.default_config.channels, 2)
        self.assertEqual(processor.default_config.output_format, "wav")

    def test_media_ingest_converts_video_to_canonical_audio(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_video = root / "source.mp4"
            source_video.write_bytes(b"video")
            canonical_audio = root / "projects" / "case" / "preprocess" / "source.wav"
            audio_processor = _FakeNormalizingAudioProcessor()

            result = MediaIngestService(audio_processor).ingest(source_video, canonical_audio)

            self.assertEqual(audio_processor.calls, [(str(source_video), str(canonical_audio))])
            self.assertEqual(result.canonical_audio_path, canonical_audio)
            self.assertTrue(canonical_audio.exists())
            self.assertEqual(result.metadata["stage"], "media_ingest")


    def test_melody_transcription_passes_vocal_activity_to_selector(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = ProjectWorkspace(project_id="melody_selector_bridge", projects_root=root / "projects")
            workspace.ensure_structure()
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"audio")
            selector = _CaptureMelodySelector()
            service = MelodyTranscriptionService(
                pitch_pipeline=_CapturePitchPipeline(),
                serializer=AudioAnalysisService(
                    audio_processor=_PassthroughAudioProcessor(),
                    vocal_separator=None,
                    lyrics_recognizer=None,
                    pitch_pipeline=None,
                    analysis_inferencer=None,
                    midi_exporter=None,
                )._serialize,
                pitch_request_builder=lambda **kwargs: PitchPipelineRequest(
                    lead_audio_path=str(kwargs["vocals_path"] or kwargs["fallback_audio_path"]),
                    source_audio_path=str(kwargs["source_audio_path"]),
                    rhythm_audio_path=str(kwargs["accompaniment_path"]) if kwargs.get("accompaniment_path") else None,
                    source_stems={name: str(path) for name, path in kwargs.get("stem_paths", {}).items()},
                ),
                short_exception=lambda exc: str(exc),
                melody_selector=selector,
            )

            result = service.transcribe(
                source_audio_path=source_audio,
                canonical_audio_path=source_audio,
                vocals_path=source_audio,
                accompaniment_path=None,
                stem_paths={"vocals": source_audio},
                workspace=workspace,
            )

            self.assertIsNotNone(selector.last_kwargs)
            self.assertEqual(selector.last_kwargs["vocal_activity"]["segments"][0]["state"], "vocal")
            self.assertEqual(result.selected_melody_dict["selected_notes"][0]["candidate_id"], "sel_1")
            self.assertEqual(result.vocal_activity_dict["segments"][0]["source_stem"], "vocals")

    def test_melody_transcription_builds_note_candidates_with_raw_source_trace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = ProjectWorkspace(project_id="melody_builder_trace", projects_root=root / "projects")
            workspace.ensure_structure()
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"audio")
            selector = _CaptureMelodySelector()
            service = MelodyTranscriptionService(
                pitch_pipeline=_SemanticCandidatePitchPipeline(),
                serializer=AudioAnalysisService(
                    audio_processor=_PassthroughAudioProcessor(),
                    vocal_separator=None,
                    lyrics_recognizer=None,
                    pitch_pipeline=None,
                    analysis_inferencer=None,
                    midi_exporter=None,
                )._serialize,
                pitch_request_builder=lambda **kwargs: PitchPipelineRequest(
                    lead_audio_path=str(kwargs["vocals_path"] or kwargs["fallback_audio_path"]),
                    source_audio_path=str(kwargs["source_audio_path"]),
                    rhythm_audio_path=str(kwargs["accompaniment_path"]) if kwargs.get("accompaniment_path") else None,
                    source_stems={name: str(path) for name, path in kwargs.get("stem_paths", {}).items()},
                ),
                short_exception=lambda exc: str(exc),
                melody_selector=selector,
            )

            result = service.transcribe(
                source_audio_path=source_audio,
                canonical_audio_path=source_audio,
                vocals_path=source_audio,
                accompaniment_path=None,
                stem_paths={"vocals": source_audio},
                workspace=workspace,
            )

            self.assertIsNotNone(result.note_candidates_dict)
            self.assertTrue(result.note_candidates_dict["builder_version"])
            melody_payload = result.note_candidates_dict["melody_candidates"]
            self.assertEqual(melody_payload["selected_notes"], [])
            self.assertEqual(melody_payload["raw_source"]["selected_notes"][0]["candidate_id"], "sem_selected_1")
            self.assertEqual(melody_payload["raw_source"]["notes"][0]["candidate_id"], "sem_raw_1")
            built_note = melody_payload["notes"][0]
            self.assertTrue(built_note["stable_id"])
            self.assertEqual(built_note["source_candidate_ids"][0], "sem_raw_1")
            self.assertEqual(built_note["source_contour_ids"], ["pc_00001"])
            self.assertIsNotNone(selector.last_kwargs)
            self.assertEqual(selector.last_kwargs["note_candidates"]["melody_candidates"]["selected_notes"], [])
            self.assertEqual(result.selected_melody_dict["selected_notes"][0]["source_candidate_id"], "sel_1")
            self.assertIsNotNone(result.quantized_notes_dict)
            self.assertEqual(result.quantized_notes_dict["notes"][0]["source_candidate_id"], "sel_1")

    def test_process_audio_canonicalizes_mp4_before_separation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_video = root / "input.mp4"
            source_video.write_bytes(b"video")
            separator_out = root / "separator"
            separator_out.mkdir(parents=True, exist_ok=True)
            stem_files = {
                "vocals": separator_out / "vocals.wav",
                "accompaniment": separator_out / "accompaniment.wav",
            }
            for path in stem_files.values():
                path.write_bytes(b"stem")

            audio_processor = _FakeNormalizingAudioProcessor()
            separator = _FakeSeparator(stem_files)
            pitch_pipeline = _CapturePitchPipeline()
            service = AudioAnalysisService(
                audio_processor=audio_processor,
                vocal_separator=separator,
                lyrics_recognizer=lambda _path: [],
                pitch_pipeline=pitch_pipeline,
                score_ir_builder=_FakeScoreIRBuilder(),
                midi_exporter=None,
                projects_root=root / "projects",
            )

            asyncio.run(service.process_audio(source_video, AudioAnalysisOptions(project_id="mp4_ingest_001")))
            workspace = ProjectWorkspace(project_id="mp4_ingest_001", projects_root=root / "projects")

            self.assertEqual(audio_processor.calls[0][0], str(workspace.input_dir / "source.mp4"))
            self.assertEqual(audio_processor.calls[0][1], str(workspace.canonical_audio_path))
            self.assertEqual(separator.calls[0][0][0], str(workspace.canonical_audio_path))
            self.assertTrue(workspace.canonical_audio_path.exists())

    def test_process_audio_creates_immutable_machine_revision_manifest_and_revision_exports(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"mix")
            separator_out = root / "separator"
            separator_out.mkdir(parents=True, exist_ok=True)
            stem_files = {
                "vocals": separator_out / "vocals.wav",
                "accompaniment": separator_out / "accompaniment.wav",
                "drums": separator_out / "drums.wav",
                "bass": separator_out / "bass.wav",
                "other": separator_out / "other.wav",
            }
            for path in stem_files.values():
                path.write_bytes(b"stem")

            service = AudioAnalysisService(
                audio_processor=_PassthroughAudioProcessor(),
                vocal_separator=_FakeSeparator(stem_files),
                lyrics_recognizer=lambda _path: [],
                pitch_pipeline=_CapturePitchPipeline(),
                score_ir_builder=_FakeScoreIRBuilder(),
                midi_exporter=None,
                projects_root=root / "projects",
            )

            first = asyncio.run(
                service.process_audio(source_audio, AudioAnalysisOptions(project_id="revision_manifest_001", job_id="job-a"))
            )
            second = asyncio.run(
                service.process_audio(source_audio, AudioAnalysisOptions(project_id="revision_manifest_001", job_id="job-b"))
            )

            self.assertNotEqual(first.score_revision["revision_id"], second.score_revision["revision_id"])
            self.assertEqual(first.score_revision["revision_number"], 1)
            self.assertEqual(second.score_revision["revision_number"], 2)
            self.assertTrue(Path(first.artifact_manifest_path).exists())
            self.assertTrue(Path(second.artifact_manifest_path).exists())
            self.assertNotEqual(first.artifact_manifest_path, second.artifact_manifest_path)
            self.assertIsNotNone(first.midi_path)
            self.assertIsNotNone(first.musicxml_path)
            self.assertIn(first.score_revision["revision_id"], first.midi_path)
            self.assertIn(first.score_revision["revision_id"], first.musicxml_path)

            manifest = json.loads(Path(first.artifact_manifest_path).read_text(encoding="utf-8"))
            artifact_types = {item["artifact_type"] for item in manifest["artifacts"]}
            self.assertEqual(manifest["score_revision"]["revision_type"], "machine")
            self.assertTrue(manifest["score_revision"]["immutable"])
            self.assertIn("f0_track", artifact_types)
            self.assertIn("pitch_contours", artifact_types)
            self.assertIn("note_candidates", artifact_types)
            self.assertIn("selected_melody", artifact_types)
            self.assertIn("rhythm_grid", artifact_types)
            self.assertIn("quantized_notes", artifact_types)
            self.assertIn("score_ir", artifact_types)
            self.assertIn("score_data", artifact_types)
            self.assertIn("midi", artifact_types)
            self.assertIn("musicxml", artifact_types)

    def test_perception_stage_routes_stems_to_pitch_request(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"mix")

            separator_out = root / "separator"
            separator_out.mkdir(parents=True, exist_ok=True)
            stem_files = {
                "vocals": separator_out / "vocals.wav",
                "accompaniment": separator_out / "accompaniment.wav",
                "drums": separator_out / "drums.wav",
                "bass": separator_out / "bass.wav",
                "other": separator_out / "other.wav",
            }
            for path in stem_files.values():
                path.write_bytes(b"stem")

            audio_processor = _PassthroughAudioProcessor()
            separator = _FakeSeparator(stem_files)
            pitch_pipeline = _CapturePitchPipeline()
            score_ir_builder = _FakeScoreIRBuilder()
            service = AudioAnalysisService(
                audio_processor=audio_processor,
                vocal_separator=separator,
                lyrics_recognizer=lambda _path: [],
                pitch_pipeline=pitch_pipeline,
                score_ir_builder=score_ir_builder,
                midi_exporter=None,
                projects_root=root / "projects",
            )

            workspace = ProjectWorkspace(project_id="analysis_routing_001", projects_root=root / "projects")
            workspace.ensure_structure()
            options = AudioAnalysisOptions(project_id="analysis_routing_001")

            canonical_audio = workspace.normalized_audio_path
            audio_processor.convert(str(source_audio), str(canonical_audio))
            perception = asyncio.run(service._run_perception_stage(source_audio, canonical_audio, workspace, options))

            self.assertIsNotNone(pitch_pipeline.last_request)
            self.assertEqual(separator.calls[0][0][0], str(canonical_audio))
            self.assertEqual(pitch_pipeline.last_request.lead_audio_path, str(workspace.vocals_path))
            self.assertEqual(pitch_pipeline.last_request.rhythm_audio_path, str(workspace.stem_path("drums")))
            self.assertEqual(pitch_pipeline.last_request.key_audio_path, str(workspace.stem_path("other")))
            self.assertEqual(pitch_pipeline.last_request.harmony_audio_path, str(workspace.stem_path("other")))
            self.assertEqual(pitch_pipeline.last_request.bass_audio_path, str(workspace.stem_path("bass")))
            self.assertEqual(perception.stem_paths["vocals"], workspace.vocals_path)
            self.assertEqual(perception.stem_paths["drums"], workspace.stem_path("drums"))
            self.assertEqual(perception.stem_paths["bass"], workspace.stem_path("bass"))
            self.assertIn("other", pitch_pipeline.last_request.source_stems)
            self.assertIsNone(perception.analysis_ir_dict)
            self.assertIsNotNone(perception.score_data_dict)
            self.assertIn("measures", perception.score_data_dict)
            self.assertIsNotNone(score_ir_builder.last_args)
            self.assertEqual(len(score_ir_builder.last_args), 2)
            self.assertNotIn("analysis_ir", score_ir_builder.last_kwargs)
            self.assertIn("quantized_notes_artifact", score_ir_builder.last_kwargs)
            self.assertEqual(perception.semantic_audio_dict["source_stems"]["bass"], str(workspace.stem_path("bass")))
            self.assertIsNotNone(perception.f0_track_dict)
            self.assertEqual(perception.f0_track_dict["backend"], "rmvpe")
            frame = perception.f0_track_dict["frames"][0]
            self.assertEqual(set(["time_sec", "f0_hz", "midi_float", "voiced", "confidence"]) - set(frame), set())
            self.assertEqual(frame["f0_hz"], 220.0)
            self.assertEqual(frame["midi_float"], 57.0)
            self.assertIsNotNone(perception.note_candidates_dict)
            self.assertIn("melody_candidates", perception.note_candidates_dict)
            self.assertTrue(perception.note_candidates_dict["builder_version"])
            contour_candidate = perception.note_candidates_dict["melody_candidates"]["notes"][0]
            self.assertTrue(contour_candidate["stable_id"])
            self.assertEqual(contour_candidate["source_contour_ids"], ["pc_00001"])
            self.assertIsNotNone(perception.pitch_contours_dict)
            self.assertGreaterEqual(perception.pitch_contours_dict["summary"]["contour_count"], 1)
            self.assertIsNotNone(perception.selected_melody_dict)
            self.assertIn("summary", perception.selected_melody_dict)
            self.assertEqual(perception.selected_melody_dict["summary"]["input_source"], "melody_candidates.notes")
            self.assertIsNotNone(perception.quantized_notes_dict)
            self.assertEqual(perception.quantized_notes_dict["quantizer_backend"], "dp_v1")
            self.assertEqual(len(perception.score_ir_dict["notes"]), len(perception.quantized_notes_dict["notes"]))
            self.assertEqual(perception.score_ir_dict["notes"][0]["source"], "quantized_notes")
            self.assertEqual(perception.score_ir_dict["meta"]["analysis_info"]["lead_note_source"], "quantized_notes")
            self.assertIsNotNone(perception.rhythm_grid_dict)
            self.assertEqual(perception.vocal_activity_dict["segments"][0]["state"], "vocal")

            alignment = service._empty_alignment_stage()
            persist_warnings = service._persist_artifacts(workspace, perception, alignment)
            self.assertEqual(persist_warnings, [])
            self.assertTrue(workspace.f0_track_path.exists())
            self.assertTrue(workspace.pitch_contours_path.exists())
            self.assertTrue(workspace.note_candidates_path.exists())
            self.assertTrue(workspace.selected_melody_path.exists())
            self.assertTrue(workspace.quantized_notes_path.exists())
            self.assertTrue(workspace.rhythm_grid_path.exists())
            self.assertTrue(workspace.vocal_activity_path.exists())

    def test_perception_stage_fails_when_pitch_pipeline_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"mix")
            workspace = ProjectWorkspace(project_id="missing_pitch_001", projects_root=root / "projects")
            workspace.ensure_structure()
            workspace.vocals_path.write_bytes(b"vocals")
            service = AudioAnalysisService(
                audio_processor=_FakeNormalizingAudioProcessor(),
                vocal_separator=_FakeSeparator({"vocals": workspace.vocals_path}),
                pitch_pipeline=None,
                score_ir_builder=_FakeScoreIRBuilder(),
                midi_exporter=None,
                projects_root=root / "projects",
            )
            service.pitch_pipeline = None
            service.melody_transcription_service.pitch_pipeline = None

            with self.assertRaisesRegex(RuntimeError, "pitch_pipeline_failed"):
                asyncio.run(service._run_perception_stage(source_audio, source_audio, workspace, AudioAnalysisOptions(project_id="missing_pitch_001")))

    def test_perception_stage_fails_when_pitch_pipeline_returns_no_notes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"mix")
            workspace = ProjectWorkspace(project_id="empty_pitch_001", projects_root=root / "projects")
            workspace.ensure_structure()
            workspace.vocals_path.write_bytes(b"vocals")
            service = AudioAnalysisService(
                audio_processor=_FakeNormalizingAudioProcessor(),
                vocal_separator=_FakeSeparator({"vocals": workspace.vocals_path}),
                pitch_pipeline=_EmptyPitchPipeline(),
                score_ir_builder=_FakeScoreIRBuilder(),
                midi_exporter=None,
                projects_root=root / "projects",
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "pitch_pipeline_failed:required F0Track is unavailable for note candidate build",
            ):
                asyncio.run(service._run_perception_stage(source_audio, source_audio, workspace, AudioAnalysisOptions(project_id="empty_pitch_001")))

    def test_perception_stage_uses_canonical_audio_for_required_stages(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_audio = root / "source.wav"
            source_audio.write_bytes(b"mix")

            audio_processor = _FakeNormalizingAudioProcessor()
            separator = _FakeSeparator({})
            pitch_pipeline = _CapturePitchPipeline()
            service = AudioAnalysisService(
                audio_processor=audio_processor,
                vocal_separator=separator,
                lyrics_recognizer=lambda _path: [],
                pitch_pipeline=pitch_pipeline,
                score_ir_builder=_FakeScoreIRBuilder(),
                midi_exporter=None,
                projects_root=root / "projects",
            )

            workspace = ProjectWorkspace(project_id="analysis_fallback_001", projects_root=root / "projects")
            workspace.ensure_structure()
            options = AudioAnalysisOptions(project_id="analysis_fallback_001")

            canonical_audio = workspace.normalized_audio_path
            audio_processor.convert(str(source_audio), str(canonical_audio))
            with self.assertRaisesRegex(RuntimeError, "vocal_separation_failed"):
                asyncio.run(service._run_perception_stage(source_audio, canonical_audio, workspace, options))

            self.assertEqual(separator.calls[0][0][0], str(canonical_audio))
            self.assertEqual(audio_processor.calls, [(str(source_audio), str(workspace.normalized_audio_path))])
            self.assertIsNone(pitch_pipeline.last_request)

    def test_export_stage_does_not_copy_raw_pitch_midi(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = ProjectWorkspace(project_id="raw_bypass_001", projects_root=root / "projects")
            workspace.ensure_structure()
            workspace.raw_pitch_midi_path.write_bytes(b"raw-midi-bypass")
            service = AudioAnalysisService(
                audio_processor=_PassthroughAudioProcessor(),
                vocal_separator=None,
                lyrics_recognizer=None,
                pitch_pipeline=None,
                analysis_inferencer=None,
                midi_exporter=MidiExporter(),
                projects_root=root / "projects",
            )
            score_ir = _FakeScoreIRBuilder().build()
            perception = type(
                "Perception",
                (),
                {
                    "score_data_dict": ScoreIRSerializer.to_score_data(score_ir),
                    "raw_pitch_midi_path": workspace.raw_pitch_midi_path,
                },
            )()

            midi_path, warnings = asyncio.run(service._run_export_stage(perception, None, workspace))

            self.assertEqual(midi_path, workspace.final_midi_path)
            self.assertEqual(warnings, [])
            self.assertNotEqual(workspace.final_midi_path.read_bytes(), b"raw-midi-bypass")

    def test_score_ir_build_service_uses_quantized_notes_as_primary_input(self) -> None:
        service = AudioAnalysisService(
            audio_processor=_PassthroughAudioProcessor(),
            vocal_separator=None,
            lyrics_recognizer=None,
            pitch_pipeline=None,
            analysis_inferencer=None,
            midi_exporter=None,
        )
        pitch_result = PitchAnalysisResult(
            version="test",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                rhythm_type="stable",
                duration_sec=1.0,
                time_signature="4/4",
            ),
            analysis_info={"lead_note_source": "quantized_notes"},
        )
        quantized_notes = {
            "quantizer_backend": "dp_v1",
            "notes": [
                {
                    "id": "qn_00001",
                    "source_candidate_id": "cand_00001",
                    "source_candidate_ids": ["cand_00001"],
                    "source_contour_ids": ["pc_00001"],
                    "source_f0_frame_range": {"start_frame_index": 0, "end_frame_index": 2},
                    "pitch": "C4",
                    "pitch_midi": 60,
                    "start_time_sec": 0.30,
                    "end_time_sec": 0.60,
                    "quantized_start_time_sec": 0.25,
                    "quantized_end_time_sec": 0.50,
                    "quantized_duration_sec": 0.25,
                    "measure_index": 0,
                    "beat_in_measure": 1.5,
                    "duration_beats": 0.5,
                    "confidence": 0.91,
                }
            ],
        }

        score_ir, score_data = service.score_build_service.build(
            pitch_result_obj=pitch_result,
            lyrics_segments=[],
            quantized_notes_dict=quantized_notes,
        )
        service._validate_score_ir_uses_quantized_notes(score_ir, quantized_notes_dict=quantized_notes)

        note = score_ir.notes[0]
        self.assertEqual(note.source, "quantized_notes")
        self.assertEqual(note.timing_origin, "performance_time_from_quantized_notes")
        self.assertAlmostEqual(note.start_time, 0.30)
        self.assertAlmostEqual(note.performance_start_time_sec, 0.30)
        self.assertEqual(note.source_contour_ids, ["pc_00001"])
        self.assertEqual(note.source_f0_frame_range["end_frame_index"], 2)
        self.assertEqual(score_data["measures"][0]["notes"][0]["quantized_note_id"], "qn_00001")


if __name__ == "__main__":
    unittest.main()
