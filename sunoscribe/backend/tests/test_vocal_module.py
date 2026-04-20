from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace

import torch

from app.modules.vocal.model_manager import DemucsModelManager
from app.modules.vocal.separator import VocalSeparator


class _FakeModel:
    sources = ["drums", "bass", "other", "vocals"]

    def to(self, _device):
        return self

    def eval(self):
        return self

    def separate_tensor(self, mix: torch.Tensor) -> torch.Tensor:
        # mix: [1, 2, T]
        _, c, t = mix.shape
        stems = torch.zeros((1, 4, c, t), dtype=mix.dtype, device=mix.device)
        stems[:, 3, :, :] = 0.7  # vocals
        stems[:, 2, :, :] = 0.3  # other -> accompaniment component
        return stems


class TestVocalModule(unittest.TestCase):
    def test_model_manager_cache_dir_uses_pathlib_home_cache(self) -> None:
        manager = DemucsModelManager(model_name="htdemucs")
        expected = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
        self.assertEqual(manager.demucs_cache_dir, expected)

    def test_separator_outputs_two_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_wav = root / "in.wav"
            out_dir = root / "out"

            fake_wave = torch.randn(2, 3200)

            with patch("app.modules.vocal.model_manager.DemucsModelManager.load_model", return_value=_FakeModel()):
                separator = VocalSeparator(model_manager=DemucsModelManager(), backend="demucs")

            fake_torchaudio = SimpleNamespace(
                load=lambda _path: (fake_wave, 44100),
                save=lambda *_args, **_kwargs: None,
                functional=SimpleNamespace(
                    resample=lambda waveform, _src_sr, _dst_sr: waveform,
                ),
            )

            with patch("app.modules.vocal.separator.torchaudio", fake_torchaudio):
                with patch("app.modules.vocal.separator.torchaudio.save") as mocked_save:
                    input_wav.write_bytes(b"dummy")
                    result = separator.separate(str(input_wav), str(out_dir), stem_prefix="x")

            self.assertTrue(result.vocal_path.endswith("x_vocals.wav"))
            self.assertTrue(result.accompaniment_path.endswith("x_accompaniment.wav"))
            self.assertEqual(mocked_save.call_count, 2)


if __name__ == "__main__":
    unittest.main()
