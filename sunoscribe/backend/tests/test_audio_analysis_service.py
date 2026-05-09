from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.modules.pitch.types import F0Frame, F0Track, MetaInfo, PitchAnalysisResult, PitchPipelineRequest, RhythmGrid, SemanticAudioResult, VocalActivitySegment
from app.modules.score_ir import ScoreIR, ScoreMeta
from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisService
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
            measures=[],
            lead_notes=[],
            raw_notes=[],
            f0_track=F0Track(
                source_stem="vocals",
                input_audio_path=str(request.lead_audio_path),
                backend="rmvpe",
                frames=[F0Frame(time_sec=0.1, frequency_hz=220.0, confidence=0.9, voiced=True, pitch_midi=57.0)],
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
                rhythm_grid=RhythmGrid(source_stem="drums", input_audio_path="drums.wav"),
            ),
        )


class _FakeScoreIRBuilder:
    def __init__(self) -> None:
        self.last_args = None
        self.last_kwargs = None

    def build(self, *_args, **_kwargs):
        self.last_args = _args
        self.last_kwargs = _kwargs
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
            )
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
            self.assertIsNotNone(perception.analysis_ir_dict)
            self.assertIsNotNone(perception.score_data_dict)
            self.assertIn("measures", perception.score_data_dict)
            self.assertIsNotNone(score_ir_builder.last_args)
            self.assertEqual(len(score_ir_builder.last_args), 2)
            self.assertIn("analysis_ir", score_ir_builder.last_kwargs)
            self.assertIsNotNone(score_ir_builder.last_kwargs["analysis_ir"])
            self.assertEqual(perception.semantic_audio_dict["source_stems"]["bass"], str(workspace.stem_path("bass")))
            self.assertIsNotNone(perception.f0_track_dict)
            self.assertEqual(perception.f0_track_dict["backend"], "rmvpe")
            self.assertIsNotNone(perception.note_candidates_dict)
            self.assertIn("melody_candidates", perception.note_candidates_dict)
            self.assertIsNotNone(perception.rhythm_grid_dict)
            self.assertEqual(perception.vocal_activity_dict["segments"][0]["state"], "vocal")

            alignment = asyncio.run(service._run_alignment_stage(perception.score_ir_obj, options))
            persist_warnings = service._persist_artifacts(workspace, perception, alignment)
            self.assertEqual(persist_warnings, [])
            self.assertTrue(workspace.f0_track_path.exists())
            self.assertTrue(workspace.note_candidates_path.exists())
            self.assertTrue(workspace.rhythm_grid_path.exists())
            self.assertTrue(workspace.vocal_activity_path.exists())

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


if __name__ == "__main__":
    unittest.main()
