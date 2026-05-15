from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.modules.pitch.melody_selection_artifact import RuleBasedMelodySelector
from app.modules.pitch.note_candidate_builder import NoteCandidateBuilder
from app.modules.pitch.pitch_contours import PitchContourBuilder
from app.modules.pitch.quantized_notes_artifact import QuantizedNotesArtifactBuilder, score_ir_note_annotations
from app.services.workspace import ProjectWorkspace


@dataclass(slots=True)
class MelodyTranscriptionResult:
    pitch_result_obj: Any | None = None
    pitch_result_dict: dict | None = None
    semantic_audio_dict: dict | None = None
    f0_track_dict: dict | None = None
    pitch_contours_dict: dict | None = None
    vocal_activity_dict: dict | None = None
    note_candidates_dict: dict | None = None
    selected_melody_dict: dict | None = None
    quantized_notes_dict: dict | None = None
    raw_pitch_midi_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


class MelodyTranscriptionService:
    """Run lead-vocal pitch/F0 transcription and note candidate extraction."""

    def __init__(
        self,
        *,
        pitch_pipeline: Any | None,
        serializer: Callable[[Any], Any],
        pitch_request_builder: Callable[..., Any],
        short_exception: Callable[[Exception], str],
        pitch_contour_builder: PitchContourBuilder | None = None,
        note_candidate_builder: NoteCandidateBuilder | None = None,
        melody_selector: RuleBasedMelodySelector | None = None,
        quantized_notes_builder: QuantizedNotesArtifactBuilder | None = None,
    ) -> None:
        self.pitch_pipeline = pitch_pipeline
        self.serializer = serializer
        self.pitch_request_builder = pitch_request_builder
        self.short_exception = short_exception
        self.pitch_contour_builder = pitch_contour_builder or PitchContourBuilder()
        self.note_candidate_builder = note_candidate_builder or NoteCandidateBuilder()
        self.melody_selector = melody_selector or RuleBasedMelodySelector()
        self.quantized_notes_builder = quantized_notes_builder or QuantizedNotesArtifactBuilder()

    def transcribe(
        self,
        *,
        source_audio_path: Path,
        canonical_audio_path: Path,
        vocals_path: Path | None,
        accompaniment_path: Path | None,
        stem_paths: dict[str, Path],
        workspace: ProjectWorkspace,
    ) -> MelodyTranscriptionResult:
        if self.pitch_pipeline is None:
            raise RuntimeError("required pitch pipeline is unavailable")

        result = MelodyTranscriptionResult()
        pitch_request = self.pitch_request_builder(
            source_audio_path=source_audio_path,
            fallback_audio_path=canonical_audio_path,
            vocals_path=vocals_path,
            accompaniment_path=accompaniment_path,
            stem_paths=stem_paths,
        )
        result.pitch_result_obj = self.pitch_pipeline.run(pitch_request)

        serialized = self.serializer(result.pitch_result_obj)
        result.pitch_result_dict = serialized if isinstance(serialized, dict) else {"value": serialized}

        semantic_audio_serialized = self.serializer(getattr(result.pitch_result_obj, "semantic_audio", None))
        if semantic_audio_serialized is not None:
            result.semantic_audio_dict = (
                semantic_audio_serialized
                if isinstance(semantic_audio_serialized, dict)
                else {"value": semantic_audio_serialized}
            )

        f0_track_serialized = self.serializer(getattr(result.pitch_result_obj, "f0_track", None))
        if f0_track_serialized is not None:
            result.f0_track_dict = (
                f0_track_serialized if isinstance(f0_track_serialized, dict) else {"value": f0_track_serialized}
            )
            result.f0_track_dict = self._normalize_f0_track_payload(result.f0_track_dict)
            raw_vocal_activity = result.f0_track_dict.get("vocal_activity")
            if raw_vocal_activity is not None:
                if isinstance(raw_vocal_activity, list):
                    result.vocal_activity_dict = {"segments": raw_vocal_activity}
                elif isinstance(raw_vocal_activity, dict):
                    result.vocal_activity_dict = dict(raw_vocal_activity)
                else:
                    result.vocal_activity_dict = {"value": raw_vocal_activity}

        result.pitch_contours_dict = self.pitch_contour_builder.build(result.f0_track_dict)
        result.note_candidates_dict = self._build_note_candidates_payload(
            f0_track_dict=result.f0_track_dict,
            pitch_contours_dict=result.pitch_contours_dict,
            semantic_audio_dict=result.semantic_audio_dict,
        )
        result.selected_melody_dict = self.melody_selector.select(
            note_candidates=result.note_candidates_dict,
            pitch_contours=result.pitch_contours_dict,
            vocal_activity=result.vocal_activity_dict,
        )
        rhythm_grid_dict = self._build_rhythm_grid_payload(result.semantic_audio_dict)
        result.quantized_notes_dict = self.quantized_notes_builder.build(
            selected_melody=result.selected_melody_dict,
            rhythm_grid=rhythm_grid_dict,
        )

        if hasattr(self.pitch_pipeline, "export_midi"):
            try:
                self.pitch_pipeline.export_midi(result.pitch_result_obj, str(workspace.raw_pitch_midi_path))
                result.raw_pitch_midi_path = workspace.raw_pitch_midi_path
            except Exception as exc:
                result.warnings.append(f"raw_midi_export_failed:{self.short_exception(exc)}")

        if not self._has_lead_notes(result.pitch_result_obj):
            raise RuntimeError(self._build_no_lead_notes_message(result.pitch_result_obj))

        return result

    @staticmethod
    def _has_lead_notes(pitch_result_obj: Any | None) -> bool:
        if pitch_result_obj is None:
            return False
        notes = getattr(pitch_result_obj, "lead_notes", None)
        if isinstance(notes, list) and notes:
            return True

        measures = getattr(pitch_result_obj, "measures", None)
        if isinstance(measures, list):
            for measure in measures:
                if not isinstance(measure, dict):
                    continue
                notes = measure.get("notes")
                if isinstance(notes, list) and notes:
                    return True
        return False

    @classmethod
    def _build_no_lead_notes_message(cls, pitch_result_obj: Any | None) -> str:
        diagnostics: list[str] = []
        analysis_info = getattr(pitch_result_obj, "analysis_info", None)
        detected_count = None
        melody_count = None
        if isinstance(analysis_info, dict):
            detected_count = analysis_info.get("detected_note_count")
            melody_count = analysis_info.get("melody_note_count")

        if detected_count is None:
            semantic_audio = getattr(pitch_result_obj, "semantic_audio", None)
            melody_candidates = getattr(semantic_audio, "melody_candidates", None)
            candidate_info = getattr(melody_candidates, "analysis_info", None)
            if isinstance(candidate_info, dict):
                detected_count = candidate_info.get("candidate_count")
            if detected_count is None:
                raw_notes = getattr(pitch_result_obj, "raw_notes", None)
                if isinstance(raw_notes, list):
                    detected_count = len(raw_notes)

        if melody_count is None:
            lead_notes = getattr(pitch_result_obj, "lead_notes", None)
            if isinstance(lead_notes, list):
                melody_count = len(lead_notes)
            elif pitch_result_obj is not None:
                melody_count = cls._count_measure_notes(getattr(pitch_result_obj, "measures", None))

        if detected_count is not None:
            diagnostics.append(f"detected_candidates={detected_count}")
        if melody_count is not None:
            diagnostics.append(f"selected_lead_notes={melody_count}")

        warnings = getattr(pitch_result_obj, "warnings", None)
        compact_warnings = cls._compact_warnings(warnings)
        if compact_warnings:
            diagnostics.append(f"warnings={compact_warnings}")

        message = "required pitch pipeline produced no lead-vocal notes"
        if diagnostics:
            return f"{message}; {'; '.join(diagnostics)}"
        return message

    @staticmethod
    def _count_measure_notes(measures: Any) -> int | None:
        if not isinstance(measures, list):
            return None
        total = 0
        for measure in measures:
            if not isinstance(measure, dict):
                continue
            notes = measure.get("notes")
            if isinstance(notes, list):
                total += len(notes)
        return total

    @staticmethod
    def _compact_warnings(warnings: Any) -> str:
        if not isinstance(warnings, list):
            return ""
        compact_items = [str(item).strip()[:120] for item in warnings if str(item).strip()]
        if not compact_items:
            return ""
        visible_items = compact_items[:3]
        if len(compact_items) > 3:
            visible_items.append(f"+{len(compact_items) - 3} more")
        return " | ".join(visible_items)

    def _build_note_candidates_payload(
        self,
        *,
        f0_track_dict: dict[str, Any] | None,
        pitch_contours_dict: dict[str, Any] | None,
        semantic_audio_dict: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if f0_track_dict is None:
            raise RuntimeError("required F0Track is unavailable for note candidate build")
        if pitch_contours_dict is None:
            raise RuntimeError("required PitchContourSet is unavailable for note candidate build")

        semantic_melody = (
            semantic_audio_dict.get("melody_candidates")
            if isinstance(semantic_audio_dict, dict)
            else None
        )
        payload = self.note_candidate_builder.build(
            f0_track=f0_track_dict,
            pitch_contours=pitch_contours_dict,
            raw_candidates=semantic_melody,
        )
        serialized = self.serializer(payload)
        if not isinstance(serialized, dict):
            raise RuntimeError("note candidate builder returned a non-dict payload")

        if isinstance(semantic_audio_dict, dict):
            if isinstance(semantic_audio_dict.get("harmony_candidates"), dict):
                serialized["harmony_candidates"] = semantic_audio_dict.get("harmony_candidates")
            if isinstance(semantic_audio_dict.get("bass_root_candidates"), dict):
                serialized["bass_root_candidates"] = semantic_audio_dict.get("bass_root_candidates")
            serialized["source_stems"] = semantic_audio_dict.get("source_stems", {})
        return serialized

    @staticmethod
    def _build_rhythm_grid_payload(semantic_audio_dict: dict | None) -> dict | None:
        if not isinstance(semantic_audio_dict, dict):
            return None
        rhythm_grid = semantic_audio_dict.get("rhythm_grid")
        return dict(rhythm_grid) if isinstance(rhythm_grid, dict) else None

    @staticmethod
    def _normalize_f0_track_payload(f0_track_dict: dict) -> dict:
        payload = dict(f0_track_dict)
        frames = payload.get("frames")
        if not isinstance(frames, list):
            return payload

        normalized_frames = []
        for frame in frames:
            if not isinstance(frame, dict):
                normalized_frames.append(frame)
                continue
            normalized = dict(frame)
            if "time_sec" not in normalized and "time" in normalized:
                normalized["time_sec"] = normalized.get("time")
            if "f0_hz" not in normalized:
                normalized["f0_hz"] = normalized.get("frequency_hz")
            if "midi_float" not in normalized:
                normalized["midi_float"] = normalized.get("pitch_midi")
            if "voiced" not in normalized:
                normalized["voiced"] = None
            if "confidence" not in normalized:
                normalized["confidence"] = None
                normalized["confidence_status"] = "unavailable"
            normalized_frames.append(normalized)
        payload["frames"] = normalized_frames
        return payload
