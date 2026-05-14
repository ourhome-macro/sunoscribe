from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path
from typing import List

import librosa
import numpy as np

from .audio_utils import get_audio_duration
from .config import PitchDetectionConfig
from .exceptions import (
    AudioTooLongError,
    PitchDetectionFailedError,
    PitchModelUnavailableError,
)
from .note_utils import hz_to_midi, midi_to_note, note_to_midi
from .reason_codes import (
    DP_LOW_CONFIDENCE_ISLAND_REJECTED,
    DP_SHORT_FRAGMENT_REJECTED,
    DP_SHORT_GAP_MERGED,
    DP_SHORT_SPIKE_SUPPRESSED,
    DP_VITERBI_SEGMENTATION,
)
from .types import Note


class PitchDetector:
    """Pitch detector with pluggable backends (RMVPE / CREPE / basic-pitch)."""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.backend_name = self._normalize_backend(self.config.pitch_backend)
        self.active_backend_name = self.backend_name
        self.backend_warnings: list[str] = []
        self.last_detection_artifacts: dict[str, object] | None = None

    @staticmethod
    def _normalize_backend(raw: str) -> str:
        value = str(raw or "").strip().lower()
        if value in {"rmvpe", "crepe", "basic-pitch"}:
            return value
        if value in {"r-mvpe", "rvc-rmvpe"}:
            return "rmvpe"
        if value in {"basic_pitch", "basicpitch"}:
            return "basic-pitch"
        return "rmvpe"

    def _validate_audio_length(self, audio_path: str) -> float:
        try:
            duration = get_audio_duration(audio_path)
        except Exception as exc:
            raise PitchDetectionFailedError(f"failed to read audio duration: {exc}") from exc

        if duration > self.config.max_audio_length_sec:
            raise AudioTooLongError(
                f"audio duration {duration:.2f}s exceeds limit {self.config.max_audio_length_sec:.2f}s"
            )
        return float(duration)

    def detect(self, audio_path: str) -> List[Note]:
        """Return non-quantized notes from detector backend."""
        self.active_backend_name = self.backend_name
        self.backend_warnings = []
        self.last_detection_artifacts = None

        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise PitchDetectionFailedError(f"audio file not found: {audio_path}")

        duration = self._validate_audio_length(audio_path)

        if self.backend_name == "rmvpe":
            try:
                return self._detect_with_rmvpe(audio_file, duration_sec=duration)
            except PitchModelUnavailableError as exc:
                if not bool(getattr(self.config, "allow_backend_fallbacks", False)):
                    self.backend_warnings = ["pitch_backend_fallback_disabled:rmvpe"]
                    raise PitchModelUnavailableError(
                        "RMVPE backend is required for this profile and no fallback is allowed."
                    ) from exc
                return self._detect_with_backend_fallbacks(audio_file, duration_sec=duration, original_error=exc)
        if self.backend_name == "basic-pitch":
            return self._detect_with_basic_pitch(audio_file)
        return self._detect_with_crepe(audio_file, duration_sec=duration)

    def _detect_with_backend_fallbacks(
        self,
        audio_file: Path,
        *,
        duration_sec: float,
        original_error: PitchModelUnavailableError,
    ) -> List[Note]:
        fallback_backends = tuple(getattr(self.config, "pitch_backend_fallbacks", ("crepe", "basic-pitch")) or ())
        errors = [f"{self.backend_name}:{original_error}"]

        for raw_backend in fallback_backends:
            backend = self._normalize_backend(str(raw_backend))
            if backend == self.backend_name:
                continue

            fallback_config = replace(self.config, pitch_backend=backend)
            fallback_detector = PitchDetector(fallback_config)
            try:
                if backend == "basic-pitch":
                    notes = fallback_detector._detect_with_basic_pitch(audio_file)
                elif backend == "crepe":
                    notes = fallback_detector._detect_with_crepe(audio_file, duration_sec=duration_sec)
                elif backend == "rmvpe":
                    notes = fallback_detector._detect_with_rmvpe(audio_file, duration_sec=duration_sec)
                else:
                    continue
            except PitchModelUnavailableError as exc:
                errors.append(f"{backend}:{exc}")
                continue
            except PitchDetectionFailedError as exc:
                errors.append(f"{backend}:{exc}")
                continue

            self.active_backend_name = fallback_detector.active_backend_name
            self.backend_warnings = [
                f"pitch_backend_fallback:{self.backend_name}->{self.active_backend_name}",
            ]
            self.last_detection_artifacts = fallback_detector.last_detection_artifacts
            return notes

        detail = "; ".join(errors[-3:])
        raise PitchModelUnavailableError(f"No pitch backend available. {detail}") from original_error

    def _detect_with_basic_pitch(self, audio_file: Path) -> List[Note]:
        try:
            from basic_pitch.inference import predict
            from basic_pitch.note_creation import model_output_to_notes
        except Exception as exc:
            raise PitchModelUnavailableError(
                "basic-pitch backend is unavailable. Install basic-pitch and its runtime dependencies."
            ) from exc

        try:
            model_output, _midi_data, note_events = predict(str(audio_file))
            if not note_events:
                note_events = model_output_to_notes(
                    model_output=model_output,
                    onset_thresh=self.config.confidence_threshold,
                    frame_thresh=self.config.confidence_threshold,
                    min_note_len=50,
                    infer_onsets=True,
                    melodia_trick=True,
                )
        except Exception as exc:
            raise PitchDetectionFailedError(f"basic-pitch inference failed: {exc}") from exc

        notes: List[Note] = []
        for event in note_events:
            if len(event) < 4:
                continue
            start_time, end_time, pitch_midi, confidence = event[:4]
            if float(confidence) < self.config.confidence_threshold:
                continue

            pitch_name = midi_to_note(int(round(float(pitch_midi))))
            notes.append(
                Note(
                    pitch=pitch_name,
                    start_time=float(start_time),
                    end_time=float(end_time),
                    confidence=float(confidence),
                )
            )

        notes.sort(key=lambda n: (n.start_time, n.end_time))
        self.last_detection_artifacts = {
            "backend": "basic-pitch",
            "input_audio_path": str(audio_file),
            "frame_count": 0,
            "f0_track": None,
            "warnings": ["frame_level_f0_unavailable_for_basic_pitch"],
        }
        return notes

    def _detect_with_rmvpe(self, audio_file: Path, *, duration_sec: float) -> List[Note]:
        model_path = self._resolve_rmvpe_model_path()
        sample_rate = max(
            1,
            int(getattr(self.config, "rmvpe_sample_rate", self.config.sample_rate) or self.config.sample_rate),
        )
        step_size_ms = max(
            1,
            int(
                getattr(self.config, "rmvpe_step_size_ms", self.config.crepe_step_size_ms)
                or self.config.crepe_step_size_ms
            ),
        )

        model = self._build_rmvpe_model(model_path=model_path)

        try:
            audio, sr = self._load_audio_mono(str(audio_file), sample_rate=sample_rate)
        except Exception as exc:
            raise PitchDetectionFailedError(f"failed to load audio for RMVPE: {exc}") from exc

        if audio.size == 0:
            return []

        try:
            times, frequencies, confidences = self._predict_rmvpe_frames(
                audio=audio,
                sample_rate=sr,
                duration_sec=float(duration_sec),
                step_size_ms=step_size_ms,
                model=model,
            )
        except PitchModelUnavailableError:
            raise
        except Exception as exc:
            raise PitchDetectionFailedError(f"RMVPE inference failed: {exc}") from exc

        time_arr = np.asarray(times, dtype=float).reshape(-1)
        freq_arr = np.asarray(frequencies, dtype=float).reshape(-1)
        conf_arr = np.asarray(confidences, dtype=float).reshape(-1)
        frame_count = int(min(time_arr.size, freq_arr.size, conf_arr.size))
        if frame_count <= 0:
            self.last_detection_artifacts = {
                "backend": "rmvpe",
                "input_audio_path": str(audio_file),
                "frame_count": 0,
                "f0_track": None,
                "warnings": ["rmvpe_returned_no_frames"],
            }
            return []

        self._store_frame_artifacts(
            audio_path=str(audio_file),
            backend="rmvpe",
            times=time_arr[:frame_count],
            frequencies=freq_arr[:frame_count],
            confidences=conf_arr[:frame_count],
        )
        return self._frames_to_notes(
            times=time_arr[:frame_count],
            frequencies=freq_arr[:frame_count],
            confidences=conf_arr[:frame_count],
            duration_sec=float(duration_sec),
            backend="rmvpe",
        )

    def _resolve_rmvpe_model_path(self) -> str | None:
        raw_path = getattr(self.config, "rmvpe_model_path", None)
        if raw_path is None:
            return None

        value = str(raw_path).strip()
        if not value:
            return None

        model_path = Path(value).expanduser()
        if not model_path.exists():
            raise PitchModelUnavailableError(f"RMVPE model file is unavailable: {model_path}")
        return str(model_path.resolve())

    def _predict_rmvpe_frames(
        self,
        *,
        audio: np.ndarray,
        sample_rate: int,
        duration_sec: float,
        step_size_ms: int,
        model: object,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        raw_output = self._call_rmvpe_model(
            model,
            audio=audio,
            sample_rate=sample_rate,
            step_size_ms=step_size_ms,
        )
        return self._coerce_rmvpe_output(
            raw_output,
            duration_sec=duration_sec,
            step_size_ms=step_size_ms,
        )

    def _build_rmvpe_model(self, *, model_path: str | None) -> object:
        candidates = (
            ("rmvpe", "RMVPE"),
            ("rmvpe.inference", "RMVPE"),
            ("rmvpe.model", "RMVPE"),
            ("rmvpe_onnx", "RMVPE"),
            ("infer.lib.rmvpe", "RMVPE"),
            ("rvc.lib.rmvpe", "RMVPE"),
            ("rvc.lib.predictors.RMVPE", "RMVPE"),
            ("rvc.modules.extract_f0.rmvpe", "RMVPE"),
        )
        errors: list[str] = []

        for module_name, class_name in candidates:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                errors.append(f"{module_name}: {exc}")
                continue

            model_cls = getattr(module, class_name, None)
            if model_cls is not None:
                try:
                    return self._instantiate_rmvpe_model(model_cls, model_path=model_path)
                except PitchModelUnavailableError as exc:
                    errors.append(f"{module_name}.{class_name}: {exc}")
                    continue

            if any(
                callable(getattr(module, method_name, None))
                for method_name in ("infer_from_audio", "predict", "get_pitch")
            ):
                return module

            errors.append(f"{module_name}: no RMVPE predictor API found")

        detail = "; ".join(errors[-3:])
        suffix = f" Details: {detail}" if detail else ""
        raise PitchModelUnavailableError(
            "RMVPE backend is unavailable. Install an RMVPE runtime and provide a local model file if required."
            + suffix
        )

    def _instantiate_rmvpe_model(self, model_cls: object, *, model_path: str | None) -> object:
        device = self._preferred_rmvpe_device()
        attempts: list[tuple[tuple[object, ...], dict[str, object]]] = []

        if model_path:
            attempts.extend(
                [
                    ((), {"model_path": model_path, "is_half": False, "device": device}),
                    ((), {"model_path": model_path, "device": device}),
                    ((), {"model_path": model_path}),
                    ((model_path, False, device), {}),
                    ((model_path,), {}),
                ]
            )
        else:
            attempts.extend(
                [
                    ((), {}),
                    ((), {"model_path": None, "is_half": False, "device": device}),
                    ((), {"model_path": None, "device": device}),
                    ((None, False, device), {}),
                    ((None,), {}),
                ]
            )

        errors: list[str] = []
        for args, kwargs in attempts:
            try:
                return model_cls(*args, **kwargs)  # type: ignore[operator]
            except TypeError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:
                raise PitchModelUnavailableError(f"RMVPE model could not be loaded: {exc}") from exc

        detail = "; ".join(errors[-2:])
        raise PitchModelUnavailableError(f"RMVPE model could not be constructed. {detail}".strip())

    @staticmethod
    def _preferred_rmvpe_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _call_rmvpe_model(
        self,
        model: object,
        *,
        audio: np.ndarray,
        sample_rate: int,
        step_size_ms: int,
    ) -> object:
        threshold = max(0.0, min(1.0, float(getattr(self.config, "rmvpe_vuv_threshold", 0.03))))
        method_names = ("infer_from_audio", "predict", "get_pitch")

        for method_name in method_names:
            method = getattr(model, method_name, None)
            if callable(method):
                result, matched = self._try_rmvpe_calls(
                    method,
                    audio=audio,
                    sample_rate=sample_rate,
                    step_size_ms=step_size_ms,
                    threshold=threshold,
                )
                if matched:
                    return result

        if callable(model):
            result, matched = self._try_rmvpe_calls(
                model,
                audio=audio,
                sample_rate=sample_rate,
                step_size_ms=step_size_ms,
                threshold=threshold,
            )
            if matched:
                return result

        raise PitchModelUnavailableError("RMVPE backend does not expose a supported inference method.")

    def _try_rmvpe_calls(
        self,
        func: object,
        *,
        audio: np.ndarray,
        sample_rate: int,
        step_size_ms: int,
        threshold: float,
    ) -> tuple[object | None, bool]:
        call_attempts = (
            ((audio,), {"thred": threshold}),
            ((audio,), {"threshold": threshold}),
            ((audio,), {"sample_rate": sample_rate, "step_size": step_size_ms}),
            ((audio, sample_rate), {}),
            ((audio,), {}),
        )
        for args, kwargs in call_attempts:
            try:
                return func(*args, **kwargs), True  # type: ignore[operator]
            except TypeError:
                continue
            except Exception as exc:
                raise PitchModelUnavailableError(f"RMVPE inference runtime is unavailable: {exc}") from exc

        return None, False

    def _coerce_rmvpe_output(
        self,
        raw_output: object,
        *,
        duration_sec: float,
        step_size_ms: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        times: object | None = None
        frequencies: object | None = None
        confidences: object | None = None

        if isinstance(raw_output, dict):
            times = self._first_present(raw_output, ("times", "time", "timestamps"))
            frequencies = self._first_present(raw_output, ("frequencies", "frequency", "f0", "pitch", "pitch_hz"))
            confidences = self._first_present(raw_output, ("confidences", "confidence", "periodicity", "uv", "voiced"))
        elif isinstance(raw_output, (tuple, list)):
            values = list(raw_output)
            if len(values) >= 3:
                times, frequencies, confidences = values[:3]
            elif len(values) == 2:
                first, second = values
                if self._looks_like_time_axis(first, duration_sec=duration_sec):
                    times, frequencies = first, second
                else:
                    frequencies, confidences = first, second
            elif len(values) == 1:
                frequencies = values[0]
        else:
            frequencies = raw_output

        if frequencies is None:
            raise PitchDetectionFailedError("RMVPE did not return pitch frequencies.")

        freq_arr = np.asarray(frequencies, dtype=float).reshape(-1)
        if times is None:
            hop_sec = max(0.001, float(step_size_ms) / 1000.0)
            time_arr = np.arange(freq_arr.size, dtype=float) * hop_sec
        else:
            time_arr = np.asarray(times, dtype=float).reshape(-1)

        if confidences is None:
            conf_arr = np.where(np.isfinite(freq_arr) & (freq_arr > 0.0), 1.0, 0.0).astype(float)
        else:
            conf_arr = np.asarray(confidences, dtype=float).reshape(-1)
            conf_arr = np.nan_to_num(conf_arr, nan=0.0, posinf=0.0, neginf=0.0)
            conf_arr = np.clip(conf_arr, 0.0, 1.0)

        frame_count = int(min(time_arr.size, freq_arr.size, conf_arr.size))
        return time_arr[:frame_count], freq_arr[:frame_count], conf_arr[:frame_count]

    @staticmethod
    def _first_present(values: dict, keys: tuple[str, ...]) -> object | None:
        for key in keys:
            if key in values and values[key] is not None:
                return values[key]
        return None

    @staticmethod
    def _looks_like_time_axis(values: object, *, duration_sec: float) -> bool:
        try:
            arr = np.asarray(values, dtype=float).reshape(-1)
        except Exception:
            return False
        if arr.size < 2 or not np.all(np.isfinite(arr)):
            return False
        diffs = np.diff(arr)
        if not np.all(diffs >= -1e-7):
            return False
        return float(arr[0]) >= -1e-6 and float(arr[-1]) <= max(1.0, float(duration_sec) + 1.0)

    def _detect_with_crepe(self, audio_file: Path, *, duration_sec: float) -> List[Note]:
        try:
            import crepe
            backend = "crepe"
        except Exception:
            crepe = None
            backend = "torchcrepe"

        step_size = max(1, int(self.config.crepe_step_size_ms))
        model_capacity = str(self.config.crepe_model_capacity or "full").strip().lower()
        chunk_size_sec = max(1.0, float(getattr(self.config, "chunk_size_sec", 30.0)))
        overlap_sec = max(
            0.05,
            float(step_size) / 1000.0 * 2.0,
            float(self.config.crepe_min_note_duration_sec),
            float(self.config.crepe_max_unvoiced_gap_sec) * 2.0,
        )

        # Short inputs keep legacy one-shot path to minimize overhead.
        if duration_sec <= (chunk_size_sec + overlap_sec):
            try:
                audio, sr = self._load_audio_mono(str(audio_file), sample_rate=int(self.config.sample_rate))
            except Exception as exc:
                raise PitchDetectionFailedError(f"failed to load audio for CREPE: {exc}") from exc

            if audio.size == 0:
                return []

            try:
                times, frequencies, confidences = self._predict_crepe_frames(
                    audio=audio,
                    sample_rate=sr,
                    backend=backend,
                    crepe_module=crepe,
                    model_capacity=model_capacity,
                    step_size_ms=step_size,
                )
            except PitchModelUnavailableError:
                raise
            except Exception as exc:
                raise PitchDetectionFailedError(f"CREPE inference failed: {exc}") from exc

            time_arr = np.asarray(times, dtype=float).reshape(-1)
            freq_arr = np.asarray(frequencies, dtype=float).reshape(-1)
            conf_arr = np.asarray(confidences, dtype=float).reshape(-1)
        else:
            time_chunks: list[np.ndarray] = []
            freq_chunks: list[np.ndarray] = []
            conf_chunks: list[np.ndarray] = []

            cursor = 0.0
            sample_rate = int(self.config.sample_rate)

            while cursor < (duration_sec - 1e-6):
                core_start = float(cursor)
                core_end = float(min(duration_sec, core_start + chunk_size_sec))
                load_start = float(max(0.0, core_start - overlap_sec))
                load_end = float(min(duration_sec, core_end + overlap_sec))

                try:
                    audio, sr = self._load_audio_mono(
                        str(audio_file),
                        sample_rate=sample_rate,
                        offset=load_start,
                        duration=max(0.01, load_end - load_start),
                    )
                except Exception as exc:
                    raise PitchDetectionFailedError(f"failed to load audio chunk for CREPE: {exc}") from exc

                if audio.size == 0:
                    cursor = core_end
                    continue

                try:
                    times, frequencies, confidences = self._predict_crepe_frames(
                        audio=audio,
                        sample_rate=sr,
                        backend=backend,
                        crepe_module=crepe,
                        model_capacity=model_capacity,
                        step_size_ms=step_size,
                    )
                except PitchModelUnavailableError:
                    raise
                except Exception as exc:
                    raise PitchDetectionFailedError(f"CREPE inference failed: {exc}") from exc

                time_arr_chunk = np.asarray(times, dtype=float).reshape(-1) + load_start
                freq_arr_chunk = np.asarray(frequencies, dtype=float).reshape(-1)
                conf_arr_chunk = np.asarray(confidences, dtype=float).reshape(-1)
                frame_count_chunk = int(min(time_arr_chunk.size, freq_arr_chunk.size, conf_arr_chunk.size))
                if frame_count_chunk <= 0:
                    cursor = core_end
                    continue

                time_arr_chunk = time_arr_chunk[:frame_count_chunk]
                freq_arr_chunk = freq_arr_chunk[:frame_count_chunk]
                conf_arr_chunk = conf_arr_chunk[:frame_count_chunk]

                if core_end >= (duration_sec - 1e-6):
                    keep = (time_arr_chunk >= core_start) & (time_arr_chunk <= core_end + 1e-6)
                else:
                    keep = (time_arr_chunk >= core_start) & (time_arr_chunk < core_end)

                if np.any(keep):
                    time_chunks.append(time_arr_chunk[keep])
                    freq_chunks.append(freq_arr_chunk[keep])
                    conf_chunks.append(conf_arr_chunk[keep])

                cursor = core_end

            if not time_chunks:
                return []

            time_arr = np.concatenate(time_chunks, axis=0)
            freq_arr = np.concatenate(freq_chunks, axis=0)
            conf_arr = np.concatenate(conf_chunks, axis=0)

            order = np.argsort(time_arr, kind="mergesort")
            time_arr = time_arr[order]
            freq_arr = freq_arr[order]
            conf_arr = conf_arr[order]

            dedup_mask = np.ones(time_arr.shape[0], dtype=bool)
            if time_arr.shape[0] > 1:
                dedup_mask[1:] = np.diff(time_arr) > 1e-7
            time_arr = time_arr[dedup_mask]
            freq_arr = freq_arr[dedup_mask]
            conf_arr = conf_arr[dedup_mask]

        frame_count = int(min(time_arr.size, freq_arr.size, conf_arr.size))
        if frame_count <= 0:
            self.last_detection_artifacts = {
                "backend": backend,
                "input_audio_path": str(audio_file),
                "frame_count": 0,
                "f0_track": None,
                "warnings": [f"{backend}_returned_no_frames"],
            }
            return []

        time_arr = time_arr[:frame_count]
        freq_arr = freq_arr[:frame_count]
        conf_arr = conf_arr[:frame_count]

        self._store_frame_artifacts(
            audio_path=str(audio_file),
            backend=backend,
            times=time_arr,
            frequencies=freq_arr,
            confidences=conf_arr,
        )
        return self._frames_to_notes(
            times=time_arr,
            frequencies=freq_arr,
            confidences=conf_arr,
            duration_sec=float(duration_sec),
            backend=backend,
        )

    def _store_frame_artifacts(
        self,
        *,
        audio_path: str,
        backend: str,
        times: np.ndarray,
        frequencies: np.ndarray,
        confidences: np.ndarray,
    ) -> None:
        time_arr = np.asarray(times, dtype=float).reshape(-1)
        freq_arr = np.asarray(frequencies, dtype=float).reshape(-1)
        conf_arr = np.asarray(confidences, dtype=float).reshape(-1)
        frame_count = int(min(time_arr.size, freq_arr.size, conf_arr.size))
        if frame_count <= 0:
            self.last_detection_artifacts = {
                "backend": backend,
                "input_audio_path": str(audio_path),
                "frame_count": 0,
                "f0_track": None,
                "warnings": [f"{backend}_returned_no_frames"],
            }
            return

        time_arr = time_arr[:frame_count]
        freq_arr = freq_arr[:frame_count]
        conf_arr = np.clip(np.nan_to_num(conf_arr[:frame_count], nan=0.0, posinf=0.0, neginf=0.0), 0.0, 1.0)
        voiced = self._voiced_mask_from_frames(freq_arr, conf_arr, backend=backend)
        frame_hop_sec = self._estimate_frame_hop_sec(time_arr)
        vocal_activity = self._build_vocal_activity_segments(
            times=time_arr,
            confidences=conf_arr,
            voiced=voiced,
            frame_hop_sec=frame_hop_sec,
        )

        pitch_midi = np.full(freq_arr.shape, np.nan, dtype=float)
        hz_valid = np.isfinite(freq_arr) & (freq_arr > 0.0)
        if np.any(hz_valid):
            pitch_midi[hz_valid] = hz_to_midi(freq_arr[hz_valid])

        self.last_detection_artifacts = {
            "backend": backend,
            "input_audio_path": str(audio_path),
            "frame_count": int(frame_count),
            "f0_track": {
                "input_audio_path": str(audio_path),
                "backend": backend,
                "frames": [
                    {
                        "time_sec": round(float(time_arr[idx]), 6),
                        "frequency_hz": round(float(freq_arr[idx]), 6),
                        "confidence": round(float(conf_arr[idx]), 6),
                        "voiced": bool(voiced[idx]),
                        "pitch_midi": round(float(pitch_midi[idx]), 6) if np.isfinite(pitch_midi[idx]) else None,
                    }
                    for idx in range(frame_count)
                ],
                "vocal_activity": vocal_activity,
                "analysis_info": {
                    "frame_hop_sec": round(float(frame_hop_sec), 6),
                    "voiced_frame_count": int(np.sum(voiced)),
                    "unvoiced_frame_count": int(frame_count - np.sum(voiced)),
                    "voiced_confidence_threshold": self._segmentation_param(
                        backend,
                        rmvpe_name="rmvpe_vuv_threshold",
                        crepe_name="crepe_vuv_confidence_threshold",
                    ),
                    "segmentation_backend": self._segmentation_backend(backend),
                },
            },
            "warnings": [],
        }

    def _predict_crepe_frames(
        self,
        *,
        audio: np.ndarray,
        sample_rate: int,
        backend: str,
        crepe_module: object | None,
        model_capacity: str,
        step_size_ms: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if backend == "crepe" and crepe_module is not None:
            try:
                times, frequencies, confidences, _ = crepe_module.predict(
                    audio,
                    sample_rate,
                    viterbi=True,
                    step_size=step_size_ms,
                    model_capacity=model_capacity,
                    verbose=0,
                )
            except TypeError:
                # Keep compatibility with older crepe versions without `verbose` argument.
                times, frequencies, confidences, _ = crepe_module.predict(
                    audio,
                    sample_rate,
                    viterbi=True,
                    step_size=step_size_ms,
                    model_capacity=model_capacity,
                )
            return (
                np.asarray(times, dtype=float).reshape(-1),
                np.asarray(frequencies, dtype=float).reshape(-1),
                np.asarray(confidences, dtype=float).reshape(-1),
            )

        try:
            return self._predict_with_torchcrepe(
                audio=audio,
                sample_rate=sample_rate,
                model_capacity=model_capacity,
                step_size_ms=step_size_ms,
            )
        except Exception as exc:
            raise PitchModelUnavailableError(
                "CREPE backend is unavailable. Install package `crepe` or `torchcrepe`."
            ) from exc

    def _load_audio_mono(
        self,
        audio_path: str,
        *,
        sample_rate: int,
        offset: float = 0.0,
        duration: float | None = None,
    ) -> tuple[np.ndarray, int]:
        return librosa.load(
            audio_path,
            sr=int(sample_rate),
            mono=True,
            offset=float(offset),
            duration=None if duration is None else float(duration),
        )

    def _frames_to_notes(
        self,
        *,
        times: np.ndarray,
        frequencies: np.ndarray,
        confidences: np.ndarray,
        duration_sec: float,
        backend: str | None = None,
    ) -> List[Note]:
        backend_key = self._segmentation_backend(backend)
        voiced_threshold = max(
            0.0,
            min(
                1.0,
                self._segmentation_param(
                    backend_key,
                    rmvpe_name="rmvpe_vuv_threshold",
                    crepe_name="crepe_vuv_confidence_threshold",
                ),
            ),
        )
        min_note_duration = max(
            0.01,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_min_note_duration_sec",
                crepe_name="crepe_min_note_duration_sec",
            ),
        )
        min_voiced_frames = max(
            1,
            int(
                self._segmentation_param(
                    backend_key,
                    rmvpe_name="rmvpe_min_voiced_frames",
                    crepe_name="crepe_min_voiced_frames",
                )
            ),
        )
        jump_threshold = max(
            0.05,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_pitch_jump_semitones",
                crepe_name="crepe_pitch_jump_semitones",
            ),
        )
        smoothing_window = max(
            1,
            int(
                self._segmentation_param(
                    backend_key,
                    rmvpe_name="rmvpe_smoothing_window",
                    crepe_name="crepe_smoothing_window",
                )
            ),
        )

        frame_hop_sec = self._estimate_frame_hop_sec(times)
        max_unvoiced_gap_frames = max(
            0,
            int(
                round(
                    max(
                        0.0,
                        self._segmentation_param(
                            backend_key,
                            rmvpe_name="rmvpe_max_unvoiced_gap_sec",
                            crepe_name="crepe_max_unvoiced_gap_sec",
                        ),
                    )
                    / max(frame_hop_sec, 1e-4)
                )
            ),
        )

        midi = np.full(frequencies.shape, np.nan, dtype=float)
        hz_valid = np.isfinite(frequencies) & (frequencies > 0.0)
        if np.any(hz_valid):
            midi[hz_valid] = hz_to_midi(frequencies[hz_valid])

        voiced = (confidences >= voiced_threshold) & np.isfinite(midi)
        voiced = self._bridge_short_unvoiced(voiced, max_gap_frames=max_unvoiced_gap_frames)

        midi_smoothed = self._median_filter_nan(midi, window=smoothing_window)

        dp_notes_for_gap_augmentation: list[Note] | None = None
        if backend_key == "rmvpe":
            strategy = str(getattr(self.config, "rmvpe_segmentation_strategy", "greedy") or "greedy").strip().lower()
            if strategy == "dp_viterbi":
                dp_notes_for_gap_augmentation = self._frames_to_notes_dp_viterbi(
                    times=times,
                    midi_smoothed=midi_smoothed,
                    confidences=confidences,
                    voiced=voiced,
                    duration_sec=duration_sec,
                    backend_key=backend_key,
                    voiced_threshold=voiced_threshold,
                    min_note_duration=min_note_duration,
                    min_voiced_frames=min_voiced_frames,
                    jump_threshold=jump_threshold,
                    smoothing_window=smoothing_window,
                    max_unvoiced_gap_frames=max_unvoiced_gap_frames,
                    frame_hop_sec=frame_hop_sec,
                )
            elif strategy not in {"greedy", "legacy"}:
                raise PitchDetectionFailedError(f"unsupported RMVPE segmentation strategy: {strategy}")

        segments: list[tuple[int, int]] = []
        segment_start: int | None = None
        last_voiced_idx: int | None = None

        for idx in range(len(voiced)):
            if not voiced[idx]:
                if (
                    segment_start is not None
                    and last_voiced_idx is not None
                    and (idx - last_voiced_idx) > max_unvoiced_gap_frames
                ):
                    segments.append((segment_start, last_voiced_idx))
                    segment_start = None
                    last_voiced_idx = None
                continue

            if segment_start is None:
                segment_start = idx
                last_voiced_idx = idx
                continue

            prev_pitch = midi_smoothed[last_voiced_idx] if last_voiced_idx is not None else np.nan
            curr_pitch = midi_smoothed[idx]
            if np.isfinite(prev_pitch) and np.isfinite(curr_pitch) and abs(curr_pitch - prev_pitch) >= jump_threshold:
                if last_voiced_idx is not None:
                    segments.append((segment_start, last_voiced_idx))
                segment_start = idx

            last_voiced_idx = idx

        if segment_start is not None and last_voiced_idx is not None:
            segments.append((segment_start, last_voiced_idx))

        notes: List[Note] = []
        for start_idx, end_idx in segments:
            seg_mask = voiced[start_idx : end_idx + 1]
            voiced_count = int(np.sum(seg_mask))
            if voiced_count < min_voiced_frames:
                continue

            seg_midi = midi_smoothed[start_idx : end_idx + 1][seg_mask]
            seg_conf = confidences[start_idx : end_idx + 1][seg_mask]
            seg_midi = seg_midi[np.isfinite(seg_midi)]

            if seg_midi.size == 0:
                continue

            avg_conf = float(np.mean(seg_conf)) if seg_conf.size > 0 else 0.0
            median_midi = float(np.median(seg_midi))
            mad_semitones = self._median_absolute_deviation(seg_midi, median_midi)
            span_semitones = self._pitch_span(seg_midi)
            stability_factor = self._stability_factor(mad_semitones, backend=backend_key)
            span_factor = self._span_factor(span_semitones, backend=backend_key)
            quality_factor = max(0.0, min(1.0, 0.55 * stability_factor + 0.45 * span_factor))
            adjusted_conf = avg_conf * (0.35 + 0.65 * quality_factor)

            if quality_factor < 0.10 and avg_conf < max(0.8, float(self.config.confidence_threshold)):
                continue
            if adjusted_conf < float(self.config.confidence_threshold):
                continue

            start_time = max(0.0, float(times[start_idx]) - frame_hop_sec * 0.5)
            end_time = min(float(duration_sec), float(times[end_idx]) + frame_hop_sec * 0.5)
            if (end_time - start_time) < min_note_duration:
                continue

            pitch_midi = int(round(median_midi))
            pitch_name = midi_to_note(pitch_midi)
            notes.append(
                Note(
                    pitch=pitch_name,
                    start_time=start_time,
                    end_time=end_time,
                    confidence=adjusted_conf,
                    segmentation_evidence={
                        "backend": self._segmentation_backend(backend_key),
                        "start_frame_index": int(start_idx),
                        "end_frame_index": int(end_idx),
                        "voiced_frame_count": int(voiced_count),
                        "frame_hop_sec": round(float(frame_hop_sec), 6),
                        "avg_confidence": round(float(avg_conf), 6),
                        "adjusted_confidence": round(float(adjusted_conf), 6),
                        "median_pitch_midi": round(float(median_midi), 6),
                        "mad_semitones": round(float(mad_semitones), 6),
                        "span_semitones": round(float(span_semitones), 6),
                        "stability_factor": round(float(stability_factor), 6),
                        "span_factor": round(float(span_factor), 6),
                        "quality_factor": round(float(quality_factor), 6),
                        "voiced_threshold": round(float(voiced_threshold), 6),
                        "jump_threshold_semitones": round(float(jump_threshold), 6),
                        "min_note_duration_sec": round(float(min_note_duration), 6),
                    },
                )
            )

        notes.sort(key=lambda n: (n.start_time, n.end_time))
        if dp_notes_for_gap_augmentation is not None:
            notes = self._merge_legacy_and_dp_notes(notes, dp_notes_for_gap_augmentation)
        return notes

    def _merge_legacy_and_dp_notes(self, legacy_notes: list[Note], dp_notes: list[Note]) -> list[Note]:
        if not dp_notes:
            return list(legacy_notes)
        if not legacy_notes:
            return list(dp_notes)

        merged: list[Note] = []
        used_dp_indices: set[int] = set()
        for legacy_note in legacy_notes:
            replacement_index = self._find_equivalent_dp_note(legacy_note, dp_notes, used_dp_indices)
            if replacement_index is None:
                merged.append(legacy_note)
                continue
            replacement = dp_notes[replacement_index]
            used_dp_indices.add(replacement_index)
            evidence = dict(getattr(replacement, "segmentation_evidence", {}) or {})
            evidence["dp_legacy_anchor_replaced"] = True
            replacement.segmentation_evidence = evidence
            merged.append(replacement)

        for idx, dp_note in enumerate(dp_notes):
            if idx in used_dp_indices:
                continue
            duration = max(0.0, float(dp_note.end_time) - float(dp_note.start_time))
            if duration <= 0.0:
                continue
            max_overlap = max((self._note_overlap_sec(dp_note, existing) for existing in legacy_notes), default=0.0)
            if max_overlap > max(0.04, duration * 0.20):
                continue
            evidence = dict(getattr(dp_note, "segmentation_evidence", {}) or {})
            evidence["dp_gap_augmentation"] = True
            evidence["dp_max_legacy_overlap_sec"] = round(float(max_overlap), 6)
            dp_note.segmentation_evidence = evidence
            merged.append(dp_note)

        merged.sort(key=lambda n: (n.start_time, n.end_time))
        return merged

    def _find_equivalent_dp_note(
        self,
        legacy_note: Note,
        dp_notes: list[Note],
        used_dp_indices: set[int],
    ) -> int | None:
        legacy_duration = max(0.0, float(legacy_note.end_time) - float(legacy_note.start_time))
        if legacy_duration <= 0.0:
            return None
        try:
            legacy_pitch = note_to_midi(legacy_note.pitch)
        except Exception:
            return None

        best_index: int | None = None
        best_overlap = 0.0
        for idx, dp_note in enumerate(dp_notes):
            if idx in used_dp_indices:
                continue
            dp_duration = max(0.0, float(dp_note.end_time) - float(dp_note.start_time))
            if dp_duration <= 0.0:
                continue
            overlap = self._note_overlap_sec(legacy_note, dp_note)
            if overlap <= best_overlap:
                continue
            if overlap / legacy_duration < 0.80 or overlap / dp_duration < 0.80:
                continue
            try:
                dp_pitch = note_to_midi(dp_note.pitch)
            except Exception:
                continue
            if abs(int(dp_pitch) - int(legacy_pitch)) > 1:
                continue
            best_index = idx
            best_overlap = overlap
        return best_index

    @staticmethod
    def _note_overlap_sec(left: Note, right: Note) -> float:
        start = max(float(left.start_time), float(right.start_time))
        end = min(float(left.end_time), float(right.end_time))
        return max(0.0, end - start)


    def _frames_to_notes_dp_viterbi(
        self,
        *,
        times: np.ndarray,
        midi_smoothed: np.ndarray,
        confidences: np.ndarray,
        voiced: np.ndarray,
        duration_sec: float,
        backend_key: str,
        voiced_threshold: float,
        min_note_duration: float,
        min_voiced_frames: int,
        jump_threshold: float,
        smoothing_window: int,
        max_unvoiced_gap_frames: int,
        frame_hop_sec: float,
    ) -> List[Note]:
        frame_count = int(min(times.size, midi_smoothed.size, confidences.size, voiced.size))
        if frame_count <= 0:
            return []

        times = np.asarray(times[:frame_count], dtype=float)
        midi_smoothed = np.asarray(midi_smoothed[:frame_count], dtype=float)
        confidences = np.clip(
            np.nan_to_num(np.asarray(confidences[:frame_count], dtype=float), nan=0.0, posinf=0.0, neginf=0.0),
            0.0,
            1.0,
        )
        voiced = np.asarray(voiced[:frame_count], dtype=bool)

        states_by_frame = self._dp_frame_states(midi_smoothed=midi_smoothed, voiced=voiced)
        local_stability = self._dp_local_stability(midi_smoothed, backend=backend_key)
        path, path_score = self._dp_viterbi_path(
            states_by_frame=states_by_frame,
            midi_smoothed=midi_smoothed,
            confidences=confidences,
            voiced=voiced,
            voiced_threshold=voiced_threshold,
            jump_threshold=jump_threshold,
            local_stability=local_stability,
        )
        if not path:
            return []

        raw_segments = self._dp_path_segments(path)
        suppressed_spike_count = self._dp_suppressed_spike_count(
            path=path,
            midi_smoothed=midi_smoothed,
            confidences=confidences,
            voiced_threshold=voiced_threshold,
            jump_threshold=jump_threshold,
            max_unvoiced_gap_frames=max_unvoiced_gap_frames,
        )
        merged_segments, merged_gap_count = self._merge_dp_segments(
            raw_segments,
            frame_hop_sec=frame_hop_sec,
            min_note_duration=min_note_duration,
            min_voiced_frames=min_voiced_frames,
            max_unvoiced_gap_frames=max_unvoiced_gap_frames,
        )
        state_changes = sum(1 for idx in range(1, len(path)) if path[idx] != path[idx - 1])
        transition_penalty_total = self._dp_transition_penalty_total(path, jump_threshold=jump_threshold)
        rejected_reason_counts: dict[str, int] = {}
        notes: list[Note] = []

        dp_summary = {
            "path_score": round(float(path_score), 6),
            "state_changes": int(state_changes),
            "merged_gap_count": int(merged_gap_count),
            "suppressed_spike_count": int(suppressed_spike_count),
            "transition_penalty_total": round(float(transition_penalty_total), 6),
            "raw_segment_count": int(len(raw_segments)),
            "merged_segment_count": int(len(merged_segments)),
        }

        for start_idx, end_idx, _state_pitch in merged_segments:
            note = self._build_dp_note_from_segment(
                start_idx=start_idx,
                end_idx=end_idx,
                times=times,
                midi_smoothed=midi_smoothed,
                confidences=confidences,
                voiced=voiced,
                duration_sec=duration_sec,
                backend_key=backend_key,
                voiced_threshold=voiced_threshold,
                min_note_duration=min_note_duration,
                min_voiced_frames=min_voiced_frames,
                jump_threshold=jump_threshold,
                smoothing_window=smoothing_window,
                frame_hop_sec=frame_hop_sec,
                dp_summary=dp_summary,
            )
            if note is None:
                self._increment_reason_count(rejected_reason_counts, DP_SHORT_FRAGMENT_REJECTED)
                continue

            duration = float(note.end_time) - float(note.start_time)
            if duration < min_note_duration:
                self._increment_reason_count(rejected_reason_counts, DP_SHORT_FRAGMENT_REJECTED)
                continue
            if int(note.segmentation_evidence.get("voiced_frame_count", 0) or 0) < min_voiced_frames:
                self._increment_reason_count(rejected_reason_counts, DP_SHORT_FRAGMENT_REJECTED)
                continue
            if (
                float(note.confidence) < max(0.35, float(self.config.confidence_threshold))
                and duration < max(0.20, min_note_duration * 2.5)
            ):
                self._increment_reason_count(rejected_reason_counts, DP_LOW_CONFIDENCE_ISLAND_REJECTED)
                continue

            evidence = dict(note.segmentation_evidence)
            evidence["dp_rejected_reason_counts"] = dict(rejected_reason_counts)
            note.segmentation_evidence = evidence
            notes.append(note)

        notes.sort(key=lambda n: (n.start_time, n.end_time))
        return notes

    def _dp_frame_states(self, *, midi_smoothed: np.ndarray, voiced: np.ndarray) -> list[list[int | None]]:
        radius = max(0, int(getattr(self.config, "rmvpe_dp_pitch_radius_semitones", 2) or 0))
        states_by_frame: list[list[int | None]] = []
        for idx, observed in enumerate(midi_smoothed):
            states: list[int | None] = [None]
            if bool(voiced[idx]) and np.isfinite(observed):
                center = int(round(float(observed)))
                for pitch in range(center - radius, center + radius + 1):
                    if 21 <= pitch <= 108:
                        states.append(int(pitch))
            states_by_frame.append(states)
        return states_by_frame

    def _dp_local_stability(self, midi_smoothed: np.ndarray, *, backend: str) -> np.ndarray:
        window = max(3, int(getattr(self.config, "rmvpe_smoothing_window", 7) or 7))
        if window % 2 == 0:
            window += 1
        half = window // 2
        stability = np.ones(midi_smoothed.shape, dtype=float)
        for idx in range(midi_smoothed.size):
            left = max(0, idx - half)
            right = min(midi_smoothed.size, idx + half + 1)
            patch = midi_smoothed[left:right]
            patch = patch[np.isfinite(patch)]
            if patch.size <= 1:
                stability[idx] = 1.0
                continue
            center = float(np.median(patch))
            stability[idx] = self._stability_factor(self._median_absolute_deviation(patch, center), backend=backend)
        return np.clip(stability, 0.0, 1.0)

    def _dp_viterbi_path(
        self,
        *,
        states_by_frame: list[list[int | None]],
        midi_smoothed: np.ndarray,
        confidences: np.ndarray,
        voiced: np.ndarray,
        voiced_threshold: float,
        jump_threshold: float,
        local_stability: np.ndarray,
    ) -> tuple[list[int | None], float]:
        if not states_by_frame:
            return [], 0.0

        previous_scores: dict[int | None, float] = {}
        backpointers: list[dict[int | None, int | None]] = []
        for frame_idx, states in enumerate(states_by_frame):
            current_scores: dict[int | None, float] = {}
            current_backpointers: dict[int | None, int | None] = {}
            for state in states:
                emission = self._dp_emission_score(
                    frame_idx=frame_idx,
                    state=state,
                    midi_smoothed=midi_smoothed,
                    confidences=confidences,
                    voiced=voiced,
                    voiced_threshold=voiced_threshold,
                    local_stability=local_stability,
                )
                if frame_idx == 0:
                    current_scores[state] = emission
                    current_backpointers[state] = None
                    continue

                best_previous_state: int | None = None
                best_score = -float("inf")
                for previous_state, previous_score in previous_scores.items():
                    transition = self._dp_transition_score(
                        previous_state,
                        state,
                        jump_threshold=jump_threshold,
                    )
                    score = float(previous_score) + transition + emission
                    if score > best_score:
                        best_score = score
                        best_previous_state = previous_state
                current_scores[state] = best_score
                current_backpointers[state] = best_previous_state
            previous_scores = current_scores
            backpointers.append(current_backpointers)

        if not previous_scores:
            return [], 0.0
        best_state = max(previous_scores, key=previous_scores.get)
        best_score = float(previous_scores[best_state])
        path: list[int | None] = [best_state]
        for frame_idx in range(len(backpointers) - 1, 0, -1):
            best_state = backpointers[frame_idx].get(best_state)
            path.append(best_state)
        path.reverse()
        return path, best_score

    def _dp_emission_score(
        self,
        *,
        frame_idx: int,
        state: int | None,
        midi_smoothed: np.ndarray,
        confidences: np.ndarray,
        voiced: np.ndarray,
        voiced_threshold: float,
        local_stability: np.ndarray,
    ) -> float:
        confidence = float(confidences[frame_idx])
        observed = float(midi_smoothed[frame_idx]) if np.isfinite(midi_smoothed[frame_idx]) else float("nan")
        is_voiced = bool(voiced[frame_idx]) and np.isfinite(observed)
        if state is None:
            if not is_voiced:
                return 0.30
            excess_confidence = max(0.0, confidence - float(voiced_threshold))
            return -0.25 - (0.85 * excess_confidence)
        if not is_voiced:
            return -2.0
        confidence_span = max(1e-6, 1.0 - float(voiced_threshold))
        confidence_score = max(0.0, min(1.0, (confidence - float(voiced_threshold)) / confidence_span))
        pitch_distance = abs(observed - float(state))
        stability = float(local_stability[frame_idx]) if frame_idx < local_stability.size else 1.0
        return (1.05 * confidence_score) + (0.35 * stability) - (0.20 * pitch_distance) - 0.10

    @staticmethod
    def _dp_transition_score(previous_state: int | None, current_state: int | None, *, jump_threshold: float) -> float:
        if previous_state is None and current_state is None:
            return 0.15
        if previous_state is None:
            return -0.45
        if current_state is None:
            return -0.35
        delta = abs(int(current_state) - int(previous_state))
        if delta == 0:
            return 0.55
        score = -1.05 - (0.25 * float(delta))
        if float(delta) >= float(jump_threshold):
            score -= 0.65 + (0.12 * min(12.0, float(delta) - float(jump_threshold)))
        return score

    @staticmethod
    def _dp_path_segments(path: list[int | None]) -> list[tuple[int, int, int]]:
        segments: list[tuple[int, int, int]] = []
        segment_start: int | None = None
        segment_pitch: int | None = None
        for idx, state in enumerate(path):
            if state is None:
                if segment_start is not None and segment_pitch is not None:
                    segments.append((segment_start, idx - 1, int(segment_pitch)))
                    segment_start = None
                    segment_pitch = None
                continue
            if segment_start is None:
                segment_start = idx
                segment_pitch = int(state)
                continue
            if int(state) != int(segment_pitch):
                segments.append((segment_start, idx - 1, int(segment_pitch)))
                segment_start = idx
                segment_pitch = int(state)
        if segment_start is not None and segment_pitch is not None:
            segments.append((segment_start, len(path) - 1, int(segment_pitch)))
        return segments

    def _merge_dp_segments(
        self,
        segments: list[tuple[int, int, int]],
        *,
        frame_hop_sec: float,
        min_note_duration: float,
        min_voiced_frames: int,
        max_unvoiced_gap_frames: int,
    ) -> tuple[list[tuple[int, int, int]], int]:
        if not segments:
            return [], 0
        max_gap_frames = max(1, max_unvoiced_gap_frames + 1)
        short_fragment_frames = max(min_voiced_frames, int(round(max(min_note_duration, frame_hop_sec) / max(frame_hop_sec, 1e-4))))
        merged: list[tuple[int, int, int]] = [segments[0]]
        merge_count = 0
        for start_idx, end_idx, pitch in segments[1:]:
            prev_start, prev_end, prev_pitch = merged[-1]
            gap_frames = int(start_idx - prev_end - 1)
            pitch_delta = abs(int(pitch) - int(prev_pitch))
            prev_len = int(prev_end - prev_start + 1)
            curr_len = int(end_idx - start_idx + 1)
            same_pitch = pitch_delta == 0
            near_short_fragment = pitch_delta <= 1 and min(prev_len, curr_len) <= max(short_fragment_frames, min_voiced_frames * 2)
            expressive_adjacent = pitch_delta <= 2 and gap_frames <= max_gap_frames and min(prev_len, curr_len) <= max(short_fragment_frames * 3, min_voiced_frames * 5)
            if gap_frames <= max_gap_frames and (same_pitch or near_short_fragment or expressive_adjacent):
                kept_pitch = int(prev_pitch if prev_len >= curr_len else pitch)
                merged[-1] = (prev_start, end_idx, kept_pitch)
                merge_count += 1
                continue
            merged.append((start_idx, end_idx, pitch))
        return merged, merge_count

    def _build_dp_note_from_segment(
        self,
        *,
        start_idx: int,
        end_idx: int,
        times: np.ndarray,
        midi_smoothed: np.ndarray,
        confidences: np.ndarray,
        voiced: np.ndarray,
        duration_sec: float,
        backend_key: str,
        voiced_threshold: float,
        min_note_duration: float,
        min_voiced_frames: int,
        jump_threshold: float,
        smoothing_window: int,
        frame_hop_sec: float,
        dp_summary: dict[str, object],
    ) -> Note | None:
        seg_mask = voiced[start_idx : end_idx + 1] & np.isfinite(midi_smoothed[start_idx : end_idx + 1])
        voiced_count = int(np.sum(seg_mask))
        if voiced_count <= 0:
            return None

        seg_midi = midi_smoothed[start_idx : end_idx + 1][seg_mask]
        seg_conf = confidences[start_idx : end_idx + 1][seg_mask]
        if seg_midi.size == 0:
            return None

        avg_conf = float(np.mean(seg_conf)) if seg_conf.size > 0 else 0.0
        median_midi = float(np.median(seg_midi))
        mad_semitones = self._median_absolute_deviation(seg_midi, median_midi)
        span_semitones = self._pitch_span(seg_midi)
        stability_factor = self._stability_factor(mad_semitones, backend=backend_key)
        span_factor = self._span_factor(span_semitones, backend=backend_key)
        quality_factor = max(0.0, min(1.0, 0.55 * stability_factor + 0.45 * span_factor))
        legacy_adjusted_conf = avg_conf * (0.35 + 0.65 * quality_factor)
        adjusted_conf = avg_conf * (0.65 + 0.35 * quality_factor)

        start_time = max(0.0, float(times[start_idx]) - frame_hop_sec * 0.5)
        end_time = min(float(duration_sec), float(times[end_idx]) + frame_hop_sec * 0.5)
        if end_time <= start_time:
            return None

        pitch_midi = int(round(median_midi))
        reason_codes = [DP_VITERBI_SEGMENTATION]
        if int(dp_summary.get("merged_gap_count", 0) or 0) > 0:
            reason_codes.append(DP_SHORT_GAP_MERGED)
        if int(dp_summary.get("suppressed_spike_count", 0) or 0) > 0:
            reason_codes.append(DP_SHORT_SPIKE_SUPPRESSED)

        return Note(
            pitch=midi_to_note(pitch_midi),
            start_time=start_time,
            end_time=end_time,
            confidence=adjusted_conf,
            reason_codes=reason_codes,
            candidate_origin="rmvpe_dp_viterbi",
            segmentation_evidence={
                "backend": self._segmentation_backend(backend_key),
                "segmentation_strategy": "dp_viterbi",
                "source_reason_code": DP_VITERBI_SEGMENTATION,
                "start_frame_index": int(start_idx),
                "end_frame_index": int(end_idx),
                "voiced_frame_count": int(voiced_count),
                "frame_hop_sec": round(float(frame_hop_sec), 6),
                "avg_confidence": round(float(avg_conf), 6),
                "adjusted_confidence": round(float(adjusted_conf), 6),
                "legacy_adjusted_confidence": round(float(legacy_adjusted_conf), 6),
                "median_pitch_midi": round(float(median_midi), 6),
                "mad_semitones": round(float(mad_semitones), 6),
                "span_semitones": round(float(span_semitones), 6),
                "stability_factor": round(float(stability_factor), 6),
                "span_factor": round(float(span_factor), 6),
                "quality_factor": round(float(quality_factor), 6),
                "voiced_threshold": round(float(voiced_threshold), 6),
                "jump_threshold_semitones": round(float(jump_threshold), 6),
                "min_note_duration_sec": round(float(min_note_duration), 6),
                "min_voiced_frames": int(min_voiced_frames),
                "smoothing_window": int(smoothing_window),
                "dp_path_score": dp_summary.get("path_score"),
                "dp_state_changes": dp_summary.get("state_changes"),
                "dp_merged_gap_count": dp_summary.get("merged_gap_count"),
                "dp_suppressed_spike_count": dp_summary.get("suppressed_spike_count"),
                "dp_transition_penalty_total": dp_summary.get("transition_penalty_total"),
                "dp_raw_segment_count": dp_summary.get("raw_segment_count"),
                "dp_merged_segment_count": dp_summary.get("merged_segment_count"),
            },
        )

    def _dp_suppressed_spike_count(
        self,
        *,
        path: list[int | None],
        midi_smoothed: np.ndarray,
        confidences: np.ndarray,
        voiced_threshold: float,
        jump_threshold: float,
        max_unvoiced_gap_frames: int,
    ) -> int:
        count = 0
        idx = 0
        max_gap = max(1, max_unvoiced_gap_frames + 1)
        while idx < len(path):
            state = path[idx]
            observed = midi_smoothed[idx] if idx < midi_smoothed.size else np.nan
            confidence = confidences[idx] if idx < confidences.size else 0.0
            is_pitch_spike = (
                state is not None
                and np.isfinite(observed)
                and float(confidence) >= float(voiced_threshold)
                and abs(float(observed) - float(state)) >= float(jump_threshold)
            )
            is_rest_spike = path[idx] is None
            if not is_pitch_spike and not is_rest_spike:
                idx += 1
                continue

            start_idx = idx
            while idx < len(path):
                state = path[idx]
                observed = midi_smoothed[idx] if idx < midi_smoothed.size else np.nan
                confidence = confidences[idx] if idx < confidences.size else 0.0
                pitch_spike = (
                    state is not None
                    and np.isfinite(observed)
                    and float(confidence) >= float(voiced_threshold)
                    and abs(float(observed) - float(state)) >= float(jump_threshold)
                )
                rest_spike = state is None
                if not pitch_spike and not rest_spike:
                    break
                idx += 1
            end_idx = idx - 1
            if start_idx == 0 or idx >= len(path) or (end_idx - start_idx + 1) > max_gap:
                continue

            left_state = path[start_idx - 1]
            right_state = path[idx]
            if left_state is None or right_state is None or abs(int(left_state) - int(right_state)) > 1:
                continue

            patch_midi = midi_smoothed[start_idx : end_idx + 1]
            patch_conf = confidences[start_idx : end_idx + 1]
            valid = np.isfinite(patch_midi) & (patch_conf >= voiced_threshold)
            if not np.any(valid):
                continue
            if np.max(np.abs(patch_midi[valid] - float(left_state))) >= float(jump_threshold):
                count += 1
        return count

    def _dp_transition_penalty_total(self, path: list[int | None], *, jump_threshold: float) -> float:
        total = 0.0
        for idx in range(1, len(path)):
            score = self._dp_transition_score(path[idx - 1], path[idx], jump_threshold=jump_threshold)
            if score < 0.0:
                total += abs(float(score))
        return total

    @staticmethod
    def _increment_reason_count(counts: dict[str, int], reason_code: str) -> None:
        counts[reason_code] = int(counts.get(reason_code, 0)) + 1

    def _estimate_frame_hop_sec(self, times: np.ndarray) -> float:
        if times.size >= 2:
            diffs = np.diff(times)
            diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
            if diffs.size > 0:
                return float(np.median(diffs))
        return max(0.001, float(self.config.crepe_step_size_ms) / 1000.0)

    def _voiced_mask_from_frames(
        self,
        frequencies: np.ndarray,
        confidences: np.ndarray,
        *,
        backend: str | None = None,
    ) -> np.ndarray:
        backend_key = self._segmentation_backend(backend)
        voiced_threshold = max(
            0.0,
            min(
                1.0,
                self._segmentation_param(
                    backend_key,
                    rmvpe_name="rmvpe_vuv_threshold",
                    crepe_name="crepe_vuv_confidence_threshold",
                ),
            ),
        )
        voiced = (confidences >= voiced_threshold) & np.isfinite(frequencies) & (frequencies > 0.0)
        frame_hop_sec = max(
            0.001,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_step_size_ms",
                crepe_name="crepe_step_size_ms",
            )
            / 1000.0,
        )
        max_unvoiced_gap_frames = max(
            0,
            int(
                round(
                    max(
                        0.0,
                        self._segmentation_param(
                            backend_key,
                            rmvpe_name="rmvpe_max_unvoiced_gap_sec",
                            crepe_name="crepe_max_unvoiced_gap_sec",
                        ),
                    )
                    / max(frame_hop_sec, 1e-4)
                )
            ),
        )
        return self._bridge_short_unvoiced(voiced, max_gap_frames=max_unvoiced_gap_frames)

    def _build_vocal_activity_segments(
        self,
        *,
        times: np.ndarray,
        confidences: np.ndarray,
        voiced: np.ndarray,
        frame_hop_sec: float,
    ) -> list[dict[str, object]]:
        if times.size == 0:
            return []

        segments: list[dict[str, object]] = []
        start_idx = 0
        current_state = bool(voiced[0])

        for idx in range(1, times.size):
            state = bool(voiced[idx])
            if state == current_state:
                continue
            segments.append(
                self._build_vocal_activity_segment(
                    times=times,
                    confidences=confidences,
                    voiced=voiced,
                    start_idx=start_idx,
                    end_idx=idx - 1,
                    frame_hop_sec=frame_hop_sec,
                )
            )
            start_idx = idx
            current_state = state

        segments.append(
            self._build_vocal_activity_segment(
                times=times,
                confidences=confidences,
                voiced=voiced,
                start_idx=start_idx,
                end_idx=times.size - 1,
                frame_hop_sec=frame_hop_sec,
            )
        )
        return segments

    def _build_vocal_activity_segment(
        self,
        *,
        times: np.ndarray,
        confidences: np.ndarray,
        voiced: np.ndarray,
        start_idx: int,
        end_idx: int,
        frame_hop_sec: float,
    ) -> dict[str, object]:
        patch_voiced = voiced[start_idx : end_idx + 1]
        patch_conf = confidences[start_idx : end_idx + 1]
        state = "vocal" if bool(np.any(patch_voiced)) else "inactive"
        start_time = max(0.0, float(times[start_idx]) - (frame_hop_sec * 0.5))
        end_time = max(start_time, float(times[end_idx]) + (frame_hop_sec * 0.5))
        return {
            "start_time": round(start_time, 6),
            "end_time": round(end_time, 6),
            "state": state,
            "voiced_ratio": round(float(np.mean(patch_voiced.astype(float))), 6),
            "mean_confidence": round(float(np.mean(patch_conf)) if patch_conf.size > 0 else 0.0, 6),
            "analysis_info": {
                "frame_count": int(end_idx - start_idx + 1),
            },
        }

    @staticmethod
    def _median_absolute_deviation(values: np.ndarray, center: float) -> float:
        if values.size == 0:
            return 0.0
        return float(np.median(np.abs(values - center)))

    @staticmethod
    def _pitch_span(values: np.ndarray) -> float:
        if values.size == 0:
            return 0.0
        lo = float(np.percentile(values, 10))
        hi = float(np.percentile(values, 90))
        return max(0.0, hi - lo)

    def _stability_factor(self, mad_semitones: float, *, backend: str | None = None) -> float:
        backend_key = self._segmentation_backend(backend)
        good = max(
            1e-6,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_note_mad_good_semitones",
                crepe_name="crepe_note_mad_good_semitones",
            ),
        )
        bad = max(
            good + 1e-6,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_note_mad_bad_semitones",
                crepe_name="crepe_note_mad_bad_semitones",
            ),
        )
        if mad_semitones <= good:
            return 1.0
        if mad_semitones >= bad:
            return 0.0
        return max(0.0, min(1.0, (bad - mad_semitones) / (bad - good)))

    def _span_factor(self, span_semitones: float, *, backend: str | None = None) -> float:
        backend_key = self._segmentation_backend(backend)
        soft = max(
            1e-6,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_note_span_soft_semitones",
                crepe_name="crepe_note_span_soft_semitones",
            ),
        )
        hard = max(
            soft + 1e-6,
            self._segmentation_param(
                backend_key,
                rmvpe_name="rmvpe_note_span_hard_semitones",
                crepe_name="crepe_note_span_hard_semitones",
            ),
        )
        if span_semitones <= soft:
            return 1.0
        if span_semitones >= hard:
            return 0.0
        return max(0.0, min(1.0, (hard - span_semitones) / (hard - soft)))

    @staticmethod
    def _segmentation_backend(backend: str | None) -> str:
        value = str(backend or "").strip().lower()
        if value in {"rmvpe", "r-mvpe", "rvc-rmvpe"}:
            return "rmvpe"
        return "crepe"

    def _segmentation_param(self, backend: str | None, *, rmvpe_name: str, crepe_name: str) -> float:
        if self._segmentation_backend(backend) == "rmvpe":
            value = getattr(self.config, rmvpe_name, None)
            if value is not None:
                return float(value)
        return float(getattr(self.config, crepe_name))

    def _predict_with_torchcrepe(
        self,
        *,
        audio: np.ndarray,
        sample_rate: int,
        model_capacity: str,
        step_size_ms: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        import torch
        import torchcrepe

        model = "full" if model_capacity not in {"tiny", "small", "medium", "large", "full"} else model_capacity
        hop_length = max(1, int(round(sample_rate * (step_size_ms / 1000.0))))

        audio_tensor = torch.from_numpy(audio).float().unsqueeze(0)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        audio_tensor = audio_tensor.to(device)

        with torch.no_grad():
            pitch_hz, periodicity = torchcrepe.predict(
                audio_tensor,
                sample_rate,
                hop_length,
                fmin=32.7,
                fmax=1975.5,
                model=model,
                batch_size=1024,
                device=device,
                return_periodicity=True,
            )

        pitch = pitch_hz.squeeze(0).detach().cpu().numpy().astype(float)
        confidence = periodicity.squeeze(0).detach().cpu().numpy().astype(float)
        times = (np.arange(pitch.shape[0], dtype=float) * hop_length) / float(sample_rate)
        return times, pitch, confidence

    @staticmethod
    def _median_filter_nan(values: np.ndarray, *, window: int) -> np.ndarray:
        if window <= 1 or values.size == 0:
            return values.copy()

        if window % 2 == 0:
            window += 1

        half = window // 2
        filtered = values.copy()

        for idx in range(values.size):
            left = max(0, idx - half)
            right = min(values.size, idx + half + 1)
            patch = values[left:right]
            patch = patch[np.isfinite(patch)]
            if patch.size > 0:
                filtered[idx] = float(np.median(patch))

        return filtered

    @staticmethod
    def _bridge_short_unvoiced(voiced: np.ndarray, *, max_gap_frames: int) -> np.ndarray:
        if max_gap_frames <= 0 or voiced.size == 0:
            return voiced.astype(bool, copy=True)

        bridged = voiced.astype(bool, copy=True)
        idx = 0
        total = bridged.size

        while idx < total:
            if bridged[idx]:
                idx += 1
                continue

            gap_start = idx
            while idx < total and not bridged[idx]:
                idx += 1
            gap_end = idx

            gap_len = gap_end - gap_start
            if (
                gap_len <= max_gap_frames
                and gap_start > 0
                and gap_end < total
                and bridged[gap_start - 1]
                and bridged[gap_end]
            ):
                bridged[gap_start:gap_end] = True

        return bridged
