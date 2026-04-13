from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, is_dataclass
import inspect
import json
import logging
from pathlib import Path
import shutil
from typing import Any

from app.modules.alignment import (
    AlignmentDraft,
    AlignmentLLMClient,
    AlignmentLLMParser,
    AlignmentLLMPayloadBuilder,
    AlignmentRefinePolicy,
    AlignmentRefineRequest,
    AlignmentRefineResponse,
    AlignmentRefineService,
    AlignmentValidator,
    InitialLyricsAligner,
    StubAlignmentLLMClient,
)
from app.modules.score_ir import AnalysisHints, ScoreIR, ScoreMeta
from app.modules.score_ir import ScoreIRBuilder

from app.services.workspace import ProjectWorkspace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioAnalysisOptions:
    project_id: str
    enable_vocal_separation: bool = True
    enable_llm_refine: bool = False
    include_refine_debug: bool = False


@dataclass(slots=True)
class AudioAnalysisResult:
    project_id: str
    source_audio_path: str | None
    normalized_audio_path: str | None
    vocals_path: str | None
    accompaniment_path: str | None
    lyrics_segments: list[dict]
    pitch_result: dict | None
    score_ir: dict | None
    baseline_alignment: dict
    baseline_validator_warnings: list[str]
    refined_alignment: dict | None
    final_alignment: dict
    alignment_source: str
    alignment_accepted: bool
    refine_warnings: list[str]
    validator_warnings_before: list[str]
    validator_warnings_after: list[str]
    refine_debug: dict | None
    midi_path: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _PerceptionStageResult:
    source_audio_path: Path
    normalized_audio_path: Path | None
    vocals_path: Path | None
    accompaniment_path: Path | None
    lyrics_segments: list[dict]
    whisper_raw: dict[str, Any] | None
    pitch_result_obj: Any | None
    pitch_result_dict: dict | None
    score_ir_obj: ScoreIR
    score_ir_dict: dict
    raw_pitch_midi_path: Path | None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _AlignmentStageResult:
    baseline_draft: AlignmentDraft
    baseline_validator_warnings: list[str]
    refine_response: AlignmentRefineResponse | None
    final_draft: AlignmentDraft
    alignment_source: str
    alignment_accepted: bool
    refine_warnings: list[str]
    validator_warnings_before: list[str]
    validator_warnings_after: list[str]
    refine_debug: dict | None
    warnings: list[str] = field(default_factory=list)


