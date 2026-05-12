from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, is_dataclass
import inspect
import json
import logging
from pathlib import Path
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
from app.modules.analysis_ir import AnalysisIR, BaselineAnalysisInferencer
from app.modules.score_ir import AnalysisHints, ScoreIR, ScoreIRBuilder, ScoreIRSerializer, ScoreMeta

from app.services.media_ingest_service import MediaIngestService
from app.services.melody_transcription_service import MelodyTranscriptionService
from app.services.rhythm_quantization_service import RhythmQuantizationService
from app.services.score_build_service import ScoreBuildService
from app.services.stem_service import StemService
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
    analysis_ir: dict | None
    score_data: dict | None
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
    stem_paths: dict[str, str] = field(default_factory=dict)
    f0_track: dict | None = None
    pitch_contours: dict | None = None
    note_candidates: dict | None = None
    selected_melody: dict | None = None
    quantized_notes: dict | None = None
    rhythm_grid: dict | None = None
    vocal_activity: dict | None = None
    semantic_audio: dict | None = None
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
    analysis_ir_obj: AnalysisIR | None
    analysis_ir_dict: dict | None
    score_data_dict: dict | None
    score_ir_obj: ScoreIR
    score_ir_dict: dict
    raw_pitch_midi_path: Path | None
    stem_paths: dict[str, Path] = field(default_factory=dict)
    f0_track_dict: dict | None = None
    pitch_contours_dict: dict | None = None
    note_candidates_dict: dict | None = None
    selected_melody_dict: dict | None = None
    quantized_notes_dict: dict | None = None
    rhythm_grid_dict: dict | None = None
    vocal_activity_dict: dict | None = None
    semantic_audio_dict: dict | None = None
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
        analysis_inferencer: Any | None = None,
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
        self.vocal_separator = vocal_separator if vocal_separator is not None else self._try_make_vocal_separator()
        self.lyrics_recognizer = lyrics_recognizer if lyrics_recognizer is not None else self._try_make_lyrics_recognizer()
        self.pitch_pipeline = pitch_pipeline if pitch_pipeline is not None else self._try_make_pitch_pipeline()
        self.analysis_inferencer = (
            analysis_inferencer if analysis_inferencer is not None else self._try_make_analysis_inferencer()
        )
        self.score_ir_builder = score_ir_builder or ScoreIRBuilder()
        self.midi_exporter = midi_exporter if midi_exporter is not None else self._try_make_midi_exporter()
        self.media_ingest_service = MediaIngestService(self.audio_processor) if self.audio_processor is not None else None
        self.stem_service = StemService(self.vocal_separator)
        self.melody_transcription_service = MelodyTranscriptionService(
            pitch_pipeline=self.pitch_pipeline,
            serializer=self._serialize,
            pitch_request_builder=self._build_pitch_pipeline_request,
            short_exception=self._short_exception,
        )
        self.rhythm_quantization_service = RhythmQuantizationService()
        self.score_build_service = ScoreBuildService(
            score_ir_builder=self.score_ir_builder,
            invoke_builder=self._invoke_score_ir_builder,
        )

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
        canonical_audio_path = await self._run_media_ingest_stage(source_copy_path, workspace)

        perception = await self._run_perception_stage(source_copy_path, canonical_audio_path, workspace, options)
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
            analysis_ir=perception.analysis_ir_dict,
            score_data=perception.score_data_dict,
            semantic_audio=perception.semantic_audio_dict,
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
            stem_paths={name: str(path) for name, path in perception.stem_paths.items()},
            f0_track=perception.f0_track_dict,
            pitch_contours=perception.pitch_contours_dict,
            note_candidates=perception.note_candidates_dict,
            selected_melody=perception.selected_melody_dict,
            quantized_notes=perception.quantized_notes_dict,
            rhythm_grid=perception.rhythm_grid_dict,
            vocal_activity=perception.vocal_activity_dict,
            warnings=all_warnings,
        )
        return result

    async def _run_media_ingest_stage(self, source_media_path: Path, workspace: ProjectWorkspace) -> Path:
        if self.media_ingest_service is None:
            raise RuntimeError("required media ingest stage is unavailable")
        ingest_result = await asyncio.to_thread(
            self.media_ingest_service.ingest,
            source_media_path,
            workspace.canonical_audio_path,
        )
        return ingest_result.canonical_audio_path

    async def _run_perception_stage(
        self,
        source_audio_path: Path,
        canonical_audio_path: Path | None,
        workspace: ProjectWorkspace,
        options: AudioAnalysisOptions,
    ) -> _PerceptionStageResult:
        warnings: list[str] = []
        normalized_audio_path: Path | None = canonical_audio_path
        vocals_path: Path | None = None
        accompaniment_path: Path | None = None
        raw_pitch_midi_path: Path | None = None
        stem_paths: dict[str, Path] = {}
        f0_track_dict: dict | None = None
        pitch_contours_dict: dict | None = None
        note_candidates_dict: dict | None = None
        selected_melody_dict: dict | None = None
        quantized_notes_dict: dict | None = None
        rhythm_grid_dict: dict | None = None
        vocal_activity_dict: dict | None = None
        semantic_audio_dict: dict | None = None

        fallback_audio_path = canonical_audio_path or source_audio_path

        if options.enable_vocal_separation:
            try:
                stem_result = await asyncio.to_thread(self.stem_service.separate, fallback_audio_path, workspace)
                stem_paths = stem_result.stem_paths
                vocals_path = stem_result.vocals_path
                accompaniment_path = stem_result.accompaniment_path
                warnings.extend(stem_result.warnings)
                if vocals_path is None:
                    raise RuntimeError("required vocal separation did not produce a vocals stem")
            except Exception as exc:
                message = f"vocal_separation_failed:{self._short_exception(exc)}"
                warnings.append(message)
                raise RuntimeError(message) from exc

        lyrics_audio_path = vocals_path or fallback_audio_path
        lyrics_segments: list[dict] = []
        whisper_raw: dict[str, Any] | None = None

        if self.lyrics_recognizer is None:
            warnings.append("lyrics_recognizer_missing: skip lyrics")
        else:
            try:
                lyrics_output = await self._invoke_lyrics_recognizer(str(lyrics_audio_path))
                # TODO: 鎸夌湡瀹炴帴鍙ｈ皟鏁?
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
        analysis_ir_obj: AnalysisIR | None = None
        analysis_ir_dict: dict | None = None
        score_data_dict: dict | None = None

        try:
            transcription = await asyncio.to_thread(
                self.melody_transcription_service.transcribe,
                source_audio_path=source_audio_path,
                canonical_audio_path=fallback_audio_path,
                vocals_path=vocals_path,
                accompaniment_path=accompaniment_path,
                stem_paths=stem_paths,
                workspace=workspace,
            )
            pitch_result_obj = transcription.pitch_result_obj
            pitch_result_dict = transcription.pitch_result_dict
            semantic_audio_dict = transcription.semantic_audio_dict
            f0_track_dict = transcription.f0_track_dict
            pitch_contours_dict = transcription.pitch_contours_dict
            vocal_activity_dict = transcription.vocal_activity_dict
            note_candidates_dict = transcription.note_candidates_dict
            selected_melody_dict = transcription.selected_melody_dict
            quantized_notes_dict = transcription.quantized_notes_dict
            raw_pitch_midi_path = transcription.raw_pitch_midi_path
            warnings.extend(transcription.warnings)
            rhythm_grid_dict = self.rhythm_quantization_service.build_rhythm_grid_payload(semantic_audio_dict)
        except Exception as exc:
            warnings.append(f"pitch_pipeline_failed:{self._short_exception(exc)}")

        if self.analysis_inferencer is None:
            warnings.append("analysis_inferencer_missing: skip analysis_ir")
        elif pitch_result_obj is None:
            warnings.append("analysis_ir_skipped_no_pitch_result")
        else:
            try:
                analysis_ir_obj = await asyncio.to_thread(
                    self.analysis_inferencer.infer,
                    pitch_result_obj,
                    lyrics_segments,
                )
                serialized = self._serialize(perception_obj=analysis_ir_obj)
                analysis_ir_dict = serialized if isinstance(serialized, dict) else {"value": serialized}
            except Exception as exc:
                warnings.append(f"analysis_ir_failed:{self._short_exception(exc)}")

        score_ir_obj: ScoreIR | None = None
        if self.score_build_service.score_ir_builder is None:
            warnings.append("score_ir_builder_missing: use empty score_ir")
        elif pitch_result_obj is None:
            warnings.append("score_ir_skipped_no_pitch_result")
        else:
            try:
                score_ir_obj, score_data_dict = await asyncio.to_thread(
                    self.score_build_service.build,
                    pitch_result_obj=pitch_result_obj,
                    lyrics_segments=lyrics_segments,
                    analysis_ir_obj=analysis_ir_obj,
                )
            except Exception as exc:
                warnings.append(f"score_ir_build_failed:{self._short_exception(exc)}")

        if score_ir_obj is None:
            score_ir_obj = self._build_empty_score_ir(warnings)

        if score_data_dict is None:
            try:
                score_data_dict = ScoreIRSerializer.to_score_data(score_ir_obj)
            except Exception as exc:
                warnings.append(f"score_data_build_failed:{self._short_exception(exc)}")

        score_ir_serialized = self._serialize(perception_obj=score_ir_obj)
        score_ir_dict = score_ir_serialized if isinstance(score_ir_serialized, dict) else {"value": score_ir_serialized}
        score_ir_dict = self._annotate_score_ir_notes(
            score_ir_dict,
            quantized_notes_dict=quantized_notes_dict,
        )
        if score_data_dict is not None:
            try:
                from app.modules.score_ir import ScoreIRSerializer

                score_data_dict = ScoreIRSerializer.to_score_data_dict(score_ir_dict)
            except Exception as exc:
                warnings.append(f"score_data_trace_annotation_failed:{self._short_exception(exc)}")

        return _PerceptionStageResult(
            source_audio_path=source_audio_path,
            normalized_audio_path=normalized_audio_path,
            vocals_path=vocals_path,
            accompaniment_path=accompaniment_path,
            lyrics_segments=lyrics_segments,
            whisper_raw=whisper_raw,
            pitch_result_obj=pitch_result_obj,
            pitch_result_dict=pitch_result_dict,
            analysis_ir_obj=analysis_ir_obj,
            analysis_ir_dict=analysis_ir_dict,
            score_data_dict=score_data_dict,
            semantic_audio_dict=semantic_audio_dict,
            score_ir_obj=score_ir_obj,
            score_ir_dict=score_ir_dict,
            raw_pitch_midi_path=raw_pitch_midi_path,
            stem_paths=stem_paths,
            f0_track_dict=f0_track_dict,
            pitch_contours_dict=pitch_contours_dict,
            note_candidates_dict=note_candidates_dict,
            selected_melody_dict=selected_melody_dict,
            quantized_notes_dict=quantized_notes_dict,
            rhythm_grid_dict=rhythm_grid_dict,
            vocal_activity_dict=vocal_activity_dict,
            warnings=warnings,
        )

    def _annotate_score_ir_notes(self, score_ir_dict: dict, *, quantized_notes_dict: dict | None) -> dict:
        if not isinstance(score_ir_dict, dict) or not isinstance(quantized_notes_dict, dict):
            return score_ir_dict
        try:
            from app.modules.pitch.quantized_notes_artifact import score_ir_note_annotations

            annotations = score_ir_note_annotations(quantized_notes_dict)
        except Exception:
            return score_ir_dict
        if not annotations:
            return score_ir_dict
        annotated = dict(score_ir_dict)
        notes = []
        for idx, note in enumerate(score_ir_dict.get("notes") or [], start=1):
            if not isinstance(note, dict):
                notes.append(note)
                continue
            updated = dict(note)
            candidates = [
                str(note.get("source_candidate_id") or ""),
                str(note.get("id") or ""),
                f"cand_{idx:05d}",
            ]
            annotation = next((annotations.get(candidate) for candidate in candidates if candidate in annotations), None)
            if annotation:
                existing_reasons = list(updated.get("reason_codes") or [])
                annotation_reasons = list(annotation.get("reason_codes") or [])
                merged_reasons = self._merge_warnings(existing_reasons, annotation_reasons)
                updated.update(
                    {
                        key: value
                        for key, value in annotation.items()
                        if value is not None and key not in {"reason_codes", "uncertain"}
                    }
                )
                updated["reason_codes"] = merged_reasons
                updated["uncertain"] = bool(updated.get("uncertain")) or bool(annotation.get("uncertain")) or bool(merged_reasons)
            notes.append(updated)
        annotated["notes"] = notes
        return annotated

    def _build_pitch_pipeline_request(
        self,
        *,
        source_audio_path: Path,
        fallback_audio_path: Path | None = None,
        vocals_path: Path | None,
        accompaniment_path: Path | None,
        stem_paths: dict[str, Path],
    ) -> Any:
        fallback_path = fallback_audio_path or source_audio_path
        try:
            from app.modules.pitch import PitchPipelineRequest
        except Exception:
            return str(vocals_path or fallback_path)

        stem_map = {name: str(path) for name, path in stem_paths.items()}
        rhythm_path = stem_paths.get("drums") or accompaniment_path or fallback_path
        key_path = stem_paths.get("other") or accompaniment_path or fallback_path
        harmony_path = stem_paths.get("other") or accompaniment_path
        bass_path = stem_paths.get("bass") or accompaniment_path
        return PitchPipelineRequest(
            lead_audio_path=str(vocals_path or fallback_path),
            source_audio_path=str(source_audio_path),
            rhythm_audio_path=str(rhythm_path),
            key_audio_path=str(key_path),
            harmony_audio_path=str(harmony_path) if harmony_path else None,
            bass_audio_path=str(bass_path) if bass_path else None,
            source_stems=stem_map,
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
        score_data = perception.score_data_dict if isinstance(perception.score_data_dict, dict) else None
        measures = score_data.get("measures") if isinstance(score_data, dict) else None
        if self.midi_exporter is not None and isinstance(measures, list) and measures:
            try:
                bpm = score_data.get("bpm")
                if bpm is None and isinstance(score_data.get("meta"), dict):
                    bpm = score_data["meta"].get("bpm")
                await asyncio.to_thread(
                    self.midi_exporter.export_from_score_data,
                    score_data,
                    float(bpm),
                    str(workspace.final_midi_path),
                )
                return workspace.final_midi_path, warnings
            except Exception as exc:
                warnings.append(f"score_ir_midi_export_failed:{self._short_exception(exc)}")

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
            self._write_json(
                workspace.separation_manifest_path,
                {name: str(path) for name, path in perception.stem_paths.items()},
            )
            self._write_json(workspace.lyrics_segments_path, perception.lyrics_segments)
            if perception.whisper_raw is not None:
                self._write_json(workspace.whisper_raw_path, perception.whisper_raw)

            self._write_json(workspace.pitch_result_path, perception.pitch_result_dict)
            if perception.f0_track_dict is not None:
                self._write_json(workspace.f0_track_path, perception.f0_track_dict)
            if perception.pitch_contours_dict is not None:
                self._write_json(workspace.pitch_contours_path, perception.pitch_contours_dict)
            if perception.note_candidates_dict is not None:
                self._write_json(workspace.note_candidates_path, perception.note_candidates_dict)
            if perception.selected_melody_dict is not None:
                self._write_json(workspace.selected_melody_path, perception.selected_melody_dict)
            if perception.quantized_notes_dict is not None:
                self._write_json(workspace.quantized_notes_path, perception.quantized_notes_dict)
            if perception.rhythm_grid_dict is not None:
                self._write_json(workspace.rhythm_grid_path, perception.rhythm_grid_dict)
            if perception.vocal_activity_dict is not None:
                self._write_json(workspace.vocal_activity_path, perception.vocal_activity_dict)
            if perception.analysis_ir_dict is not None:
                self._write_json(workspace.analysis_ir_path, perception.analysis_ir_dict)
            if perception.score_data_dict is not None:
                self._write_json(workspace.score_data_path, perception.score_data_dict)
            if perception.semantic_audio_dict is not None:
                self._write_json(workspace.semantic_audio_path, perception.semantic_audio_dict)
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

    def _invoke_score_ir_builder(
        self,
        pitch_result_obj: Any,
        lyrics_segments: list[dict],
        analysis_ir_obj: AnalysisIR | None,
    ) -> ScoreIR:
        builder = self.score_ir_builder
        if builder is None:
            raise RuntimeError("score_ir_builder is not configured")

        build_fn = getattr(builder, "build", builder)
        if analysis_ir_obj is None:
            return build_fn(pitch_result_obj, lyrics_segments)

        try:
            signature = inspect.signature(build_fn)
            parameters = signature.parameters
            if "analysis_ir" in parameters or any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()
            ):
                return build_fn(pitch_result_obj, lyrics_segments, analysis_ir=analysis_ir_obj)
        except Exception:
            pass

        return build_fn(pitch_result_obj, lyrics_segments)

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

    def _build_note_candidates_payload(self, semantic_audio_dict: dict | None) -> dict | None:
        if not isinstance(semantic_audio_dict, dict):
            return None
        payload = {
            "melody_candidates": semantic_audio_dict.get("melody_candidates"),
            "harmony_candidates": semantic_audio_dict.get("harmony_candidates"),
            "bass_root_candidates": semantic_audio_dict.get("bass_root_candidates"),
        }
        if not any(isinstance(value, dict) for value in payload.values()):
            return None
        payload["source_stems"] = semantic_audio_dict.get("source_stems", {})
        return payload

    def _build_rhythm_grid_payload(self, semantic_audio_dict: dict | None) -> dict | None:
        if not isinstance(semantic_audio_dict, dict):
            return None
        rhythm_grid = semantic_audio_dict.get("rhythm_grid")
        return dict(rhythm_grid) if isinstance(rhythm_grid, dict) else None

    def _short_exception(self, exc: Exception) -> str:
        msg = str(exc).strip()
        if not msg:
            return exc.__class__.__name__
        return msg[:240]

    def _try_make_audio_processor(self) -> Any | None:
        try:
            from app.config import settings
            from app.modules.audio.config import AudioConfig
            from app.modules.audio.processor import AudioProcessor

            return AudioProcessor(
                AudioConfig(
                    sample_rate=settings.canonical_audio_sample_rate,
                    channels=settings.canonical_audio_channels,
                    output_format="wav",
                )
            )
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

    def _try_make_vocal_separator(self) -> Any | None:
        try:
            from app.modules.vocal.separator import VocalSeparator

            return VocalSeparator(backend="mdx-net")
        except Exception as exc:
            self.logger.warning("VocalSeparator unavailable: %s", self._short_exception(exc))
            return None

    def _try_make_pitch_pipeline(self) -> Any | None:
        try:
            from app.modules.pitch import PitchPipeline
            from app.services.pitch_runtime import build_pitch_detection_config_from_settings

            return PitchPipeline(config=build_pitch_detection_config_from_settings())
        except Exception as exc:
            self.logger.warning("PitchPipeline unavailable: %s", self._short_exception(exc))
            return None

    def _try_make_analysis_inferencer(self) -> Any | None:
        try:
            return BaselineAnalysisInferencer()
        except Exception as exc:
            self.logger.warning("BaselineAnalysisInferencer unavailable: %s", self._short_exception(exc))
            return None

    def _try_make_midi_exporter(self) -> Any | None:
        try:
            from app.modules.pitch import MidiExporter

            return MidiExporter()
        except Exception as exc:
            self.logger.warning("MidiExporter unavailable: %s", self._short_exception(exc))
            return None




