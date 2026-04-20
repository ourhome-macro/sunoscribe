from __future__ import annotations

from pathlib import Path
from typing import List

import librosa
import numpy as np

from .config import PitchDetectionConfig
from .exceptions import (
    AudioTooLongError,
    PitchDetectionFailedError,
    PitchModelUnavailableError,
)
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
            duration = librosa.get_duration(path=audio_path)
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

            pitch_name = librosa.midi_to_note(int(round(float(pitch_midi))))
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
        except Exception as exc:
            raise PitchModelUnavailableError(
                "CREPE backend is unavailable. Install package `crepe` to enable pitch inference."
            ) from exc

        try:
            audio, sr = librosa.load(str(audio_file), sr=int(self.config.sample_rate), mono=True)
        except Exception as exc:
            raise PitchDetectionFailedError(f"failed to load audio for CREPE: {exc}") from exc

        if audio.size == 0:
            return []

        step_size = max(1, int(self.config.crepe_step_size_ms))
        model_capacity = str(self.config.crepe_model_capacity or "full").strip().lower()

        try:
            times, frequencies, confidences, _ = crepe.predict(
                audio,
                sr,
                viterbi=True,
                step_size=step_size,
                model_capacity=model_capacity,
                verbose=0,
            )
        except TypeError:
            # Keep compatibility with older crepe versions without `verbose` argument.
            try:
                times, frequencies, confidences, _ = crepe.predict(
                    audio,
                    sr,
                    viterbi=True,
                    step_size=step_size,
                    model_capacity=model_capacity,
                )
            except Exception as exc:
                raise PitchDetectionFailedError(f"CREPE inference failed: {exc}") from exc
        except Exception as exc:
            raise PitchDetectionFailedError(f"CREPE inference failed: {exc}") from exc

        time_arr = np.asarray(times, dtype=float).reshape(-1)
        freq_arr = np.asarray(frequencies, dtype=float).reshape(-1)
        conf_arr = np.asarray(confidences, dtype=float).reshape(-1)

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
            midi[hz_valid] = librosa.hz_to_midi(frequencies[hz_valid])

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
            if avg_conf < float(self.config.confidence_threshold):
                continue

            start_time = max(0.0, float(times[start_idx]) - frame_hop_sec * 0.5)
            end_time = min(float(duration_sec), float(times[end_idx]) + frame_hop_sec * 0.5)
            if (end_time - start_time) < min_note_duration:
                continue

            pitch_midi = int(round(float(np.median(seg_midi))))
            pitch_name = librosa.midi_to_note(pitch_midi)
            notes.append(
                Note(
                    pitch=pitch_name,
                    start_time=start_time,
                    end_time=end_time,
                    confidence=avg_conf,
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
