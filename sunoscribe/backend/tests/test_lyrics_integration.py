import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_recognize_lyrics_integration(monkeypatch, tmp_path: Path) -> None:
    class _Model:
        def transcribe(self, audio_path: str, **kwargs):
            assert Path(audio_path).exists()
            assert kwargs["word_timestamps"] is False
            return {
                "segments": [
                    {"start": 0.0, "end": 0.9, "text": "  first line "},
                    {"start": 0.9, "end": 1.8, "text": "[音乐]"},
                    {"start": 1.8, "end": 2.7, "text": "second line"},
                ]
            }

    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=lambda _name: _Model()))

    lyrics_module = importlib.import_module("app.modules.lyrics")
    lyrics_module.reset_recognizer_singleton()

    audio = tmp_path / "demo.wav"
    audio.write_bytes(b"fake")

    got = await lyrics_module.recognize_lyrics(str(audio))

    assert got == [
        {"start": 0.0, "end": 0.9, "text": "first line"},
        {"start": 1.8, "end": 2.7, "text": "second line"},
    ]
