from __future__ import annotations

from .config import WhisperLyricsConfig
from .formatter import format_whisper_segments
from .recognizer import WhisperRecognizer, get_recognizer, reset_recognizer_singleton


async def recognize_lyrics(audio_path: str) -> list[dict]:
    """歌词识别入口：Whisper 转写 + 结果格式转换。"""
    raw = await get_recognizer().recognize(audio_path)
    return format_whisper_segments(raw)


__all__ = [
    "WhisperLyricsConfig",
    "WhisperRecognizer",
    "get_recognizer",
    "reset_recognizer_singleton",
    "format_whisper_segments",
    "recognize_lyrics",
]
