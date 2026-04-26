from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.detector import PitchDetector
from app.modules.pitch.exceptions import PitchModelUnavailableError


RMVPE_MODULE_CANDIDATES = (
    "rmvpe",
    "rmvpe.inference",
    "rmvpe.model",
    "infer.lib.rmvpe",
    "rvc.lib.rmvpe",
    "rvc.lib.predictors.RMVPE",
    "rvc.modules.extract_f0.rmvpe",
)


def parse_pitch_backend_fallbacks(raw: str | tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = raw.split(",")
    else:
        values = [str(item) for item in raw]

    normalized: list[str] = []
    for value in values:
        backend = _normalize_optional_backend(value)
        if backend and backend not in normalized:
            normalized.append(backend)
    return tuple(normalized)


def build_pitch_detection_config_from_settings() -> PitchDetectionConfig:
    return PitchDetectionConfig(
        pitch_backend=settings.pitch_backend,
        pitch_backend_fallbacks=parse_pitch_backend_fallbacks(settings.pitch_backend_fallbacks),
        cache_dir=settings.pitch_cache_dir,
        rmvpe_model_path=settings.rmvpe_model_path,
    )


def build_pitch_runtime_health(
    *,
    deep: bool = False,
    config: PitchDetectionConfig | None = None,
) -> dict[str, Any]:
    cfg = config or build_pitch_detection_config_from_settings()
    detector = PitchDetector(cfg)
    cache = _build_cache_health(cfg.resolved_cache_dir())
    rmvpe = _build_rmvpe_health(cfg, deep=deep)
    fallback_backends = parse_pitch_backend_fallbacks(cfg.pitch_backend_fallbacks)

    overall = "ok"
    if cache["status"] != "ok":
        overall = "degraded"
    if detector.backend_name == "rmvpe" and rmvpe["status"] != "ok":
        overall = "degraded" if fallback_backends else "fail"

    return {
        "status": overall,
        "pitch_backend": detector.backend_name,
        "pitch_backend_fallbacks": list(fallback_backends),
        "cache": cache,
        "rmvpe": rmvpe,
        "deep": bool(deep),
    }


def _build_cache_health(cache_dir: Path) -> dict[str, Any]:
    cache_dir = cache_dir.expanduser().resolve()
    exists = cache_dir.exists()
    is_dir = cache_dir.is_dir() if exists else False
    writable = _is_writable_path(cache_dir if exists else _nearest_existing_parent(cache_dir))

    if exists and is_dir and writable:
        status = "ok"
    elif exists and not is_dir:
        status = "not_directory"
    elif not writable:
        status = "not_writable"
    else:
        status = "missing"

    return {
        "status": status,
        "path": str(cache_dir),
        "exists": exists,
        "is_dir": is_dir,
        "writable": writable,
    }


def _build_rmvpe_health(config: PitchDetectionConfig, *, deep: bool) -> dict[str, Any]:
    raw_model_path = str(config.rmvpe_model_path or "").strip()
    model_path = Path(raw_model_path).expanduser() if raw_model_path else None
    model_exists = bool(model_path and model_path.exists() and model_path.is_file())
    modules = _find_available_modules(RMVPE_MODULE_CANDIDATES)

    if model_path is not None and not model_exists:
        status = "missing_model"
        message = "Configured RMVPE model path does not exist."
    elif modules:
        status = "ok"
        message = "RMVPE runtime module is importable."
    elif model_path is None:
        status = "missing_runtime"
        message = "No RMVPE runtime module found; fallback backends will be used if configured."
    else:
        status = "missing_runtime"
        message = "RMVPE model file exists, but no RMVPE runtime module is importable."

    load_error: str | None = None
    if deep and status == "ok":
        detector = PitchDetector(config)
        try:
            detector._build_rmvpe_model(model_path=str(model_path.resolve()) if model_path else None)
        except PitchModelUnavailableError as exc:
            status = "load_failed"
            load_error = str(exc)
        except Exception as exc:
            status = "load_failed"
            load_error = str(exc)

    return {
        "status": status,
        "message": message,
        "model_path": str(model_path.resolve()) if model_path else None,
        "model_exists": model_exists,
        "available_modules": modules,
        "load_error": load_error,
    }


def _find_available_modules(candidates: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for module_name in candidates:
        try:
            if importlib.util.find_spec(module_name) is not None:
                found.append(module_name)
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
    return found


def _normalize_optional_backend(raw: str) -> str | None:
    value = str(raw or "").strip().lower()
    if not value:
        return None
    aliases = {
        "basic_pitch": "basic-pitch",
        "basicpitch": "basic-pitch",
        "r-mvpe": "rmvpe",
        "rvc-rmvpe": "rmvpe",
    }
    value = aliases.get(value, value)
    if value in {"rmvpe", "crepe", "basic-pitch"}:
        return value
    return None


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _is_writable_path(path: Path) -> bool:
    try:
        target = path if path.exists() else path.parent
        return os.access(target, os.W_OK)
    except Exception:
        return False
