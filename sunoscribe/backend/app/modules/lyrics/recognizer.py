from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import threading
from typing import Any

from .config import WhisperLyricsConfig

logger = logging.getLogger(__name__)


class WhisperRecognizer:
    """Whisper inference wrapper with lazy singleton support."""

    def __init__(self, config: WhisperLyricsConfig | None = None) -> None:
        self.config = config or WhisperLyricsConfig()

        try:
            import whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError("openai-whisper is not installed. Please install dependencies first.") from exc

        logger.info("Loading whisper model: %s", self.config.model_name)
        self._model = whisper.load_model(self.config.model_name)

    def _transcribe_sync(self, audio_path: str) -> dict[str, Any]:
        path = Path(audio_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        options = self.config.transcribe_options()
        logger.info("Running whisper transcribe: %s", path)
        result = self._model.transcribe(str(path), **options)
        if not isinstance(result, dict):
            raise RuntimeError("Whisper transcribe result must be a dict.")
        return result

    async def recognize(self, audio_path: str) -> dict[str, Any]:
        """Async recognize API backed by thread offloading."""
        return await asyncio.to_thread(self._transcribe_sync, audio_path)


_recognizer_singleton: WhisperRecognizer | None = None
_recognizer_signature: tuple[Any, ...] | None = None
_recognizer_lock = threading.Lock()


def _config_signature(config: WhisperLyricsConfig) -> tuple[Any, ...]:
    return (
        str(config.model_name),
        config.language,
        str(config.task),
        bool(config.word_timestamps),
        bool(config.fp16),
    )


def get_recognizer(config: WhisperLyricsConfig | None = None) -> WhisperRecognizer:
    """Get global recognizer singleton, reloading when explicit config changes."""
    global _recognizer_singleton, _recognizer_signature

    requested_config = config or WhisperLyricsConfig()
    requested_signature = _config_signature(requested_config)

    current = _recognizer_singleton
    if current is not None and (config is None or _recognizer_signature == requested_signature):
        return current

    with _recognizer_lock:
        if _recognizer_singleton is None:
            _recognizer_singleton = WhisperRecognizer(config=requested_config)
            _recognizer_signature = requested_signature
            return _recognizer_singleton

        if config is None:
            return _recognizer_singleton

        if _recognizer_signature != requested_signature:
            logger.info(
                "Reloading whisper model due to config change: %s -> %s",
                _recognizer_signature,
                requested_signature,
            )
            _recognizer_singleton = WhisperRecognizer(config=requested_config)
            _recognizer_signature = requested_signature

        return _recognizer_singleton


def reset_recognizer_singleton() -> None:
    """Test helper: reset singleton state."""
    global _recognizer_singleton, _recognizer_signature
    with _recognizer_lock:
        _recognizer_singleton = None
        _recognizer_signature = None