class AudioAnalysisService:
    def __init__(
        self,
        *,
        audio_processor: Any | None = None,
        vocal_separator: Any | None = None,
        lyrics_recognizer: Any | None = None,
        pitch_pipeline: Any | None = None,
        score_ir_builder: ScoreIRBuilder | None = None,
        midi_exporter: Any | None = None,
        initial_aligner: InitialLyricsAligner | None = None,
        alignment_validator: AlignmentValidator | None = None,
        alignment_refine_service: AlignmentRefineService | None = None,
        alignment_payload_builder: AlignmentLLMPayloadBuilder | None = None,
        alignment_parser: AlignmentLLMParser | None = None,
        alignment_llm_client: AlignmentLLMClient | None = None,
        alignment_policy: AlignmentRefinePolicy | None = None,
        include_refine_debug: bool = False,
        projects_root: Path | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.logger = logger_ or logger
        self.projects_root = projects_root or Path("data/projects")
        self.include_refine_debug = bool(include_refine_debug)

        self.audio_processor = audio_processor if audio_processor is not None else self._try_make_audio_processor()
        self.vocal_separator = vocal_separator
        self.lyrics_recognizer = lyrics_recognizer if lyrics_recognizer is not None else self._try_make_lyrics_recognizer()
        self.pitch_pipeline = pitch_pipeline if pitch_pipeline is not None else self._try_make_pitch_pipeline()
        self.score_ir_builder = score_ir_builder or ScoreIRBuilder()
        self.midi_exporter = midi_exporter if midi_exporter is not None else self._try_make_midi_exporter()

        self.initial_aligner = initial_aligner or InitialLyricsAligner()
        self.alignment_validator = alignment_validator or AlignmentValidator()

        self.alignment_refine_service = alignment_refine_service or AlignmentRefineService(
            validator=self.alignment_validator,
            payload_builder=alignment_payload_builder or AlignmentLLMPayloadBuilder(),
            parser=alignment_parser or AlignmentLLMParser(),
            llm_client=alignment_llm_client or StubAlignmentLLMClient(response={"alignments": []}),
            policy=alignment_policy,
            include_debug=self.include_refine_debug,
        )

    async def process_audio(self, input_audio_path: str | Path, options: AudioAnalysisOptions) -> AudioAnalysisResult:
        workspace = ProjectWorkspace(project_id=options.project_id, projects_root=self.projects_root)
        workspace.ensure_structure()

        source_copy_path = workspace.save_input_copy(input_audio_path)

        perception = await self._run_perception_stage(source_copy_path, workspace, options)
        alignment = await self._run_alignment_stage(perception.score_ir_obj, options)
        final_midi_path, export_warnings = await self._run_export_stage(perception, alignment, workspace)

        persist_warnings = self._persist_artifacts(workspace, perception, alignment)

        all_warnings = self._merge_warnings(
            perception.warnings,
            alignment.warnings,
            export_warnings,
            persist_warnings,
        )

        result = AudioAnalysisResult(
            project_id=options.project_id,
            source_audio_path=str(perception.source_audio_path),
            normalized_audio_path=str(perception.normalized_audio_path) if perception.normalized_audio_path else None,
            vocals_path=str(perception.vocals_path) if perception.vocals_path else None,
            accompaniment_path=str(perception.accompaniment_path) if perception.accompaniment_path else None,
            lyrics_segments=perception.lyrics_segments,
            pitch_result=perception.pitch_result_dict,
            score_ir=perception.score_ir_dict,
            baseline_alignment=self._serialize(perception_obj=alignment.baseline_draft),
            baseline_validator_warnings=alignment.baseline_validator_warnings,
            refined_alignment=self._serialize(perception_obj=alignment.refine_response.draft)
            if alignment.refine_response is not None
            else None,
            final_alignment=self._serialize(perception_obj=alignment.final_draft),
            alignment_source=alignment.alignment_source,
            alignment_accepted=alignment.alignment_accepted,
            refine_warnings=alignment.refine_warnings,
            validator_warnings_before=alignment.validator_warnings_before,
            validator_warnings_after=alignment.validator_warnings_after,
            refine_debug=alignment.refine_debug,
            midi_path=str(final_midi_path) if final_midi_path else None,
            warnings=all_warnings,
        )
        return result

    async def _run_perception_stage(
        self,
        source_audio_path: Path,
        workspace: ProjectWorkspace,
        options: AudioAnalysisOptions,
    ) -> _PerceptionStageResult:
        warnings: list[str] = []
        normalized_audio_path: Path | None = None
        vocals_path: Path | None = None
        accompaniment_path: Path | None = None
        raw_pitch_midi_path: Path | None = None

        current_audio_path = source_audio_path

        if self.audio_processor is None:
            warnings.append("audio_processor_missing: skip normalize")
        else:
            try:
                # TODO: 按真实接口调整
                normalized_str = await asyncio.to_thread(
                    self.audio_processor.convert,
                    str(source_audio_path),
                    str(workspace.normalized_audio_path),
                )
                normalized_audio_path = Path(normalized_str)
                current_audio_path = normalized_audio_path
            except Exception as exc:
                warnings.append(f"audio_normalize_failed:{self._short_exception(exc)}")

        if options.enable_vocal_separation:
            if self.vocal_separator is None:
                warnings.append("vocal_separator_missing: skip separation")
            else:
                try:
                    # TODO: 按真实接口调整
                    sep = await asyncio.to_thread(
                        self.vocal_separator.separate,
                        str(current_audio_path),
                        str(workspace.separation_dir),
                        "separated",
                    )
                    vocals_raw = getattr(sep, "vocal_path", None) or getattr(sep, "vocals_path", None)
                    acc_raw = getattr(sep, "accompaniment_path", None)

                    if vocals_raw:
                        vocals_path = Path(vocals_raw)
                        shutil.copyfile(vocals_path, workspace.vocals_path)
                        vocals_path = workspace.vocals_path

                    if acc_raw:
                        accompaniment_path = Path(acc_raw)
                        shutil.copyfile(accompaniment_path, workspace.accompaniment_path)
                        accompaniment_path = workspace.accompaniment_path
                except Exception as exc:
                    warnings.append(f"vocal_separation_failed:{self._short_exception(exc)}")

        lyrics_audio_path = vocals_path or current_audio_path
        lyrics_segments: list[dict] = []
        whisper_raw: dict[str, Any] | None = None

        if self.lyrics_recognizer is None:
            warnings.append("lyrics_recognizer_missing: skip lyrics")
        else:
            try:
                lyrics_output = await self._invoke_lyrics_recognizer(str(lyrics_audio_path))
                # TODO: 按真实接口调整
                if isinstance(lyrics_output, dict):
                    whisper_raw = lyrics_output
                    maybe_segments = lyrics_output.get("segments")
                    if isinstance(maybe_segments, list):
                        lyrics_segments = [seg for seg in maybe_segments if isinstance(seg, dict)]
                elif isinstance(lyrics_output, list):
                    lyrics_segments = [seg for seg in lyrics_output if isinstance(seg, dict)]
                else:
                    warnings.append("lyrics_output_invalid_type")
            except Exception as exc:
                warnings.append(f"lyrics_recognition_failed:{self._short_exception(exc)}")

        pitch_result_obj: Any | None = None
        pitch_result_dict: dict | None = None

        pitch_audio_path = vocals_path or current_audio_path
        if self.pitch_pipeline is None:
            warnings.append("pitch_pipeline_missing: skip pitch")
        else:
            try:
                # TODO: 按真实接口调整
                pitch_result_obj = await asyncio.to_thread(self.pitch_pipeline.run, str(pitch_audio_path))
                serialized = self._serialize(perception_obj=pitch_result_obj)
                pitch_result_dict = serialized if isinstance(serialized, dict) else {"value": serialized}

                if hasattr(self.pitch_pipeline, "export_midi"):
                    try:
                        await asyncio.to_thread(
                            self.pitch_pipeline.export_midi,
                            pitch_result_obj,
                            str(workspace.raw_pitch_midi_path),
                        )
                        raw_pitch_midi_path = workspace.raw_pitch_midi_path
                    except Exception as exc:
                        warnings.append(f"raw_midi_export_failed:{self._short_exception(exc)}")
            except Exception as exc:
                warnings.append(f"pitch_pipeline_failed:{self._short_exception(exc)}")

        score_ir_obj: ScoreIR | None = None
        if self.score_ir_builder is None:
            warnings.append("score_ir_builder_missing: use empty score_ir")
        elif pitch_result_obj is None:
            warnings.append("score_ir_skipped_no_pitch_result")
        else:
            try:
                # TODO: 按真实接口调整
                score_ir_obj = await asyncio.to_thread(self.score_ir_builder.build, pitch_result_obj, lyrics_segments)
            except Exception as exc:
                warnings.append(f"score_ir_build_failed:{self._short_exception(exc)}")

        if score_ir_obj is None:
            score_ir_obj = self._build_empty_score_ir(warnings)

        score_ir_serialized = self._serialize(perception_obj=score_ir_obj)
        score_ir_dict = score_ir_serialized if isinstance(score_ir_serialized, dict) else {"value": score_ir_serialized}

        return _PerceptionStageResult(
            source_audio_path=source_audio_path,
            normalized_audio_path=normalized_audio_path,
            vocals_path=vocals_path,
            accompaniment_path=accompaniment_path,
            lyrics_segments=lyrics_segments,
            whisper_raw=whisper_raw,
            pitch_result_obj=pitch_result_obj,
            pitch_result_dict=pitch_result_dict,
            score_ir_obj=score_ir_obj,
            score_ir_dict=score_ir_dict,
            raw_pitch_midi_path=raw_pitch_midi_path,
            warnings=warnings,
        )

    async def _run_alignment_stage(
        self,
        score_ir: ScoreIR,
        options: AudioAnalysisOptions,
    ) -> _AlignmentStageResult:
        warnings: list[str] = []

        try:
            baseline_draft = await asyncio.to_thread(self.initial_aligner.align, score_ir)
        except Exception as exc:
            warnings.append(f"baseline_alignment_failed:{self._short_exception(exc)}")
            baseline_draft = AlignmentDraft(method="baseline_failed", warnings=["baseline_alignment_failed"])

        try:
            baseline_validator_warnings = await asyncio.to_thread(
                self.alignment_validator.validate,
                score_ir,
                baseline_draft,
            )
        except Exception as exc:
            warnings.append(f"baseline_validation_failed:{self._short_exception(exc)}")
            baseline_validator_warnings = ["baseline_validation_failed"]

        if (not options.enable_llm_refine) or (self.alignment_refine_service is None):
            if options.enable_llm_refine and self.alignment_refine_service is None:
                warnings.append("alignment_refine_service_missing: fallback_to_baseline")
            return _AlignmentStageResult(
                baseline_draft=baseline_draft,
                baseline_validator_warnings=baseline_validator_warnings,
                refine_response=None,
                final_draft=baseline_draft,
                alignment_source="baseline",
                alignment_accepted=True,
                refine_warnings=[],
                validator_warnings_before=baseline_validator_warnings,
                validator_warnings_after=baseline_validator_warnings,
                refine_debug=None,
                warnings=warnings,
            )

        refine_include_debug = bool(options.include_refine_debug or self.include_refine_debug)
        if hasattr(self.alignment_refine_service, "include_debug"):
            try:
                self.alignment_refine_service.include_debug = refine_include_debug
            except Exception:
                warnings.append("alignment_refine_debug_toggle_failed")

        try:
            refine_request = AlignmentRefineRequest(
                score_ir=score_ir,
                draft=baseline_draft,
                use_validator_warnings=True,
                allow_fallback_to_original=True,
                metadata={"project_id": options.project_id},
            )
            refine_response = await asyncio.to_thread(self.alignment_refine_service.refine, refine_request)
        except Exception as exc:
            warnings.append(f"alignment_refine_failed:{self._short_exception(exc)}")
            return _AlignmentStageResult(
                baseline_draft=baseline_draft,
                baseline_validator_warnings=baseline_validator_warnings,
                refine_response=None,
                final_draft=baseline_draft,
                alignment_source="baseline",
                alignment_accepted=False,
                refine_warnings=["alignment_refine_failed"],
                validator_warnings_before=baseline_validator_warnings,
                validator_warnings_after=baseline_validator_warnings,
                refine_debug=None,
                warnings=warnings,
            )

        refine_debug = self._serialize(perception_obj=refine_response.debug) if refine_response.debug else None
        if refine_debug is not None and not isinstance(refine_debug, dict):
            refine_debug = {"value": refine_debug}

        return _AlignmentStageResult(
            baseline_draft=baseline_draft,
            baseline_validator_warnings=baseline_validator_warnings,
            refine_response=refine_response,
            final_draft=refine_response.draft,
            alignment_source=refine_response.source,
            alignment_accepted=refine_response.accepted,
            refine_warnings=list(refine_response.warnings),
            validator_warnings_before=list(refine_response.validator_warnings_before),
            validator_warnings_after=list(refine_response.validator_warnings_after),
            refine_debug=refine_debug,
            warnings=warnings,
        )

    async def _run_export_stage(
        self,
        perception: _PerceptionStageResult,
        alignment: _AlignmentStageResult,
        workspace: ProjectWorkspace,
    ) -> tuple[Path | None, list[str]]:
        warnings: list[str] = []

        if self.midi_exporter is not None and perception.pitch_result_obj is not None:
            try:
                # TODO: 按真实接口调整（目前用 pitch 结果导出，后续可纳入 alignment）
                measures = getattr(perception.pitch_result_obj, "measures", None)
                bpm = getattr(getattr(perception.pitch_result_obj, "meta", None), "bpm", None)
                if measures is not None and bpm is not None:
                    await asyncio.to_thread(
                        self.midi_exporter.export_from_measures,
                        measures,
                        float(bpm),
                        str(workspace.final_midi_path),
                    )
                    return workspace.final_midi_path, warnings
            except Exception as exc:
                warnings.append(f"final_midi_export_failed:{self._short_exception(exc)}")

        if perception.raw_pitch_midi_path and perception.raw_pitch_midi_path.exists():
            try:
                shutil.copyfile(perception.raw_pitch_midi_path, workspace.final_midi_path)
                return workspace.final_midi_path, warnings
            except Exception as exc:
                warnings.append(f"final_midi_copy_failed:{self._short_exception(exc)}")

        warnings.append("midi_not_generated")
        return None, warnings

    def _persist_artifacts(
        self,
        workspace: ProjectWorkspace,
        perception: _PerceptionStageResult,
        alignment: _AlignmentStageResult,
    ) -> list[str]:
        warnings: list[str] = []

        try:
            self._write_json(workspace.lyrics_segments_path, perception.lyrics_segments)
            if perception.whisper_raw is not None:
                self._write_json(workspace.whisper_raw_path, perception.whisper_raw)

            self._write_json(workspace.pitch_result_path, perception.pitch_result_dict)
            self._write_json(workspace.score_ir_path, perception.score_ir_dict)

            self._write_json(workspace.baseline_alignment_path, self._serialize(perception_obj=alignment.baseline_draft))
            self._write_json(workspace.baseline_validator_warnings_path, alignment.baseline_validator_warnings)

            if alignment.refine_response is not None:
                self._write_json(workspace.refine_response_path, self._serialize(perception_obj=alignment.refine_response))

            self._write_json(workspace.final_alignment_path, self._serialize(perception_obj=alignment.final_draft))

            if alignment.refine_debug is not None:
                self._write_json(workspace.refine_debug_path, alignment.refine_debug)

        except Exception as exc:
            warnings.append(f"persist_artifacts_failed:{self._short_exception(exc)}")

        return warnings

    async def _invoke_lyrics_recognizer(self, audio_path: str) -> Any:
        recognizer = self.lyrics_recognizer
        if recognizer is None:
            return []

        if hasattr(recognizer, "recognize"):
            fn = recognizer.recognize
        else:
            fn = recognizer

        if inspect.iscoroutinefunction(fn):
            return await fn(audio_path)

        result = fn(audio_path)
        if inspect.isawaitable(result):
            return await result
        return result

    def _build_empty_score_ir(self, warnings: list[str]) -> ScoreIR:
        return ScoreIR(
            meta=ScoreMeta(
                source_version="orchestration_stub",
                bpm=0.0,
                bpm_confidence=0.0,
                key="",
                key_confidence=0.0,
                duration_sec=0.0,
                time_signature="4/4",
                rhythm_type="unknown",
                total_measures=0,
                has_anacrusis=False,
                analysis_info={"fallback": True},
            ),
            analysis_hints=AnalysisHints(
                downbeat_confidence=None,
                rhythm_stability=None,
                has_accompaniment=None,
                detector=None,
                beat_backend=None,
                key_backend=None,
                quantize_mode=None,
            ),
            warnings=self._merge_warnings(warnings, ["score_ir_is_empty_fallback"]),
        )

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._serialize(perception_obj=data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _serialize(self, perception_obj: Any) -> Any:
        if perception_obj is None:
            return None

        if isinstance(perception_obj, (str, int, float, bool)):
            return perception_obj

        if isinstance(perception_obj, Path):
            return str(perception_obj)

        if isinstance(perception_obj, list):
            return [self._serialize(item) for item in perception_obj]

        if isinstance(perception_obj, dict):
            return {str(k): self._serialize(v) for k, v in perception_obj.items()}

        to_dict = getattr(perception_obj, "to_dict", None)
        if callable(to_dict):
            try:
                return self._serialize(to_dict())
            except Exception:
                pass

        if is_dataclass(perception_obj):
            return self._serialize(asdict(perception_obj))

        return str(perception_obj)

    def _merge_warnings(self, *chunks: list[str] | None) -> list[str]:
        merged: list[str] = []
        for chunk in chunks:
            for item in chunk or []:
                text = str(item).strip()
                if text and text not in merged:
                    merged.append(text)
        return merged

    def _short_exception(self, exc: Exception) -> str:
        msg = str(exc).strip()
        if not msg:
            return exc.__class__.__name__
        return msg[:240]

    def _try_make_audio_processor(self) -> Any | None:
        try:
            from app.modules.audio.processor import AudioProcessor

            return AudioProcessor()
        except Exception as exc:
            self.logger.warning("AudioProcessor unavailable: %s", self._short_exception(exc))
            return None

    def _try_make_lyrics_recognizer(self) -> Any | None:
        try:
            from app.modules.lyrics import recognize_lyrics

            return recognize_lyrics
        except Exception as exc:
            self.logger.warning("Lyrics recognizer unavailable: %s", self._short_exception(exc))
            return None

    def _try_make_pitch_pipeline(self) -> Any | None:
        try:
            from app.modules.pitch import PitchPipeline

            return PitchPipeline()
        except Exception as exc:
            self.logger.warning("PitchPipeline unavailable: %s", self._short_exception(exc))
            return None

    def _try_make_midi_exporter(self) -> Any | None:
        try:
            from app.modules.pitch import MidiExporter

            return MidiExporter()
        except Exception as exc:
            self.logger.warning("MidiExporter unavailable: %s", self._short_exception(exc))
            return None
