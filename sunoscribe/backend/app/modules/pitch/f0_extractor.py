from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .config import PitchDetectionConfig
from .detector import PitchDetector
from .exceptions import PitchDetectionFailedError, PitchModelUnavailableError
from .types import F0Frame, F0Track, VocalActivitySegment


class RMVPEF0Extractor:
    """Authoritative RMVPE frame-level F0 extractor.

    This stage intentionally stops at ``F0Track``. It must not perform note
    segmentation or use CREPE/basic-pitch fallbacks to mask RMVPE failures.
    """

    VERSION = "rmvpe_f0_extractor_v1"

    def __init__(
        self,
        config: PitchDetectionConfig | None = None,
        detector: PitchDetector | None = None,
    ) -> None:
        self.detector = detector or PitchDetector(config or PitchDetectionConfig())
        self.config = config or self.detector.config
        self.last_extraction_artifacts: dict[str, Any] | None = None

    def extract(self, audio_path: str, *, source_stem: str | None = None) -> F0Track:
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise PitchDetectionFailedError(f"rmvpe_f0_extraction_failed:audio_file_not_found:{audio_path}")

        rmvpe_config = replace(
            self.config,
            pitch_backend="rmvpe",
            pitch_backend_fallbacks=(),
            allow_backend_fallbacks=False,
        )
        original_config = self.detector.config
        original_backend_name = self.detector.backend_name
        original_active_backend_name = self.detector.active_backend_name

        try:
            self.detector.config = rmvpe_config
            self.detector.backend_name = "rmvpe"
            self.detector.active_backend_name = "rmvpe"
            self.detector.backend_warnings = []
            self.detector.last_detection_artifacts = None

            duration_sec = self.detector._validate_audio_length(str(audio_file))
            model_path = self.detector._resolve_rmvpe_model_path()
            sample_rate = max(
                1,
                int(getattr(rmvpe_config, "rmvpe_sample_rate", rmvpe_config.sample_rate) or rmvpe_config.sample_rate),
            )
            step_size_ms = max(
                1,
                int(getattr(rmvpe_config, "rmvpe_step_size_ms", rmvpe_config.crepe_step_size_ms) or rmvpe_config.crepe_step_size_ms),
            )

            model = self.detector._build_rmvpe_model(model_path=model_path)
            try:
                audio, loaded_sample_rate = self.detector._load_audio_mono(str(audio_file), sample_rate=sample_rate)
            except Exception as exc:
                raise PitchDetectionFailedError(f"rmvpe_f0_extraction_failed:audio_load_failed:{exc}") from exc

            if audio.size == 0:
                self._store_empty_failure_artifact(audio_file=audio_file, reason_code="rmvpe_audio_empty")
                raise PitchDetectionFailedError("rmvpe_f0_extraction_failed:rmvpe_audio_empty")

            try:
                times, frequencies, confidences = self.detector._predict_rmvpe_frames(
                    audio=audio,
                    sample_rate=loaded_sample_rate,
                    duration_sec=float(duration_sec),
                    step_size_ms=step_size_ms,
                    model=model,
                )
            except PitchModelUnavailableError:
                raise
            except Exception as exc:
                raise PitchDetectionFailedError(f"rmvpe_f0_extraction_failed:inference_failed:{exc}") from exc

            time_arr = np.asarray(times, dtype=float).reshape(-1)
            freq_arr = np.asarray(frequencies, dtype=float).reshape(-1)
            conf_arr = np.asarray(confidences, dtype=float).reshape(-1)
            frame_count = int(min(time_arr.size, freq_arr.size, conf_arr.size))
            if frame_count <= 0:
                self._store_empty_failure_artifact(audio_file=audio_file, reason_code="rmvpe_returned_no_frames")
                raise PitchDetectionFailedError("rmvpe_f0_extraction_failed:rmvpe_returned_no_frames")

            self.detector._store_frame_artifacts(
                audio_path=str(audio_file),
                backend="rmvpe",
                times=time_arr[:frame_count],
                frequencies=freq_arr[:frame_count],
                confidences=conf_arr[:frame_count],
            )

            artifacts = self.detector.last_detection_artifacts
            if not isinstance(artifacts, dict) or not isinstance(artifacts.get("f0_track"), dict):
                raise PitchDetectionFailedError("rmvpe_f0_extraction_failed:f0_track_artifact_missing")

            f0_track_payload = artifacts["f0_track"]
            f0_track = self._track_from_payload(f0_track_payload, raw_artifacts=artifacts, source_stem=source_stem)
            f0_track.analysis_info.update(
                {
                    "extractor": self.VERSION,
                    "stage": "F0Track",
                    "authoritative": True,
                    "required_stage": True,
                    "fallback_allowed": False,
                    "frame_count": len(f0_track.frames),
                }
            )
            f0_track_payload["analysis_info"] = dict(f0_track.analysis_info)
            f0_track_payload["source_stem"] = source_stem
            self.last_extraction_artifacts = artifacts
            return f0_track
        finally:
            self.detector.config = original_config
            self.detector.backend_name = original_backend_name
            self.detector.active_backend_name = original_active_backend_name

    def _store_empty_failure_artifact(self, *, audio_file: Path, reason_code: str) -> None:
        artifacts = {
            "backend": "rmvpe",
            "input_audio_path": str(audio_file),
            "frame_count": 0,
            "f0_track": None,
            "warnings": [reason_code],
            "required_stage": True,
            "fallback_allowed": False,
            "extractor": self.VERSION,
        }
        self.detector.last_detection_artifacts = artifacts
        self.last_extraction_artifacts = artifacts

    @staticmethod
    def _track_from_payload(
        payload: dict[str, Any],
        *,
        raw_artifacts: dict[str, Any],
        source_stem: str | None,
    ) -> F0Track:
        frames: list[F0Frame] = []
        for raw_frame in payload.get("frames") or []:
            if not isinstance(raw_frame, dict):
                continue
            frames.append(
                F0Frame(
                    time_sec=_safe_float(raw_frame.get("time_sec")),
                    frequency_hz=_safe_float(raw_frame.get("frequency_hz")),
                    confidence=_safe_float(raw_frame.get("confidence")),
                    voiced=bool(raw_frame.get("voiced", False)),
                    pitch_midi=_safe_optional_float(raw_frame.get("pitch_midi")),
                )
            )

        vocal_activity: list[VocalActivitySegment] = []
        for raw_segment in payload.get("vocal_activity") or []:
            if not isinstance(raw_segment, dict):
                continue
            vocal_activity.append(
                VocalActivitySegment(
                    start_time=_safe_float(raw_segment.get("start_time")),
                    end_time=_safe_float(raw_segment.get("end_time")),
                    state=str(raw_segment.get("state") or "inactive"),
                    voiced_ratio=_safe_float(raw_segment.get("voiced_ratio")),
                    mean_confidence=_safe_float(raw_segment.get("mean_confidence")),
                    source_stem=source_stem,
                    analysis_info=dict(raw_segment.get("analysis_info") or {}),
                )
            )

        return F0Track(
            source_stem=source_stem,
            input_audio_path=str(payload.get("input_audio_path") or raw_artifacts.get("input_audio_path") or ""),
            backend=str(payload.get("backend") or raw_artifacts.get("backend") or "rmvpe"),
            frames=frames,
            vocal_activity=vocal_activity,
            analysis_info=dict(payload.get("analysis_info") or {}),
        )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
