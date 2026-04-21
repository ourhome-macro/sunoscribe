from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import torch

logger = logging.getLogger(__name__)


class ModelManagerError(RuntimeError):
    """Raised when model loading or cache validation fails."""


class DemucsModelManager:
    """Manage Demucs model cache and loading."""

    def __init__(
        self,
        model_name: str = "htdemucs",
        cache_root: Optional[Path] = None,
        prefer_cuda: bool = True,
    ) -> None:
        self.model_name = model_name
        self.cache_root = cache_root or Path.home() / ".cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)

        self.prefer_cuda = prefer_cuda
        self._selected_device = self._detect_device(prefer_cuda=prefer_cuda)

    @property
    def selected_device(self) -> torch.device:
        return self._selected_device

    @property
    def demucs_cache_dir(self) -> Path:
        return self.cache_root / "torch" / "hub" / "checkpoints"

    def _detect_device(self, prefer_cuda: bool = True) -> torch.device:
        if prefer_cuda and torch.cuda.is_available():
            logger.info("Demucs device selected: cuda")
            return torch.device("cuda")

        logger.info("Demucs device selected: cpu")
        return torch.device("cpu")

    def has_cached_model(self) -> bool:
        ckpt_dir = self.demucs_cache_dir
        if not ckpt_dir.exists():
            return False

        matches = list(ckpt_dir.glob(f"*{self.model_name}*"))
        return len(matches) > 0

    def load_model(self):
        try:
            from demucs.pretrained import get_model
        except Exception as exc:
            raise ModelManagerError(
                "Demucs is not installed. Please install `demucs` in backend environment."
            ) from exc

        cache_hit = self.has_cached_model()
        if cache_hit:
            logger.info("Demucs cache detected under: %s", self.demucs_cache_dir)
        else:
            logger.warning(
                "Demucs cache not found under %s. First load may require network download.",
                self.demucs_cache_dir,
            )

        try:
            model = get_model(name=self.model_name)
            model.to(self._selected_device)
            model.eval()
            logger.info("Demucs model loaded: name=%s device=%s", self.model_name, self._selected_device)
            return model
        except Exception as exc:
            if not cache_hit:
                raise ModelManagerError(
                    "Failed to load Demucs model and no local cache detected. "
                    "Connect to network once to download model into cache."
                ) from exc
            raise ModelManagerError(f"Failed to load cached Demucs model: {exc}") from exc


class MdxNetModelManager:
    """Manage MDX-Net runtime and model loading."""

    def __init__(
        self,
        model_name: str = "UVR_MDXNET_Main.onnx",
        cache_root: Optional[Path] = None,
        prefer_cuda: bool = True,
    ) -> None:
        self.model_name = model_name
        self.cache_root = cache_root or (Path.home() / ".cache" / "sunoscribe")
        self.cache_root.mkdir(parents=True, exist_ok=True)

        self.prefer_cuda = prefer_cuda
        self._selected_device = self._detect_device(prefer_cuda=prefer_cuda)

    @property
    def selected_device(self) -> torch.device:
        return self._selected_device

    @property
    def mdx_cache_dir(self) -> Path:
        return self.cache_root / "mdxnet"

    def _detect_device(self, prefer_cuda: bool = True) -> torch.device:
        if prefer_cuda and torch.cuda.is_available():
            logger.info("MDX-Net device selected: cuda")
            return torch.device("cuda")

        logger.info("MDX-Net device selected: cpu")
        return torch.device("cpu")

    def has_cached_model(self) -> bool:
        model_dir = self.mdx_cache_dir
        if not model_dir.exists():
            return False
        return any(model_dir.glob(f"*{self.model_name}*"))

    def load_separator(self) -> Any:
        try:
            from audio_separator.separator import Separator
        except Exception as exc:
            raise ModelManagerError(
                "MDX-Net backend requires package `audio-separator`. "
                "Install it with `pip install audio-separator` (and matching onnxruntime)."
            ) from exc

        self.mdx_cache_dir.mkdir(parents=True, exist_ok=True)
        use_cuda = self._selected_device.type == "cuda"

        separator: Any | None = None
        ctor_errors: list[str] = []

        constructor_candidates = [
            {
                "output_format": "wav",
                "model_file_dir": str(self.mdx_cache_dir),
                "use_cuda": use_cuda,
            },
            {
                "model_file_dir": str(self.mdx_cache_dir),
                "use_cuda": use_cuda,
            },
            {
                "output_format": "wav",
                "model_file_dir": str(self.mdx_cache_dir),
            },
            {},
        ]

        for kwargs in constructor_candidates:
            try:
                separator = Separator(**kwargs)
                break
            except TypeError as exc:
                ctor_errors.append(str(exc))
                continue
            except Exception as exc:
                raise ModelManagerError(f"Failed to initialize MDX separator: {exc}") from exc

        if separator is None:
            raise ModelManagerError(
                "Failed to initialize MDX separator with known constructor signatures: "
                + " | ".join(ctor_errors[-2:])
            )

        load_errors: list[str] = []
        load_calls = [
            lambda: separator.load_model(model_filename=self.model_name),
            lambda: separator.load_model(model_name=self.model_name),
            lambda: separator.load_model(self.model_name),
        ]

        for call in load_calls:
            try:
                call()
                logger.info("MDX-Net model loaded: name=%s device=%s", self.model_name, self._selected_device)
                return separator
            except TypeError as exc:
                load_errors.append(str(exc))
                continue
            except Exception as exc:
                raise ModelManagerError(f"Failed to load MDX-Net model: {exc}") from exc

        raise ModelManagerError(
            "Failed to load MDX-Net model with known loader signatures: " + " | ".join(load_errors[-2:])
        )
