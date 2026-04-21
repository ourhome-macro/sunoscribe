import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class _DummyModel:
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, audio_path: str, **kwargs):
        self.calls.append((audio_path, kwargs))
        return {
            "segments": [
                {"start": 0.0, "end": 1.1, "text": "line one"},
                {"start": 1.1, "end": 2.0, "text": "[音乐]"},
            ]
        }


@pytest.mark.asyncio
async def test_recognizer_async_and_singleton(monkeypatch, tmp_path: Path) -> None:
    dummy_model = _DummyModel()

    def _fake_load_model(name: str):
        assert name == "medium"
        return dummy_model

    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=_fake_load_model))

    module = importlib.import_module("app.modules.lyrics.recognizer")
    module.reset_recognizer_singleton()

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake-wav")

    to_thread_called = {"ok": False}
    original_to_thread = asyncio.to_thread

    async def _fake_to_thread(func, *args, **kwargs):
        to_thread_called["ok"] = True
        return func(*args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", _fake_to_thread)

    recognizer1 = module.get_recognizer()
    recognizer2 = module.get_recognizer()
    assert recognizer1 is recognizer2

    result = await recognizer1.recognize(str(audio_path))

    assert to_thread_called["ok"] is True
    assert isinstance(result, dict)
    assert len(dummy_model.calls) == 1
    called_audio, called_kwargs = dummy_model.calls[0]
    assert called_audio == str(audio_path)
    assert called_kwargs["word_timestamps"] is False

    monkeypatch.setattr(module.asyncio, "to_thread", original_to_thread)


def test_get_recognizer_reloads_when_explicit_config_changes(monkeypatch) -> None:
    loaded_models: list[str] = []

    class _Model:
        def transcribe(self, audio_path: str, **kwargs):
            return {"audio_path": audio_path, "kwargs": kwargs}

    def _fake_load_model(name: str):
        loaded_models.append(name)
        return _Model()

    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=_fake_load_model))

    module = importlib.import_module("app.modules.lyrics.recognizer")
    module.reset_recognizer_singleton()

    r1 = module.get_recognizer()
    r2 = module.get_recognizer()
    assert r1 is r2

    r3 = module.get_recognizer(module.WhisperLyricsConfig(model_name="small"))
    assert r3 is not r1

    r4 = module.get_recognizer(module.WhisperLyricsConfig(model_name="small"))
    assert r4 is r3

    assert loaded_models == ["medium", "small"]
