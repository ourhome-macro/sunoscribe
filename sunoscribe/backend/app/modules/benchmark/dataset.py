from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any


class ManifestValidationError(ValueError):
    """Raised when a benchmark manifest is malformed or inconsistent."""


@dataclass(slots=True)
class BenchmarkSample:
    id: str
    input_mp4: Path
    expected_midi: Path
    expected_melody_track: int | None
    expected_reference_strategy: str | None = None
    expected_reference_pitch_shift_semitones: int = 0
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    input_sha256: str | None = None
    expected_sha256: str | None = None

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        data = asdict(self)
        if root is None:
            data["input_mp4"] = str(self.input_mp4)
            data["expected_midi"] = str(self.expected_midi)
        else:
            data["input_mp4"] = _display_path(self.input_mp4, root)
            data["expected_midi"] = _display_path(self.expected_midi, root)
        return data


@dataclass(slots=True)
class BenchmarkManifest:
    version: int
    description: str
    root: Path
    samples: list[BenchmarkSample]
    defaults: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled_samples(self) -> list[BenchmarkSample]:
        return [sample for sample in self.samples if sample.enabled]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "description": self.description,
            "defaults": self.defaults,
            "samples": [sample.to_dict(root=self.root) for sample in self.samples],
        }


@dataclass(slots=True)
class BenchmarkDatasetReport:
    manifest_path: str | None
    samples_root: str
    mp4_count: int
    midi_count: int
    paired_count: int
    enabled_count: int
    mp4_only: list[str]
    midi_only: list[str]
    duplicate_mp4_keys: dict[str, list[str]]
    duplicate_midi_keys: dict[str, list[str]]
    sample_status: list[dict[str, Any]]
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_sample_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.strip().lower()
    return re.sub(r"\s+", " ", normalized)


def compute_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_sample_pairs(samples_root: str | Path) -> dict[str, Any]:
    root = Path(samples_root)
    mp4_files = sorted((root / "source_mp4").glob("*.mp4")) if (root / "source_mp4").exists() else []
    midi_files = sorted((root / "source_mid").glob("*.mid")) if (root / "source_mid").exists() else []
    mp4_by_key, duplicate_mp4_keys = _index_by_normalized_stem(mp4_files)
    midi_by_key, duplicate_midi_keys = _index_by_normalized_stem(midi_files)
    paired_keys = sorted(set(mp4_by_key) & set(midi_by_key))
    return {
        "samples_root": str(root),
        "mp4_count": len(mp4_files),
        "midi_count": len(midi_files),
        "paired_count": len(paired_keys),
        "pairs": [
            {
                "id": _sample_id_from_key(key),
                "key": key,
                "input_mp4": mp4_by_key[key],
                "expected_midi": midi_by_key[key],
            }
            for key in paired_keys
        ],
        "mp4_only": [str(mp4_by_key[key]) for key in sorted(set(mp4_by_key) - set(midi_by_key))],
        "midi_only": [str(midi_by_key[key]) for key in sorted(set(midi_by_key) - set(mp4_by_key))],
        "duplicate_mp4_keys": {key: [str(path) for path in paths] for key, paths in duplicate_mp4_keys.items()},
        "duplicate_midi_keys": {key: [str(path) for path in paths] for key, paths in duplicate_midi_keys.items()},
    }


def load_manifest(path: str | Path) -> BenchmarkManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_value = payload.get("root") or "."
    root = (manifest_path.parent / root_value).resolve(strict=False)
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    samples_payload = payload.get("samples")
    if not isinstance(samples_payload, list):
        raise ManifestValidationError("manifest.samples must be a list")

    samples: list[BenchmarkSample] = []
    seen_ids: set[str] = set()
    for index, raw_sample in enumerate(samples_payload):
        if not isinstance(raw_sample, dict):
            raise ManifestValidationError(f"sample[{index}] must be an object")
        sample_id = str(raw_sample.get("id") or "").strip()
        if not sample_id:
            raise ManifestValidationError(f"sample[{index}].id is required")
        if sample_id in seen_ids:
            raise ManifestValidationError(f"duplicate sample id: {sample_id}")
        seen_ids.add(sample_id)

        input_mp4 = _resolve_manifest_path(root, raw_sample.get("input_mp4"), f"sample[{index}].input_mp4")
        expected_midi = _resolve_manifest_path(root, raw_sample.get("expected_midi"), f"sample[{index}].expected_midi")
        melody_track = raw_sample.get("expected_melody_track")
        if melody_track is not None:
            try:
                melody_track = int(melody_track)
            except Exception as exc:
                raise ManifestValidationError(f"sample[{index}].expected_melody_track must be an integer") from exc

        reference_pitch_shift = raw_sample.get("expected_reference_pitch_shift_semitones", 0)
        try:
            reference_pitch_shift = int(reference_pitch_shift)
        except Exception as exc:
            raise ManifestValidationError(
                f"sample[{index}].expected_reference_pitch_shift_semitones must be an integer"
            ) from exc
        if reference_pitch_shift < -24 or reference_pitch_shift > 24:
            raise ManifestValidationError(
                f"sample[{index}].expected_reference_pitch_shift_semitones must be between -24 and 24"
            )

        tags = raw_sample.get("tags") or []
        if not isinstance(tags, list):
            raise ManifestValidationError(f"sample[{index}].tags must be a list")

        samples.append(
            BenchmarkSample(
                id=sample_id,
                input_mp4=input_mp4,
                expected_midi=expected_midi,
                expected_melody_track=melody_track,
                expected_reference_strategy=raw_sample.get("expected_reference_strategy"),
                expected_reference_pitch_shift_semitones=reference_pitch_shift,
                enabled=bool(raw_sample.get("enabled", True)),
                tags=[str(tag) for tag in tags],
                notes=raw_sample.get("notes"),
                input_sha256=raw_sample.get("input_sha256"),
                expected_sha256=raw_sample.get("expected_sha256"),
            )
        )

    return BenchmarkManifest(
        version=int(payload.get("version", 1)),
        description=str(payload.get("description") or ""),
        root=root,
        defaults=defaults,
        samples=samples,
    )


