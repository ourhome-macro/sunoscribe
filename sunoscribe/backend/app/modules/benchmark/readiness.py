from __future__ import annotations

from dataclasses import asdict, dataclass, field
import importlib.util
from pathlib import Path
import shutil
import sys
from typing import Any

from app.services.pitch_runtime import build_pitch_runtime_health


@dataclass(slots=True)
class ReadinessCheck:
    name: str
    status: str
    required: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MvpReadinessReport:
    status: str
    checks: list[ReadinessCheck]
    notes: list[str] = field(default_factory=list)

    @property
    def blocking_checks(self) -> list[ReadinessCheck]:
        return [check for check in self.checks if check.required and check.status != "ok"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "blocking_checks": [check.to_dict() for check in self.blocking_checks],
            "notes": list(self.notes),
        }


def build_mvp_readiness_report(*, deep_pitch: bool = False) -> MvpReadinessReport:
    checks = [
        _python_check(),
        _ffmpeg_check(),
        _module_check("pretty_midi", required=True, package_hint="pretty_midi"),
        _module_check("mido", required=True, package_hint="mido"),
        _module_check("librosa", required=True, package_hint="librosa"),
        _module_check("soundfile", required=True, package_hint="soundfile"),
        _pitch_check(deep=deep_pitch),
        _vocal_separator_check(),
    ]
    status = "ok" if not [check for check in checks if check.required and check.status != "ok"] else "fail"
    return MvpReadinessReport(
        status=status,
        checks=checks,
        notes=[
            "Production MVP keeps pitch fallbacks disabled.",
            "If readiness fails, install/configure required dependencies rather than enabling fallback output.",
        ],
    )


def _python_check() -> ReadinessCheck:
    version = sys.version_info
    ok = (version.major, version.minor) == (3, 10)
    return ReadinessCheck(
        name="python",
        status="ok" if ok else "warn",
        required=False,
        message="Python 3.10 is recommended for backend runtime." if ok else "Backend runtime is not Python 3.10.",
        details={"version": sys.version.split()[0], "executable": sys.executable},
    )


def _ffmpeg_check() -> ReadinessCheck:
    path = shutil.which("ffmpeg")
    return ReadinessCheck(
        name="ffmpeg",
        status="ok" if path else "fail",
        required=True,
        message="ffmpeg is available." if path else "ffmpeg is required for MP4/audio canonicalization.",
        details={"path": path},
    )


def _module_check(module_name: str, *, required: bool, package_hint: str) -> ReadinessCheck:
    available = _module_available(module_name)
    return ReadinessCheck(
        name=module_name,
        status="ok" if available else "fail",
        required=required,
        message=f"{module_name} is importable." if available else f"Install `{package_hint}` in the backend environment.",
        details={"module": module_name, "package_hint": package_hint},
    )


def _pitch_check(*, deep: bool) -> ReadinessCheck:
    try:
        health = build_pitch_runtime_health(deep=deep)
    except Exception as exc:
        return ReadinessCheck(
            name="rmvpe_pitch",
            status="fail",
            required=True,
            message=f"Pitch runtime health check failed: {exc}",
            details={"error_type": exc.__class__.__name__},
        )

    status = "ok" if health.get("status") == "ok" else "fail"
    fallback_allowed = bool(health.get("allow_backend_fallbacks")) or bool(health.get("pitch_backend_fallbacks"))
    if fallback_allowed:
        status = "fail"
    message = "RMVPE production runtime is ready." if status == "ok" else "RMVPE production runtime is not ready."
    return ReadinessCheck(
        name="rmvpe_pitch",
        status=status,
        required=True,
        message=message,
        details=health,
    )


def _vocal_separator_check() -> ReadinessCheck:
    audio_separator_available = _module_available("audio_separator.separator")
    demucs_available = _module_available("demucs.pretrained")
    model_cache = _mdx_model_cache_status()
    ok = audio_separator_available and bool(model_cache.get("has_cached_model"))
    if ok:
        message = "MDX-Net vocal separator package and cached model are available."
    elif not audio_separator_available:
        message = "Install `audio-separator` and matching onnxruntime for production vocal separation."
    else:
        message = "MDX-Net runtime is importable, but the configured model cache is missing."
    return ReadinessCheck(
        name="vocal_separator",
        status="ok" if ok else "fail",
        required=True,
        message=message,
        details={
            "audio_separator_available": audio_separator_available,
            "demucs_available": demucs_available,
            **model_cache,
        },
    )


def _mdx_model_cache_status() -> dict[str, Any]:
    cache_dir = Path.home() / ".cache" / "sunoscribe" / "mdxnet"
    model_name = "UVR_MDXNET_Main.onnx"
    matches = list(cache_dir.glob(f"*{model_name}*")) if cache_dir.exists() else []
    return {
        "cache_dir": str(cache_dir),
        "model_name": model_name,
        "cache_exists": cache_dir.exists(),
        "has_cached_model": bool(matches),
        "matches": [str(path) for path in matches],
    }


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
