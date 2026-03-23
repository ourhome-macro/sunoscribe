from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from demucs.apply import apply_model

try:
    import torchaudio
except Exception:
    torchaudio = None  # 真正导入失败才置空

if torchaudio is not None:
    try:
        torchaudio.set_audio_backend("soundfile")
    except Exception:
        # 仅记录，不影响后续 torchaudio.load/save 使用
        pass

from .model_manager import DemucsModelManager, ModelManagerError

logger = logging.getLogger(__name__)


class SeparationError(RuntimeError):
    """Raised when Demucs inference fails."""


@dataclass(slots=True)
class SeparationResult:
    vocal_path: str
    accompaniment_path: str


# Global lock to avoid CPU overload under concurrent requests.
# On GPU we allow no lock by default (configurable).
_GLOBAL_CPU_LOCK = threading.Semaphore(1)


class VocalSeparator:
    def __init__(
        self,
        model_manager: Optional[DemucsModelManager] = None,
        cpu_max_concurrency: int = 1,
    ) -> None:
        self.model_manager = model_manager or DemucsModelManager()
        self.device = self.model_manager.selected_device
        self.model = self.model_manager.load_model()

        if cpu_max_concurrency < 1:
            raise ValueError("cpu_max_concurrency must be >= 1")
        self._cpu_lock = threading.Semaphore(cpu_max_concurrency)

    def separate(
        self,
        input_audio_path: str,
        output_dir: str,
        stem_prefix: str = "separated",
        sample_rate: int = 44_100,
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
                    "torchaudio is not installed. Please install torch+torchaudio in backend env."
                )

            if lock is not None:
                lock.acquire()
            else:
                # Keep symbol in use to avoid linter complaints for global lock definition.
                _ = _GLOBAL_CPU_LOCK

            waveform, sr = self._load_audio(str(src))
            waveform = self._normalize_channels(waveform)

            if sr != sample_rate:
                waveform = torchaudio.functional.resample(waveform, sr, sample_rate)
                sr = sample_rate

            # Demucs expects [batch, channels, time]
            mix = waveform.unsqueeze(0).to(self.device)

            with torch.no_grad():
                # apply_model returns [batch, stems, channels, time]
                stems = apply_model(self.model, mix, progress=False)[0]

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

            return SeparationResult(
                vocal_path=str(vocal_path),
                accompaniment_path=str(accompaniment_path),
            )
        except ModelManagerError:
            raise
        except Exception as exc:
            raise SeparationError(f"Failed during separation: {exc}") from exc
        finally:
            if lock is not None:
                lock.release()

    @staticmethod
    def _load_audio(path: str) -> tuple[torch.Tensor, int]:
        if torchaudio is not None:
            try:
                return torchaudio.load(path)
            except ImportError as exc:
                # Newer torchaudio may route decoding via torchcodec for some formats.
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
                "Failed to load audio: torchaudio unavailable or requires torchcodec, "
                "and soundfile is not installed. Please install soundfile (pip install soundfile)."
            ) from exc

        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as exc:
            raise SeparationError(f"Failed to read audio file via soundfile: {exc}") from exc

        # soundfile returns [time, channels], convert to [channels, time]
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
                "Failed to save audio: torchaudio unavailable or requires torchcodec, "
                "and soundfile is not installed. Please install soundfile (pip install soundfile)."
            ) from exc

        try:
            # [channels, time] -> [time, channels]
            data = waveform.detach().cpu().numpy().T
            sf.write(path, data, int(sample_rate), subtype="PCM_16")
        except Exception as exc:
            raise SeparationError(f"Failed to write audio file via soundfile: {exc}") from exc

    @staticmethod
    def _normalize_channels(waveform: torch.Tensor) -> torch.Tensor:
        # torchaudio returns [channels, time]
        if waveform.dim() != 2:
            raise SeparationError(f"Unexpected waveform shape: {tuple(waveform.shape)}")

        channels, _ = waveform.shape
        if channels == 1:
            return waveform.repeat(2, 1)
        if channels == 2:
            return waveform

        # For multi-channel audio, downmix to stereo by averaging.
        mono = waveform.mean(dim=0, keepdim=True)
        return mono.repeat(2, 1)
