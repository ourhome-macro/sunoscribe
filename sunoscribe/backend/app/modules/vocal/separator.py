from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
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
STEM_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")


class SeparationError(RuntimeError):
    """Raised when source separation fails."""


@dataclass(slots=True)
class SeparationResult:
    stem_paths: dict[str, str] = field(default_factory=dict)

    @property
    def vocal_path(self) -> str | None:
        return self.stem_paths.get("vocals")

    @property
    def vocals_path(self) -> str | None:
        return self.vocal_path

    @property
    def accompaniment_path(self) -> str | None:
        return self.stem_paths.get("accompaniment")


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
        raw_output_dir = out_dir / "_mdx_raw"
        raw_output_dir.mkdir(parents=True, exist_ok=True)

        cpu_locks: list[threading.Semaphore] = []
        if self.device.type == "cpu":
            cpu_locks = [_GLOBAL_CPU_LOCK, self._cpu_lock]
            for lock in cpu_locks:
                lock.acquire()

        try:
            fallback_snapshot = self._snapshot_mdx_fallback_outputs(source_stem=src.stem, raw_output_dir=raw_output_dir)
            result = self._invoke_mdx_separator(src=src, output_dir=raw_output_dir)
            candidates = self._collect_output_candidates(
                result,
                fallback=self._iter_mdx_fallback_outputs(
                    source_stem=src.stem,
                    raw_output_dir=raw_output_dir,
                    before=fallback_snapshot,
                ),
                base_dir=raw_output_dir,
            )
            stem_sources = self._pick_mdx_stem_map(candidates)

            if stem_sources.get("vocals") is None:
                raise SeparationError(
                    "MDX-Net output does not contain a vocals stem. "
                    f"candidates={[p.name for p in candidates]}"
                )

            if stem_sources.get("accompaniment") is None:
                accompaniment_mix_sources = [
                    stem_sources.get(name)
                    for name in ("drums", "bass", "other")
                    if stem_sources.get(name) is not None
                ]
                if accompaniment_mix_sources:
                    accompaniment_path = out_dir / f"{stem_prefix}_accompaniment.wav"
                    self._mix_audio_files(accompaniment_mix_sources, accompaniment_path)
                    stem_sources["accompaniment"] = accompaniment_path

            if stem_sources.get("accompaniment") is None:
                raise SeparationError(
                    "MDX-Net output does not contain accompaniment-compatible stems. "
                    f"candidates={[p.name for p in candidates]}"
                )

            persisted_stems = self._persist_named_stems(stem_sources, out_dir=out_dir, stem_prefix=stem_prefix)

            logger.info(
                "MDX-Net separation completed: stems=%s",
                persisted_stems,
            )
            return SeparationResult(stem_paths={name: str(path) for name, path in persisted_stems.items()})
        except ModelManagerError:
            raise
        except Exception as exc:
            raise SeparationError(f"Failed during MDX-Net separation: {exc}") from exc
        finally:
            for lock in reversed(cpu_locks):
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
            lambda: self._invoke_mdx_separator_in_output_dir(
                lambda: separator.separate(str(src), output_dir=str(output_dir)), output_dir
            ),
            lambda: self._invoke_mdx_separator_in_output_dir(
                lambda: separator.separate(audio_file=str(src), output_dir=str(output_dir)), output_dir
            ),
            lambda: self._invoke_mdx_separator_in_output_dir(
                lambda: separator.separate(audio_path=str(src), output_dir=str(output_dir)), output_dir
            ),
            lambda: self._invoke_mdx_separator_in_output_dir(lambda: separator.separate(str(src)), output_dir),
            lambda: self._invoke_mdx_separator_in_output_dir(lambda: separator.separate(audio_file=str(src)), output_dir),
            lambda: self._invoke_mdx_separator_in_output_dir(lambda: separator.separate(audio_path=str(src)), output_dir),
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

    @staticmethod
    def _invoke_mdx_separator_in_output_dir(call: Any, output_dir: Path) -> Any:
        previous_cwd = Path.cwd()
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chdir(output_dir)
            return call()
        finally:
            os.chdir(previous_cwd)

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

    @staticmethod
    def _snapshot_mdx_fallback_outputs(*, source_stem: str, raw_output_dir: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in VocalSeparator._iter_mdx_candidate_locations(source_stem=source_stem, raw_output_dir=raw_output_dir):
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[str(path.resolve(strict=False))] = (int(stat.st_mtime_ns), int(stat.st_size))
        return snapshot

    @staticmethod
    def _iter_mdx_fallback_outputs(
        *,
        source_stem: str,
        raw_output_dir: Path,
        before: dict[str, tuple[int, int]],
    ) -> Iterable[Path]:
        for path in raw_output_dir.glob("**/*"):
            yield path

        for path in VocalSeparator._iter_mdx_candidate_locations(source_stem=source_stem, raw_output_dir=raw_output_dir):
            key = str(path.resolve(strict=False))
            try:
                stat = path.stat()
            except OSError:
                continue
            current = (int(stat.st_mtime_ns), int(stat.st_size))
            if before.get(key) != current:
                yield path

    @staticmethod
    def _iter_mdx_candidate_locations(*, source_stem: str, raw_output_dir: Path) -> Iterable[Path]:
        allowed_suffixes = {".wav", ".flac", ".mp3", ".m4a", ".ogg"}
        candidate_dirs = [raw_output_dir, Path.cwd()]
        seen_dirs: set[str] = set()
        safe_source_stem = str(source_stem or "").strip()
        patterns = [f"{safe_source_stem}*", "*Vocals*", "*Instrumental*"] if safe_source_stem else ["*Vocals*", "*Instrumental*"]

        for directory in candidate_dirs:
            key = str(directory.resolve(strict=False))
            if key in seen_dirs or not directory.exists() or not directory.is_dir():
                continue
            seen_dirs.add(key)
            for pattern in patterns:
                for path in directory.glob(pattern):
                    if path.is_file() and path.suffix.lower() in allowed_suffixes:
                        yield path

    def _pick_mdx_stem_map(self, candidates: list[Path]) -> dict[str, Path]:
        if not candidates:
            return {}

        keyword_map = {
            "vocals": ("vocal", "vocals", "voice", "acapella"),
            "drums": ("drum", "drums", "percussion"),
            "bass": ("bass",),
            "other": ("other", "others"),
            "accompaniment": ("instrumental", "inst", "accompaniment", "karaoke", "no_vocals", "music"),
        }

        stem_map: dict[str, Path] = {}
        for path in candidates:
            name = path.name.lower()
            for stem_name, keywords in keyword_map.items():
                if stem_name in stem_map:
                    continue
                if any(keyword in name for keyword in keywords):
                    stem_map[stem_name] = path
                    break

        if len(candidates) == 2 and "vocals" not in stem_map:
            first, second = candidates
            if first.stat().st_size >= second.stat().st_size:
                stem_map["vocals"] = second
                stem_map.setdefault("accompaniment", first)
            else:
                stem_map["vocals"] = first
                stem_map.setdefault("accompaniment", second)

        if len(candidates) == 2 and "vocals" in stem_map and "accompaniment" not in stem_map:
            remaining = [path for path in candidates if path != stem_map["vocals"]]
            if remaining:
                stem_map["accompaniment"] = remaining[0]

        return stem_map

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

        logger.info("Demucs separation started: input=%s device=%s", src, self.device)

        cpu_locks: list[threading.Semaphore] = []
        if self.device.type == "cpu":
            logger.info("CPU mode detected, waiting for inference slot...")
            cpu_locks = [_GLOBAL_CPU_LOCK, self._cpu_lock]

        try:
            if torchaudio is None:
                raise SeparationError(
                    "torchaudio is not installed. Please install torch+torchaudio in backend environment."
                )
            if demucs_apply_model is None:
                raise SeparationError("demucs runtime is not installed. Please install `demucs` package.")

            for lock in cpu_locks:
                lock.acquire()

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

            persisted_stems: dict[str, Path] = {}
            for name, tensor in stem_map.items():
                stem_name = self._normalize_stem_name(name)
                stem_path = out_dir / f"{stem_prefix}_{stem_name}.wav"
                self._save_audio(str(stem_path), tensor, sr)
                persisted_stems[stem_name] = stem_path

            accompaniment_path = out_dir / f"{stem_prefix}_accompaniment.wav"
            self._save_audio(str(accompaniment_path), accompaniment, sr)
            persisted_stems["accompaniment"] = accompaniment_path

            logger.info(
                "Demucs separation completed: stems=%s",
                persisted_stems,
            )

            return SeparationResult(stem_paths={name: str(path) for name, path in persisted_stems.items()})
        except ModelManagerError:
            raise
        except Exception as exc:
            raise SeparationError(f"Failed during Demucs separation: {exc}") from exc
        finally:
            for lock in reversed(cpu_locks):
                lock.release()

    @staticmethod
    def _normalize_stem_name(raw_name: str) -> str:
        value = str(raw_name or "").strip().lower().replace("-", "_").replace(" ", "_")
        if value in {"vocal", "voice"}:
            value = "vocals"
        value = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
        if not value:
            raise SeparationError("stem name cannot be empty")
        if not STEM_NAME_PATTERN.fullmatch(value):
            raise SeparationError(f"unsupported stem name: {raw_name}")
        return value

    def _persist_named_stems(
        self,
        stem_sources: dict[str, Path],
        *,
        out_dir: Path,
        stem_prefix: str,
    ) -> dict[str, Path]:
        persisted: dict[str, Path] = {}
        for name, src_path in stem_sources.items():
            stem_name = self._normalize_stem_name(name)
            dst_path = out_dir / f"{stem_prefix}_{stem_name}.wav"
            if src_path.resolve(strict=False) != dst_path.resolve(strict=False):
                shutil.copyfile(src_path, dst_path)
            persisted[stem_name] = dst_path
        return persisted

    def _mix_audio_files(self, source_paths: list[Path], output_path: Path) -> None:
        if not source_paths:
            raise SeparationError("No source stems provided for accompaniment mix.")

        mixed_waveform: torch.Tensor | None = None
        mixed_sr: int | None = None

        for stem_path in source_paths:
            waveform, sr = self._load_audio(str(stem_path))
            waveform = self._normalize_channels(waveform)

            if mixed_waveform is None:
                mixed_waveform = waveform
                mixed_sr = sr
                continue

            assert mixed_sr is not None
            if sr != mixed_sr:
                if torchaudio is None:
                    raise SeparationError(
                        "Cannot mix stems with mismatched sample rates without torchaudio resample support."
                    )
                waveform = torchaudio.functional.resample(waveform, sr, mixed_sr)

            current_len = int(mixed_waveform.shape[-1])
            next_len = int(waveform.shape[-1])
            if current_len < next_len:
                mixed_waveform = torch.nn.functional.pad(mixed_waveform, (0, next_len - current_len))
            elif next_len < current_len:
                waveform = torch.nn.functional.pad(waveform, (0, current_len - next_len))

            mixed_waveform = mixed_waveform + waveform

        assert mixed_waveform is not None and mixed_sr is not None
        self._save_audio(str(output_path), mixed_waveform, mixed_sr)

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
        prepared = VocalSeparator._prepare_waveform_for_save(waveform)
        if torchaudio is not None:
            try:
                torchaudio.save(path, prepared, sample_rate=sample_rate)
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
            data = prepared.detach().cpu().numpy().T
            sf.write(path, data, int(sample_rate), subtype="PCM_16")
        except Exception as exc:
            raise SeparationError(f"Failed to write audio via soundfile: {exc}") from exc

    @staticmethod
    def _prepare_waveform_for_save(waveform: torch.Tensor) -> torch.Tensor:
        if waveform.dim() != 2:
            raise SeparationError(f"Unexpected waveform shape for save: {tuple(waveform.shape)}")

        prepared = waveform.detach().cpu().float()
        if prepared.numel() == 0:
            return prepared

        peak = float(prepared.abs().max().item())
        target_peak = 0.98
        if peak > target_peak:
            prepared = prepared * (target_peak / peak)

        return prepared.clamp(-1.0, 1.0)

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
