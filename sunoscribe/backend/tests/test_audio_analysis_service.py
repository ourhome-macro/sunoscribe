from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.modules.pitch.types import MetaInfo, PitchAnalysisResult, PitchPipelineRequest, SemanticAudioResult
from app.modules.score_ir import ScoreIR, ScoreMeta
from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisService
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
            semantic_audio=SemanticAudioResult(source_stems=dict(request.source_stems)),
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

            perception = asyncio.run(service._run_perception_stage(source_audio, workspace, options))

            self.assertIsNotNone(pitch_pipeline.last_request)
            self.assertEqual(separator.calls[0][0][0], str(source_audio))
            self.assertEqual(audio_processor.calls, [])
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

    def test_perception_stage_uses_normalized_audio_only_as_fallback(self) -> None:
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

            perception = asyncio.run(service._run_perception_stage(source_audio, workspace, options))

            self.assertEqual(separator.calls[0][0][0], str(source_audio))
            self.assertEqual(audio_processor.calls, [(str(source_audio), str(workspace.normalized_audio_path))])
            self.assertEqual(perception.normalized_audio_path, workspace.normalized_audio_path)
            self.assertEqual(pitch_pipeline.last_request.source_audio_path, str(source_audio))
            self.assertEqual(pitch_pipeline.last_request.lead_audio_path, str(workspace.normalized_audio_path))
            self.assertEqual(pitch_pipeline.last_request.rhythm_audio_path, str(workspace.normalized_audio_path))
            self.assertEqual(pitch_pipeline.last_request.key_audio_path, str(workspace.normalized_audio_path))


if __name__ == "__main__":
    unittest.main()
