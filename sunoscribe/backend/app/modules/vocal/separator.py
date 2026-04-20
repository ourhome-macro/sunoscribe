from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import torch

try:
    from demucs.apply import apply_model as demucs_apply_model
except Exception:
    demucs_apply_model = None

try:
    import torchaudio
except Exception:
    torchaudio = None

if torchaudio is not None:
    try:
        torchaudio.set_audio_backend("soundfile")
    except Exception:
        pass

from .model_manager import DemucsModelManager, MdxNetModelManager, ModelManagerError

logger = logging.getLogger(__name__)


class SeparationError(RuntimeError):
    """Raised when source separation fails."""


@dataclass(slots=True)
class SeparationResult:
    vocal_path: str
    accompaniment_path: str


_GLOBAL_CPU_LOCK = threading.Semaphore(1)


class VocalSeparator:
    def __init__(
        self,
        model_manager: Optional[Any] = None,
        cpu_max_concurrency: int = 1,
        backend: str = "mdx-net",
    ) -> None:
        self.backend = self._normalize_backend(backend)

        if cpu_max_concurrency < 1:
            raise ValueError("cpu_max_concurrency must be >= 1")
        self._cpu_lock = threading.Semaphore(cpu_max_concurrency)

        if self.backend == "mdx-net":
            self.model_manager = model_manager or MdxNetModelManager()
            self.device = self.model_manager.selected_device
            self.model = None
            self._mdx_separator = self.model_manager.load_separator()
        elif self.backend == "demucs":
            self.model_manager = model_manager or DemucsModelManager()
            self.device = self.model_manager.selected_device
            self.model = self.model_manager.load_model()
            self._mdx_separator = None
        else:
            raise ValueError(f"unsupported backend: {backend}")

    @staticmethod
    def _normalize_backend(raw: str) -> str:
        value = str(raw or "").strip().lower()
        if value in {"mdx-net", "mdx", "mdxnet"}:
            return "mdx-net"
        if value in {"demucs", "htdemucs"}:
            return "demucs"
        return "mdx-net"

    def separate(
        self,
        input_audio_path: str,
        output_dir: str,
        stem_prefix: str = "separated",
        sample_rate: int = 44_100,
    ) -> SeparationResult:
        if self.backend == "mdx-net":
            return self._separate_with_mdx_net(
                input_audio_path=input_audio_path,
                output_dir=output_dir,
                stem_prefix=stem_prefix,
            )

        return self._separate_with_demucs(
            input_audio_path=input_audio_path,
            output_dir=output_dir,
            stem_prefix=stem_prefix,
            sample_rate=sample_rate,
        )

    def _separate_with_mdx_net(
        self,
        *,
        input_audio_path: str,
        output_dir: str,
        stem_prefix: str,
    ) -> SeparationResult:
        src = Path(input_audio_path)
        if not src.exists() or not src.is_file():
            raise SeparationError(f"Input audio file does not exist: {src}")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        vocal_path = out_dir / f"{stem_prefix}_vocals.wav"
        accompaniment_path = out_dir / f"{stem_prefix}_accompaniment.wav"
        raw_output_dir = out_dir / "_mdx_raw"
        raw_output_dir.mkdir(parents=True, exist_ok=True)

        lock = self._cpu_lock if self.device.type == "cpu" else None

        if lock is not None:
            lock.acquire()
        else:
            _ = _GLOBAL_CPU_LOCK

        try:
            result = self._invoke_mdx_separator(src=src, output_dir=raw_output_dir)
            candidates = self._collect_output_candidates(
                result,
                fallback=raw_output_dir.glob("**/*"),
                base_dir=raw_output_dir,
            )
            vocals_src, accompaniment_src = self._pick_mdx_stems(candidates)

            if vocals_src is None or accompaniment_src is None:
                raise SeparationError(
                    "MDX-Net output does not contain both vocals and accompaniment stems. "
                    f"candidates={[p.name for p in candidates]}"
                )

            shutil.copyfile(vocals_src, vocal_path)
            shutil.copyfile(accompaniment_src, accompaniment_path)

            logger.info(
                "MDX-Net separation completed: vocals=%s accompaniment=%s",
                vocal_path,
                accompaniment_path,
            )
            return SeparationResult(vocal_path=str(vocal_path), accompaniment_path=str(accompaniment_path))
        except ModelManagerError:
            raise
        except Exception as exc:
            raise SeparationError(f"Failed during MDX-Net separation: {exc}") from exc
        finally:
            if lock is not None:
                lock.release()

    def _invoke_mdx_separator(self, *, src: Path, output_dir: Path) -> Any:
        separator = self._mdx_separator
        if separator is None:
            raise SeparationError("MDX separator is not initialized")

        if hasattr(separator, "output_dir"):
            try:
                setattr(separator, "output_dir", str(output_dir))
            except Exception:
                pass

        errors: list[str] = []
        call_candidates = [
            lambda: separator.separate(str(src)),
            lambda: separator.separate(audio_file=str(src)),
            lambda: separator.separate(audio_path=str(src)),
            lambda: separator.separate(str(src), output_dir=str(output_dir)),
            lambda: separator.separate(audio_file=str(src), output_dir=str(output_dir)),
            lambda: separator.separate(audio_path=str(src), output_dir=str(output_dir)),
        ]

        for call in call_candidates:
            try:
                return call()
            except TypeError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:
                raise SeparationError(f"MDX separator runtime failed: {exc}") from exc

        raise SeparationError(
            "Unable to call MDX separator with known signatures: " + " | ".join(errors[-2:])
        )

    def _collect_output_candidates(
        self,
        result: Any,
        *,
        fallback: Iterable[Path],
        base_dir: Path,
    ) -> list[Path]:
        candidates: list[Path] = []

        def append_path(raw: Any) -> None:
            if raw is None:
                return
            if isinstance(raw, Path):
                candidates.append(raw)
                return
            if isinstance(raw, str) and raw.strip():
                candidates.append(Path(raw.strip()))

        def walk(node: Any) -> None:
            if node is None:
                return
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, (list, tuple, set)):
                for item in node:
                    walk(item)
                return
            append_path(node)

        walk(result)
        for p in fallback:
            append_path(p)

        normalized: list[Path] = []
        seen: set[str] = set()
        allowed_suffixes = {".wav", ".flac", ".mp3", ".m4a", ".ogg"}

        for path in candidates:
            try:
                if path.is_absolute():
                    resolved = path
                else:
                    resolved = (base_dir / path).resolve()
            except Exception:
                resolved = path
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            if not resolved.exists() or not resolved.is_file():
                continue
            if resolved.suffix.lower() not in allowed_suffixes:
                continue
            normalized.append(resolved)

        return normalized

    def _pick_mdx_stems(self, candidates: list[Path]) -> tuple[Path | None, Path | None]:
        if not candidates:
            return None, None

        vocals_keys = ("vocal", "vocals", "voice", "acapella")
        accompaniment_keys = ("instrumental", "inst", "accompaniment", "karaoke", "no_vocals", "music")

        vocals: Path | None = None
        accompaniment: Path | None = None

        for path in candidates:
            name = path.name.lower()
            if vocals is None and any(k in name for k in vocals_keys):
                vocals = path
                continue
            if accompaniment is None and any(k in name for k in accompaniment_keys):
                accompaniment = path

        if vocals is not None and accompaniment is not None:
            return vocals, accompaniment

        if len(candidates) == 2:
            first, second = candidates
            first_name = first.name.lower()
            second_name = second.name.lower()

            if any(k in first_name for k in vocals_keys):
                return first, second
            if any(k in second_name for k in vocals_keys):
                return second, first

            # Fallback heuristic: choose larger file as accompaniment.
            if first.stat().st_size >= second.stat().st_size:
                return second, first
            return first, second

        return vocals, accompaniment

    def _separate_with_demucs(
        self,
        *,
        input_audio_path: str,
        output_dir: str,
        stem_prefix: str,
        sample_rate: int,
    ) -> SeparationResult:
        src = Path(input_audio_path)
        if not src.exists() or not src.is_file():
            raise SeparationError(f"Input audio file does not exist: {src}")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        vocal_path = out_dir / f"{stem_prefix}_vocals.wav"
        accompaniment_path = out_dir / f"{stem_prefix}_accompaniment.wav"

        logger.info("Demucs separation started: input=%s device=%s", src, self.device)

        lock = self._cpu_lock if self.device.type == "cpu" else None
        if lock is not None:
            logger.info("CPU mode detected, waiting for inference slot...")

        try:
            if torchaudio is None:
                raise SeparationError(
                    "torchaudio is not installed. Please install torch+torchaudio in backend environment."
                )
            if demucs_apply_model is None:
                raise SeparationError("demucs runtime is not installed. Please install `demucs` package.")

            if lock is not None:
                lock.acquire()
            else:
                _ = _GLOBAL_CPU_LOCK

            waveform, sr = self._load_audio(str(src))
            waveform = self._normalize_channels(waveform)

            if sr != sample_rate:
                waveform = torchaudio.functional.resample(waveform, sr, sample_rate)
                sr = sample_rate

            mix = waveform.unsqueeze(0).to(self.device)

            with torch.no_grad():
                stems = demucs_apply_model(self.model, mix, progress=False)[0]

            source_names = list(getattr(self.model, "sources", []))
            if not source_names:
                raise SeparationError("Demucs model does not expose sources metadata.")

            stem_map = {name: stems[idx].detach().cpu() for idx, name in enumerate(source_names)}

            if "vocals" not in stem_map:
                raise SeparationError(f"Demucs sources does not include vocals: {source_names}")

            vocals = stem_map["vocals"]
            accompaniment = torch.zeros_like(vocals)
            for name, tensor in stem_map.items():
                if name != "vocals":
                    accompaniment = accompaniment + tensor

            self._save_audio(str(vocal_path), vocals, sr)
            self._save_audio(str(accompaniment_path), accompaniment, sr)

            logger.info(
                "Demucs separation completed: vocals=%s accompaniment=%s",
                vocal_path,
                accompaniment_path,
            )

            return SeparationResult(vocal_path=str(vocal_path), accompaniment_path=str(accompaniment_path))
        except ModelManagerError:
            raise
        except Exception as exc:
            raise SeparationError(f"Failed during Demucs separation: {exc}") from exc
        finally:
            if lock is not None:
                lock.release()

    @staticmethod
    def _load_audio(path: str) -> tuple[torch.Tensor, int]:
        if torchaudio is not None:
            try:
                return torchaudio.load(path)
            except ImportError as exc:
                if "TorchCodec" not in str(exc) and "torchcodec" not in str(exc).lower():
                    raise
                logger.warning(
                    "torchaudio.load requires torchcodec for this file, falling back to soundfile: %s",
                    path,
                )

        try:
            import soundfile as sf
        except Exception as exc:
            raise SeparationError(
                "Failed to load audio: torchaudio unavailable or requires torchcodec, and soundfile is not installed."
            ) from exc

        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as exc:
            raise SeparationError(f"Failed to read audio via soundfile: {exc}") from exc

        waveform = torch.from_numpy(np.asarray(data).T)
        return waveform, int(sr)

    @staticmethod
    def _save_audio(path: str, waveform: torch.Tensor, sample_rate: int) -> None:
        if torchaudio is not None:
            try:
                torchaudio.save(path, waveform, sample_rate=sample_rate)
                return
            except ImportError as exc:
                if "TorchCodec" not in str(exc) and "torchcodec" not in str(exc).lower():
                    raise
                logger.warning(
                    "torchaudio.save requires torchcodec for this file, falling back to soundfile: %s",
                    path,
                )

        try:
            import soundfile as sf
        except Exception as exc:
            raise SeparationError(
                "Failed to save audio: torchaudio unavailable or requires torchcodec, and soundfile is not installed."
            ) from exc

        try:
            data = waveform.detach().cpu().numpy().T
            sf.write(path, data, int(sample_rate), subtype="PCM_16")
        except Exception as exc:
            raise SeparationError(f"Failed to write audio via soundfile: {exc}") from exc

    @staticmethod
    def _normalize_channels(waveform: torch.Tensor) -> torch.Tensor:
        if waveform.dim() != 2:
            raise SeparationError(f"Unexpected waveform shape: {tuple(waveform.shape)}")

        channels, _ = waveform.shape
        if channels == 1:
            return waveform.repeat(2, 1)
        if channels == 2:
            return waveform

        mono = waveform.mean(dim=0, keepdim=True)
        return mono.repeat(2, 1)