def build_dataset_report(
    *,
    samples_root: str | Path,
    manifest: BenchmarkManifest | None = None,
    manifest_path: str | Path | None = None,
    include_checksums: bool = True,
) -> BenchmarkDatasetReport:
    discovery = discover_sample_pairs(samples_root)
    sample_status: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    enabled_count = 0

    if manifest is not None:
        for sample in manifest.samples:
            status = _sample_dataset_status(sample, root=manifest.root, include_checksums=include_checksums)
            sample_status.append(status)
            if sample.enabled:
                enabled_count += 1
            errors.extend(status.get("errors", []))
            warnings.extend(status.get("warnings", []))
    else:
        enabled_count = int(discovery["paired_count"])

    return BenchmarkDatasetReport(
        manifest_path=str(manifest_path) if manifest_path is not None else None,
        samples_root=str(samples_root),
        mp4_count=int(discovery["mp4_count"]),
        midi_count=int(discovery["midi_count"]),
        paired_count=int(discovery["paired_count"]),
        enabled_count=enabled_count,
        mp4_only=[str(item) for item in discovery["mp4_only"]],
        midi_only=[str(item) for item in discovery["midi_only"]],
        duplicate_mp4_keys=discovery["duplicate_mp4_keys"],
        duplicate_midi_keys=discovery["duplicate_midi_keys"],
        sample_status=sample_status,
        errors=errors,
        warnings=warnings,
    )


def _sample_dataset_status(sample: BenchmarkSample, *, root: Path, include_checksums: bool) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    input_exists = sample.input_mp4.exists() and sample.input_mp4.is_file()
    expected_exists = sample.expected_midi.exists() and sample.expected_midi.is_file()
    if not input_exists:
        errors.append({"sample_id": sample.id, "code": "MISSING_INPUT_MP4", "path": str(sample.input_mp4)})
    if not expected_exists:
        errors.append({"sample_id": sample.id, "code": "MISSING_EXPECTED_MIDI", "path": str(sample.expected_midi)})
    if sample.enabled and sample.expected_melody_track is None:
        errors.append({"sample_id": sample.id, "code": "MISSING_MELODY_TRACK"})

    checksum_status: dict[str, Any] = {}
    if include_checksums:
        checksum_status = _checksum_status(sample)
        for kind, status in checksum_status.items():
            if status.get("matches") is False:
                errors.append({"sample_id": sample.id, "code": "CHECKSUM_MISMATCH", "kind": kind})
            if status.get("configured") is False:
                warnings.append({"sample_id": sample.id, "code": "CHECKSUM_NOT_CONFIGURED", "kind": kind})

    return {
        "id": sample.id,
        "enabled": sample.enabled,
        "input_mp4": _display_path(sample.input_mp4, root),
        "expected_midi": _display_path(sample.expected_midi, root),
        "expected_melody_track": sample.expected_melody_track,
        "expected_reference_strategy": sample.expected_reference_strategy,
        "input_exists": input_exists,
        "expected_exists": expected_exists,
        "checksums": checksum_status,
        "errors": errors,
        "warnings": warnings,
    }


def _checksum_status(sample: BenchmarkSample) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind, path, expected in (
        ("input_mp4", sample.input_mp4, sample.input_sha256),
        ("expected_midi", sample.expected_midi, sample.expected_sha256),
    ):
        configured = bool(expected)
        actual = compute_sha256(path) if path.exists() and path.is_file() else None
        result[kind] = {
            "configured": configured,
            "expected": expected,
            "actual": actual,
            "matches": (actual == expected) if configured and actual is not None else None,
        }
    return result


def _resolve_manifest_path(root: Path, value: Any, field_name: str) -> Path:
    if not value:
        raise ManifestValidationError(f"{field_name} is required")
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return str(path)


def _index_by_normalized_stem(paths: list[Path]) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    grouped: dict[str, list[Path]] = {}
    for path in paths:
        grouped.setdefault(normalize_sample_key(path.stem), []).append(path)
    unique: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}
    for key, grouped_paths in grouped.items():
        chosen = sorted(grouped_paths, key=lambda path: (" " in path.stem, len(path.stem.strip()), path.name))[0]
        unique[key] = chosen
        if len(grouped_paths) > 1:
            duplicates[key] = grouped_paths
    return unique, duplicates


def _sample_id_from_key(key: str) -> str:
    ascii_key = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_key.lower()).strip("_")
    if slug:
        return slug
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"sample_{digest}"
