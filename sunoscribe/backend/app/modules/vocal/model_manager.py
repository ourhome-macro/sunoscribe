from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import torch

logger = logging.getLogger(__name__)


class ModelManagerError(RuntimeError):
    """Raised when model loading or cache validation fails."""


class DemucsModelManager:
    """Manage Demucs model cache, download and loading strategy."""

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
        # Keep aligned with torch.hub default structure when possible.
        # Example: ~/.cache/torch/hub/checkpoints
        return self.cache_root / "torch" / "hub" / "checkpoints"

    def _detect_device(self, prefer_cuda: bool = True) -> torch.device:
        if prefer_cuda and torch.cuda.is_available():
            logger.info("Demucs device selected: cuda")
            return torch.device("cuda")

        logger.info("Demucs device selected: cpu")
        return torch.device("cpu")

    def has_cached_model(self) -> bool:
        """
        Heuristic cache check:
        - demucs downloads checkpoints under torch hub checkpoints directory.
        - file names may vary by release, so we use a model-name substring match.
        """
        ckpt_dir = self.demucs_cache_dir
        if not ckpt_dir.exists():
            return False

        matches = list(ckpt_dir.glob(f"*{self.model_name}*"))
        return len(matches) > 0

    def load_model(self):
        """
        Load Demucs pretrained model.

        Behavior:
        - If cache exists, load from local cache.
        - If cache missing, try to download once (requires network).
        - Always move model to selected device and eval mode.
        """
        try:
            from demucs.pretrained import get_model
        except Exception as exc:
            raise ModelManagerError(
                "Demucs is not installed. Please install demucs package in backend env."
            ) from exc

        cache_hit = self.has_cached_model()
        if cache_hit:
            logger.info("Demucs cache detected under: %s", self.demucs_cache_dir)
        else:
            logger.warning(
                "Demucs cache not found under %s. First load may need network to download model.",
                self.demucs_cache_dir,
            )

        try:
            model = get_model(name=self.model_name)
            model.to(self._selected_device)
            model.eval()
            logger.info(
                "Demucs model loaded: name=%s device=%s",
                self.model_name,
                self._selected_device,
            )
            return model
        except Exception as exc:
            if not cache_hit:
                raise ModelManagerError(
                    "Failed to load Demucs model and no local cache detected. "
                    "Please connect network once to download model into ~/.cache, then run offline."
                ) from exc
            raise ModelManagerError(f"Failed to load cached Demucs model: {exc}") from exc
