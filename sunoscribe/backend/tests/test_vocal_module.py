from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace

import torch

from app.modules.vocal.model_manager import DemucsModelManager
from app.modules.vocal.separator import SeparationError, VocalSeparator


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

            with patch(
                "app.modules.vocal.separator.demucs_apply_model",
                side_effect=lambda model, mix, progress=False: model.separate_tensor(mix),
            ), patch("app.modules.vocal.separator.torchaudio", fake_torchaudio):
                with patch("app.modules.vocal.separator.torchaudio.save") as mocked_save:
                    input_wav.write_bytes(b"dummy")
                    result = separator.separate(str(input_wav), str(out_dir), stem_prefix="x")

            self.assertTrue(result.vocal_path.endswith("x_vocals.wav"))
            self.assertTrue(result.accompaniment_path.endswith("x_accompaniment.wav"))
            self.assertIn("drums", result.stem_paths)
            self.assertIn("bass", result.stem_paths)
            self.assertIn("other", result.stem_paths)
            self.assertIn("accompaniment", result.stem_paths)
            self.assertEqual(mocked_save.call_count, 5)

    def test_mdx_separator_falls_back_to_output_dir_cwd_for_legacy_signature(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_wav = root / "source.wav"
            out_dir = root / "out"
            input_wav.write_bytes(b"dummy")

            class _LegacySeparator:
                def separate(self, audio_path, output_dir=None):
                    if output_dir is not None:
                        raise TypeError("legacy signature")
                    Path("source_(Vocals)_UVR_MDXNET_Main.wav").write_bytes(b"vocals")
                    Path("source_(Instrumental)_UVR_MDXNET_Main.wav").write_bytes(b"instrumental")
                    return []

            class _Manager:
                selected_device = torch.device("cpu")

                def load_separator(self):
                    return _LegacySeparator()

            separator = VocalSeparator(model_manager=_Manager(), backend="mdx-net")
            result = separator.separate(str(input_wav), str(out_dir), stem_prefix="x")

            self.assertTrue(Path(result.vocal_path).exists())
            self.assertTrue(Path(result.accompaniment_path).exists())
            self.assertTrue(result.vocal_path.endswith("x_vocals.wav"))
            self.assertTrue(result.accompaniment_path.endswith("x_accompaniment.wav"))
            self.assertFalse((root / "source_(Vocals)_UVR_MDXNET_Main.wav").exists())

    def test_mdx_separator_runs_output_dir_signature_inside_output_dir(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_wav = root / "source.wav"
            out_dir = root / "out"
            input_wav.write_bytes(b"dummy")

            class _OutputDirSeparator:
                def separate(self, audio_path, output_dir=None):
                    Path("source_(Vocals)_UVR_MDXNET_Main.wav").write_bytes(b"vocals")
                    Path("source_(Instrumental)_UVR_MDXNET_Main.wav").write_bytes(b"instrumental")
                    return []

            class _Manager:
                selected_device = torch.device("cpu")

                def load_separator(self):
                    return _OutputDirSeparator()

            separator = VocalSeparator(model_manager=_Manager(), backend="mdx-net")
            result = separator.separate(str(input_wav), str(out_dir), stem_prefix="x")

            self.assertTrue(Path(result.vocal_path).exists())
            self.assertTrue(Path(result.accompaniment_path).exists())
            self.assertTrue(result.vocal_path.endswith("x_vocals.wav"))
            self.assertTrue(result.accompaniment_path.endswith("x_accompaniment.wav"))
            self.assertFalse((root / "source_(Vocals)_UVR_MDXNET_Main.wav").exists())

    def test_mdx_separator_collects_fresh_outputs_from_current_working_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_wav = root / "source.wav"
            out_dir = root / "out"
            input_wav.write_bytes(b"dummy")
            stale_vocals = root / "source_(Vocals)_UVR_MDXNET_Main.wav"
            stale_vocals.write_bytes(b"stale")

            class _CwdSeparator:
                def __init__(self, cwd: Path):
                    self.cwd = cwd

                def separate(self, audio_path, output_dir=None):
                    (self.cwd / "source_(Vocals)_UVR_MDXNET_Main.wav").write_bytes(b"fresh vocals")
                    (self.cwd / "source_(Instrumental)_UVR_MDXNET_Main.wav").write_bytes(b"fresh instrumental")
                    return []

            class _Manager:
                selected_device = torch.device("cpu")

                def load_separator(self):
                    return _CwdSeparator(root)

            separator = VocalSeparator(model_manager=_Manager(), backend="mdx-net")
            previous_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                result = separator.separate(str(input_wav), str(out_dir), stem_prefix="x")
            finally:
                os.chdir(previous_cwd)

            self.assertTrue(Path(result.vocal_path).exists())
            self.assertTrue(Path(result.accompaniment_path).exists())
            self.assertEqual(Path(result.vocal_path).read_bytes(), b"fresh vocals")

    def test_mdx_stem_discovery_identifies_top_level_vocals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "out"
            output_dir.mkdir()
            vocals = output_dir / "vocals.wav"
            vocals.write_bytes(b"vocals")

            candidates = VocalSeparator._collect_output_candidates(
                VocalSeparator.__new__(VocalSeparator),
                None,
                fallback=[],
                base_dir=output_dir,
                scan_dirs=[output_dir],
            )
            stem_map = VocalSeparator._pick_mdx_stem_map(VocalSeparator.__new__(VocalSeparator), candidates)

            self.assertEqual(stem_map.get("vocals"), vocals.resolve(strict=False))

    def test_mdx_stem_discovery_recurses_for_capitalized_vocals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "out"
            nested = output_dir / "song"
            nested.mkdir(parents=True)
            vocals = nested / "Vocals.wav"
            vocals.write_bytes(b"vocals")

            candidates = VocalSeparator._collect_output_candidates(
                VocalSeparator.__new__(VocalSeparator),
                None,
                fallback=[],
                base_dir=output_dir,
                scan_dirs=[output_dir],
            )
            stem_map = VocalSeparator._pick_mdx_stem_map(VocalSeparator.__new__(VocalSeparator), candidates)

            self.assertEqual(stem_map.get("vocals"), vocals.resolve(strict=False))

    def test_mdx_stem_discovery_does_not_treat_no_vocals_as_vocals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "out"
            output_dir.mkdir()
            no_vocals = output_dir / "no_vocals.wav"
            no_vocals.write_bytes(b"instrumental")

            candidates = VocalSeparator._collect_output_candidates(
                VocalSeparator.__new__(VocalSeparator),
                None,
                fallback=[],
                base_dir=output_dir,
                scan_dirs=[output_dir],
            )
            stem_map = VocalSeparator._pick_mdx_stem_map(VocalSeparator.__new__(VocalSeparator), candidates)

            self.assertNotIn("vocals", stem_map)
            self.assertEqual(stem_map.get("accompaniment"), no_vocals.resolve(strict=False))

    def test_mdx_empty_output_error_includes_scanned_directories_and_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_wav = root / "source.wav"
            out_dir = root / "out"
            input_wav.write_bytes(b"dummy")

            class _EmptySeparator:
                def separate(self, audio_path, output_dir=None):
                    return []

            class _Manager:
                selected_device = torch.device("cpu")

                def load_separator(self):
                    return _EmptySeparator()

            separator = VocalSeparator(model_manager=_Manager(), backend="mdx-net")
            with self.assertRaises(SeparationError) as raised:
                separator.separate(str(input_wav), str(out_dir), stem_prefix="x")

            message = str(raised.exception)
            self.assertIn("mdx_net_produced_no_audio_files", message)
            self.assertIn("candidates=[]", message)
            self.assertIn(str(out_dir.resolve(strict=False)), message)
            diagnostics = out_dir / "mdx_diagnostics.json"
            self.assertTrue(diagnostics.exists())

    def test_prepare_waveform_for_save_limited_to_target_peak(self) -> None:
        waveform = torch.tensor([[2.0, -2.0, 0.5], [1.5, -1.5, 0.25]], dtype=torch.float32)
        prepared = VocalSeparator._prepare_waveform_for_save(waveform)

        self.assertLessEqual(float(prepared.abs().max()), 1.0)
        self.assertAlmostEqual(float(prepared.abs().max()), 0.98, places=3)


if __name__ == "__main__":
    unittest.main()
