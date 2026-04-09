from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WhisperLyricsConfig:
    """Whisper 歌词识别配置。"""

    model_name: str = "medium"
    language: str | None = None  # None 表示自动语言检测
    task: str = "transcribe"
    word_timestamps: bool = False
    fp16: bool = False

    def transcribe_options(self) -> dict[str, Any]:
        """转换为 whisper.transcribe 所需参数。"""
        return {
            "language": self.language,
            "task": self.task,
            "word_timestamps": self.word_timestamps,
            "fp16": self.fp16,
        }
