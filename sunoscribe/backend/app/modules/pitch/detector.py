from __future__ import annotations

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
from .note_utils import hz_to_midi, midi_to_note
from .types import Note


class PitchDetector:
    """Pitch detector with pluggable backends (CREPE / basic-pitch)."""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.backend_name = self._normalize_backend(self.config.pitch_backend)

    @staticmethod
    def _normalize_backend(raw: str) -> str:
        value = str(raw or "").strip().lower()
        if value in {"crepe", "basic-pitch"}:
            return value
        if value in {"basic_pitch", "basicpitch"}:
            return "basic-pitch"
        return "crepe"

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
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise PitchDetectionFailedError(f"audio file not found: {audio_path}")

        duration = self._validate_audio_length(audio_path)

        if self.backend_name == "basic-pitch":
            return self._detect_with_basic_pitch(audio_file)
        return self._detect_with_crepe(audio_file, duration_sec=duration)

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
        return notes

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
            return []

        time_arr = time_arr[:frame_count]
        freq_arr = freq_arr[:frame_count]
        conf_arr = conf_arr[:frame_count]

        return self._frames_to_notes(
            times=time_arr,
            frequencies=freq_arr,
            confidences=conf_arr,
            duration_sec=float(duration_sec),
        )

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
    ) -> List[Note]:
        voiced_threshold = max(0.0, min(1.0, float(self.config.crepe_vuv_confidence_threshold)))
        min_note_duration = max(0.01, float(self.config.crepe_min_note_duration_sec))
        min_voiced_frames = max(1, int(self.config.crepe_min_voiced_frames))
        jump_threshold = max(0.05, float(self.config.crepe_pitch_jump_semitones))
        smoothing_window = max(1, int(self.config.crepe_smoothing_window))

        frame_hop_sec = self._estimate_frame_hop_sec(times)
        max_unvoiced_gap_frames = max(
            0,
            int(round(max(0.0, float(self.config.crepe_max_unvoiced_gap_sec)) / max(frame_hop_sec, 1e-4))),
        )

        midi = np.full(frequencies.shape, np.nan, dtype=float)
        hz_valid = np.isfinite(frequencies) & (frequencies > 0.0)
        if np.any(hz_valid):
            midi[hz_valid] = hz_to_midi(frequencies[hz_valid])

        voiced = (confidences >= voiced_threshold) & np.isfinite(midi)
        voiced = self._bridge_short_unvoiced(voiced, max_gap_frames=max_unvoiced_gap_frames)

        midi_smoothed = self._median_filter_nan(midi, window=smoothing_window)

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
            stability_factor = self._stability_factor(mad_semitones)
            span_factor = self._span_factor(span_semitones)
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
                )
            )

        notes.sort(key=lambda n: (n.start_time, n.end_time))
        return notes

    def _estimate_frame_hop_sec(self, times: np.ndarray) -> float:
        if times.size >= 2:
            diffs = np.diff(times)
            diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
            if diffs.size > 0:
                return float(np.median(diffs))
        return max(0.001, float(self.config.crepe_step_size_ms) / 1000.0)

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

    def _stability_factor(self, mad_semitones: float) -> float:
        good = max(1e-6, float(self.config.crepe_note_mad_good_semitones))
        bad = max(good + 1e-6, float(self.config.crepe_note_mad_bad_semitones))
        if mad_semitones <= good:
            return 1.0
        if mad_semitones >= bad:
            return 0.0
        return max(0.0, min(1.0, (bad - mad_semitones) / (bad - good)))

    def _span_factor(self, span_semitones: float) -> float:
        soft = max(1e-6, float(self.config.crepe_note_span_soft_semitones))
        hard = max(soft + 1e-6, float(self.config.crepe_note_span_hard_semitones))
        if span_semitones <= soft:
            return 1.0
        if span_semitones >= hard:
            return 0.0
        return max(0.0, min(1.0, (hard - span_semitones) / (hard - soft)))

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
