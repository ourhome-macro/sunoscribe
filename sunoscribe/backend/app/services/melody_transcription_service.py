from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.workspace import ProjectWorkspace


@dataclass(slots=True)
class MelodyTranscriptionResult:
    pitch_result_obj: Any | None = None
    pitch_result_dict: dict | None = None
    semantic_audio_dict: dict | None = None
    f0_track_dict: dict | None = None
    vocal_activity_dict: dict | None = None
    note_candidates_dict: dict | None = None
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
    ) -> None:
        self.pitch_pipeline = pitch_pipeline
        self.serializer = serializer
        self.pitch_request_builder = pitch_request_builder
        self.short_exception = short_exception

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
            return MelodyTranscriptionResult(warnings=["pitch_pipeline_missing: skip pitch"])

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

        result.note_candidates_dict = self._build_note_candidates_payload(result.semantic_audio_dict)

        if hasattr(self.pitch_pipeline, "export_midi"):
            try:
                self.pitch_pipeline.export_midi(result.pitch_result_obj, str(workspace.raw_pitch_midi_path))
                result.raw_pitch_midi_path = workspace.raw_pitch_midi_path
            except Exception as exc:
                result.warnings.append(f"raw_midi_export_failed:{self.short_exception(exc)}")

        return result

    @staticmethod
    def _build_note_candidates_payload(semantic_audio_dict: dict | None) -> dict | None:
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
