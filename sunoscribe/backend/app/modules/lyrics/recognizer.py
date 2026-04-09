from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .config import WhisperLyricsConfig

logger = logging.getLogger(__name__)


class WhisperRecognizer:
    """Whisper 推理封装（单实例模型加载）。"""

    def __init__(self, config: WhisperLyricsConfig | None = None) -> None:
        self.config = config or WhisperLyricsConfig()

        try:
            import whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai-whisper 未安装，请先安装依赖后重试。"
            ) from exc

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
        """异步识别接口（内部线程化执行模型推理）。"""
        return await asyncio.to_thread(self._transcribe_sync, audio_path)


_recognizer_singleton: WhisperRecognizer | None = None


def get_recognizer(config: WhisperLyricsConfig | None = None) -> WhisperRecognizer:
    """获取全局单例识别器。"""
    global _recognizer_singleton
    if _recognizer_singleton is None:
        _recognizer_singleton = WhisperRecognizer(config=config)
    return _recognizer_singleton


def reset_recognizer_singleton() -> None:
    """测试辅助：重置单例。"""
    global _recognizer_singleton
    _recognizer_singleton = None
