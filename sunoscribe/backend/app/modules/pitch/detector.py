from __future__ import annotations

from pathlib import Path
from typing import List

from .config import PitchDetectionConfig
from .exceptions import (
    AudioTooLongError,
    PitchDetectionFailedError,
    PitchModelUnavailableError,
)
from .types import Note


class PitchDetector:
    """基于 basic-pitch 的音高检测器。"""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    def _validate_audio_length(self, audio_path: str) -> float:
        import librosa

        try:
            duration = librosa.get_duration(path=audio_path)
        except Exception as exc:
            raise PitchDetectionFailedError(f"读取音频时长失败: {exc}") from exc

        if duration > self.config.max_audio_length_sec:
            raise AudioTooLongError(
                f"音频时长 {duration:.2f}s 超过上限 {self.config.max_audio_length_sec:.2f}s"
            )
        return float(duration)

    def detect(self, audio_path: str) -> List[Note]:
        """
        返回原始音符序列（不做量化，不做小节切分）。
        """
        import librosa

        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise PitchDetectionFailedError(f"音频文件不存在: {audio_path}")

        self._validate_audio_length(audio_path)

        try:
            from basic_pitch.inference import predict
            from basic_pitch.note_creation import model_output_to_notes
        except Exception as exc:
            raise PitchModelUnavailableError(
                "无法导入 basic-pitch，请确认已安装 basic-pitch 及依赖。"
            ) from exc

        try:
            model_output, midi_data, note_events = predict(str(audio_file))
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
            raise PitchDetectionFailedError(f"basic-pitch 推理失败: {exc}") from exc

        notes: List[Note] = []
        for event in note_events:
            if len(event) < 4:
                continue
            start_time, end_time, pitch_midi, confidence = event[:4]
            if confidence < self.config.confidence_threshold:
                continue

            pitch_name = librosa.midi_to_note(int(round(pitch_midi)))
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
