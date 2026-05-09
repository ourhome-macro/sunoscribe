from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import contextlib
import io
import json
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
AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac", ".aif", ".aiff"}


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


@dataclass(slots=True)
class _MdxInvocationResult:
    value: Any
    call_signature: str
    attempted_signatures: list[str]
    stdout: str = ""
    stderr: str = ""


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
        original_src = Path(input_audio_path)
        src = original_src.resolve(strict=False)
        if not src.exists() or not src.is_file():
            raise SeparationError(f"Input audio file does not exist: {original_src}")

        initial_cwd = Path.cwd().resolve(strict=False)
        out_dir = Path(output_dir).resolve(strict=False)
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_output_dir = out_dir / "_mdx_raw"
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        diagnostics_path = out_dir / "mdx_diagnostics.json"
        scanned_directories = self._mdx_scanned_directories(
            output_dir=out_dir,
            raw_output_dir=raw_output_dir,
            initial_cwd=initial_cwd,
            src_parent=src.parent,
        )

        cpu_locks: list[threading.Semaphore] = []
        if self.device.type == "cpu":
            cpu_locks = [_GLOBAL_CPU_LOCK, self._cpu_lock]
            for lock in cpu_locks:
                lock.acquire()

        try:
            fallback_snapshot = self._snapshot_mdx_fallback_outputs(source_stem=src.stem, raw_output_dir=raw_output_dir)
            output_snapshot = self._snapshot_audio_files(out_dir)
            invocation = self._invoke_mdx_separator(src=src, output_dir=raw_output_dir)
            fallback_outputs = list(
                self._iter_mdx_fallback_outputs(
                    source_stem=src.stem,
                    raw_output_dir=raw_output_dir,
                    before=fallback_snapshot,
                )
            )
            fallback_outputs.extend(self._iter_changed_audio_files(out_dir, before=output_snapshot))
            candidates = self._collect_output_candidates(
                invocation.value,
                fallback=fallback_outputs,
                base_dir=raw_output_dir,
            )
            output_files = self._scan_mdx_output_files(out_dir)
            diagnostics = self._build_mdx_diagnostics(
                src=src,
                original_src=original_src,
                out_dir=out_dir,
                raw_output_dir=raw_output_dir,
                initial_cwd=initial_cwd,
                scanned_directories=scanned_directories,
                output_files=output_files,
                candidates=candidates,
                invocation=invocation,
                status="completed",
            )
            self._write_mdx_diagnostics(diagnostics_path, diagnostics)

            if not any(item["extension"] in AUDIO_SUFFIXES for item in output_files) and not candidates:
                raise SeparationError(
                    "mdx_net_produced_no_audio_files: "
                    f"input_path={src}; output_dir={out_dir}; candidates=[]; "
                    f"scanned_directories={self._format_paths(scanned_directories)}; "
                    f"stdout={self._short_log(invocation.stdout)}; stderr={self._short_log(invocation.stderr)}"
                )

            stem_sources = self._pick_mdx_stem_map(candidates)

            if stem_sources.get("vocals") is None:
                raise SeparationError(
                    "MDX-Net output does not contain a vocals stem. "
                    f"candidates={[self._display_candidate_path(path, out_dir) for path in candidates]}; "
                    f"scanned_directories={self._format_paths(scanned_directories)}"
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
                    f"candidates={[self._display_candidate_path(path, out_dir) for path in candidates]}; "
                    f"scanned_directories={self._format_paths(scanned_directories)}"
                )

            persisted_stems = self._persist_named_stems(stem_sources, out_dir=out_dir, stem_prefix=stem_prefix)

            logger.info(
                "MDX-Net separation completed: stems=%s",
                persisted_stems,
            )
            return SeparationResult(stem_paths={name: str(path) for name, path in persisted_stems.items()})
        except ModelManagerError:
            raise
        except SeparationError as exc:
            output_files = self._scan_mdx_output_files(out_dir)
            diagnostics = self._build_mdx_diagnostics(
                src=src,
                original_src=original_src,
                out_dir=out_dir,
                raw_output_dir=raw_output_dir,
                initial_cwd=initial_cwd,
                scanned_directories=scanned_directories,
                output_files=output_files,
                candidates=locals().get("candidates", []),
                invocation=locals().get("invocation"),
                status="failed",
                error=str(exc),
            )
            self._write_mdx_diagnostics(diagnostics_path, diagnostics)
            raise
        except Exception as exc:
            output_files = self._scan_mdx_output_files(out_dir)
            diagnostics = self._build_mdx_diagnostics(
                src=src,
                original_src=original_src,
                out_dir=out_dir,
                raw_output_dir=raw_output_dir,
                initial_cwd=initial_cwd,
                scanned_directories=scanned_directories,
                output_files=output_files,
                candidates=[],
                invocation=None,
                status="failed",
                error=str(exc),
            )
            self._write_mdx_diagnostics(diagnostics_path, diagnostics)
            raise SeparationError(f"Failed during MDX-Net separation: {exc}") from exc
        finally:
            for lock in reversed(cpu_locks):
                lock.release()

    def _invoke_mdx_separator(self, *, src: Path, output_dir: Path) -> _MdxInvocationResult:
        separator = self._mdx_separator
        if separator is None:
            raise SeparationError("MDX separator is not initialized")

        self._set_mdx_output_dir(separator, output_dir)

        errors: list[str] = []
        attempted_signatures: list[str] = []
        src_arg = str(src.resolve(strict=False))
        output_arg = str(output_dir.resolve(strict=False))
        call_candidates = [
            (
                "separate(path, output_dir=output_dir)",
                lambda: self._invoke_mdx_separator_in_output_dir(
                    lambda: separator.separate(src_arg, output_dir=output_arg), output_dir
                ),
            ),
            (
                "separate(audio_file=path, output_dir=output_dir)",
                lambda: self._invoke_mdx_separator_in_output_dir(
                    lambda: separator.separate(audio_file=src_arg, output_dir=output_arg), output_dir
                ),
            ),
            (
                "separate(audio_path=path, output_dir=output_dir)",
                lambda: self._invoke_mdx_separator_in_output_dir(
                    lambda: separator.separate(audio_path=src_arg, output_dir=output_arg), output_dir
                ),
            ),
            (
                "separate(path)",
                lambda: self._invoke_mdx_separator_in_output_dir(lambda: separator.separate(src_arg), output_dir),
            ),
            (
                "separate(audio_file=path)",
                lambda: self._invoke_mdx_separator_in_output_dir(lambda: separator.separate(audio_file=src_arg), output_dir),
            ),
            (
                "separate(audio_path=path)",
                lambda: self._invoke_mdx_separator_in_output_dir(lambda: separator.separate(audio_path=src_arg), output_dir),
            ),
        ]

        for signature, call in call_candidates:
            attempted_signatures.append(signature)
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    value = call()
                return _MdxInvocationResult(
                    value=value,
                    call_signature=signature,
                    attempted_signatures=list(attempted_signatures),
                    stdout=stdout.getvalue(),
                    stderr=stderr.getvalue(),
                )
            except TypeError as exc:
                errors.append(f"{signature}: {exc}")
                continue
            except Exception as exc:
                raise SeparationError(
                    f"MDX separator runtime failed with {signature}: {exc}; "
                    f"stdout={self._short_log(stdout.getvalue())}; stderr={self._short_log(stderr.getvalue())}"
                ) from exc

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

    @staticmethod
    def _set_mdx_output_dir(separator: Any, output_dir: Path) -> None:
        output_arg = str(output_dir.resolve(strict=False))
        for target in (separator, getattr(separator, "model_instance", None)):
            if target is None or not hasattr(target, "output_dir"):
                continue
            try:
                setattr(target, "output_dir", output_arg)
            except Exception:
                pass

    def _collect_output_candidates(
        self,
        result: Any,
        *,
        fallback: Iterable[Path],
        base_dir: Path,
        scan_dirs: Iterable[Path] | None = None,
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

        for directory in scan_dirs or []:
            for path in self._iter_audio_files_recursive(directory):
                append_path(path)

        normalized: list[Path] = []
        seen: set[str] = set()

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
            if resolved.suffix.lower() not in AUDIO_SUFFIXES:
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
    def _snapshot_audio_files(directory: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in VocalSeparator._iter_audio_files_recursive(directory):
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[str(path.resolve(strict=False))] = (int(stat.st_mtime_ns), int(stat.st_size))
        return snapshot

    @staticmethod
    def _iter_changed_audio_files(directory: Path, *, before: dict[str, tuple[int, int]]) -> Iterable[Path]:
        for path in VocalSeparator._iter_audio_files_recursive(directory):
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
                    if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
                        yield path

    @staticmethod
    def _iter_audio_files_recursive(directory: Path) -> Iterable[Path]:
        try:
            if not directory.exists() or not directory.is_dir():
                return
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
                    yield path.resolve(strict=False)
        except OSError:
            return

    @staticmethod
    def _mdx_scanned_directories(
        *,
        output_dir: Path,
        raw_output_dir: Path,
        initial_cwd: Path,
        src_parent: Path,
    ) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for raw_path in (output_dir, raw_output_dir, initial_cwd, src_parent):
            path = raw_path.resolve(strict=False)
            key = str(path)
            if key not in seen:
                paths.append(path)
                seen.add(key)
        return paths

    @staticmethod
    def _scan_mdx_output_files(output_dir: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        if not output_dir.exists() or not output_dir.is_dir():
            return files
        for path in sorted(output_dir.rglob("*"), key=lambda item: str(item).lower()):
            if not path.is_file():
                continue
            try:
                relative_path = path.relative_to(output_dir).as_posix()
            except ValueError:
                relative_path = path.name
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
            files.append(
                {
                    "relative_path": relative_path,
                    "size_bytes": size_bytes,
                    "extension": path.suffix.lower(),
                }
            )
        return files

    def _build_mdx_diagnostics(
        self,
        *,
        src: Path,
        original_src: Path,
        out_dir: Path,
        raw_output_dir: Path,
        initial_cwd: Path,
        scanned_directories: list[Path],
        output_files: list[dict[str, Any]],
        candidates: list[Path],
        invocation: _MdxInvocationResult | None,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "error": error,
            "mdx_input_path": str(src),
            "mdx_input_path_original": str(original_src),
            "mdx_output_dir": str(raw_output_dir),
            "separation_output_dir": str(out_dir),
            "current_working_directory": str(initial_cwd),
            "backend_config": self._mdx_backend_config(invocation),
            "scanned_directories": [str(path) for path in scanned_directories],
            "output_files": output_files,
            "candidates": [self._display_candidate_path(path, out_dir) for path in candidates],
        }

    def _mdx_backend_config(self, invocation: _MdxInvocationResult | None) -> dict[str, Any]:
        separator = self._mdx_separator
        manager = self.model_manager
        attrs: dict[str, Any] = {}
        if separator is not None:
            for name in ("output_dir", "model_file_dir", "output_format", "model_filename", "model_name"):
                if hasattr(separator, name):
                    try:
                        attrs[name] = str(getattr(separator, name))
                    except Exception:
                        attrs[name] = "<unavailable>"
        payload: dict[str, Any] = {
            "backend": self.backend,
            "device": str(self.device),
            "separator_class": separator.__class__.__name__ if separator is not None else None,
            "separator_attrs": attrs,
            "model_name": str(getattr(manager, "model_name", "")),
            "cache_root": str(getattr(manager, "cache_root", "")),
            "mdx_cache_dir": str(getattr(manager, "mdx_cache_dir", "")),
            "prefer_cuda": bool(getattr(manager, "prefer_cuda", False)),
        }
        if invocation is not None:
            payload.update(
                {
                    "call_signature": invocation.call_signature,
                    "attempted_signatures": invocation.attempted_signatures,
                    "stdout": invocation.stdout[-4000:],
                    "stderr": invocation.stderr[-4000:],
                }
            )
        return payload

    @staticmethod
    def _write_mdx_diagnostics(path: Path, diagnostics: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write MDX diagnostics to %s: %s", path, exc)

    @staticmethod
    def _display_candidate_path(path: Path, base_dir: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(base_dir.resolve(strict=False)).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def _format_paths(paths: Iterable[Path]) -> list[str]:
        return [str(path) for path in paths]

    @staticmethod
    def _short_log(text: str, limit: int = 1200) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[-limit:]

    def _pick_mdx_stem_map(self, candidates: list[Path]) -> dict[str, Path]:
        if not candidates:
            return {}

        stem_map: dict[str, Path] = {}
        for path in candidates:
            stem_name = self._classify_mdx_stem(path)
            if stem_name and stem_name not in stem_map:
                stem_map[stem_name] = path

        if len(candidates) == 2 and "vocals" in stem_map and "accompaniment" not in stem_map:
            remaining = [path for path in candidates if path != stem_map["vocals"]]
            if remaining:
                stem_map["accompaniment"] = remaining[0]

        return stem_map

    @staticmethod
    def _classify_mdx_stem(path: Path) -> str | None:
        name = path.stem.lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
        tokens = [token for token in normalized.split("_") if token]
        token_set = set(tokens)
        has_no_vocal = any(
            token in {"no", "non", "without"} and index + 1 < len(tokens) and tokens[index + 1] in {"vocal", "vocals"}
            for index, token in enumerate(tokens)
        ) or "no_vocals" in normalized or "no_vocal" in normalized

        if has_no_vocal or token_set.intersection({"instrumental", "accompaniment", "karaoke", "music", "inst"}):
            return "accompaniment"
        if token_set.intersection({"vocals", "vocal", "voice", "acapella", "acappella"}):
            return "vocals"
        if token_set.intersection({"drum", "drums", "percussion"}):
            return "drums"
        if "bass" in token_set:
            return "bass"
        if token_set.intersection({"other", "others"}):
            return "other"
        return None

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
