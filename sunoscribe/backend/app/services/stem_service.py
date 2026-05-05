from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any

from app.services.workspace import ProjectWorkspace


@dataclass(slots=True)
class StemServiceResult:
    stem_paths: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def vocals_path(self) -> Path | None:
        return self.stem_paths.get("vocals")

    @property
    def accompaniment_path(self) -> Path | None:
        return self.stem_paths.get("accompaniment")


class StemService:
    """Run vocal/accompaniment separation from canonical audio."""

    def __init__(self, vocal_separator: Any | None) -> None:
        self.vocal_separator = vocal_separator

    def separate(self, canonical_audio_path: str | Path, workspace: ProjectWorkspace) -> StemServiceResult:
        if self.vocal_separator is None:
            return StemServiceResult(warnings=["vocal_separator_missing: skip separation"])

        separation_result = self.vocal_separator.separate(
            str(canonical_audio_path),
            str(workspace.separation_dir),
            "separated",
        )
        return StemServiceResult(stem_paths=self._collect_and_persist_stems(separation_result, workspace))

    def _collect_and_persist_stems(self, separation_result: Any, workspace: ProjectWorkspace) -> dict[str, Path]:
        collected: dict[str, Path] = {}

        raw_stem_paths = getattr(separation_result, "stem_paths", None)
        if isinstance(raw_stem_paths, dict):
            for stem_name, stem_path in raw_stem_paths.items():
                normalized_name = ProjectWorkspace.normalize_stem_name(str(stem_name))
                candidate = Path(str(stem_path))
                if candidate.exists() and candidate.is_file():
                    collected[normalized_name] = candidate

        vocals_raw = getattr(separation_result, "vocal_path", None) or getattr(separation_result, "vocals_path", None)
        accompaniment_raw = getattr(separation_result, "accompaniment_path", None)

        if vocals_raw:
            candidate = Path(str(vocals_raw))
            if candidate.exists() and candidate.is_file():
                collected.setdefault("vocals", candidate)

        if accompaniment_raw:
            candidate = Path(str(accompaniment_raw))
            if candidate.exists() and candidate.is_file():
                collected.setdefault("accompaniment", candidate)

        persisted: dict[str, Path] = {}
        for stem_name, source_path in collected.items():
            destination_path = workspace.stem_path(stem_name)
            if source_path.resolve(strict=False) != destination_path.resolve(strict=False):
                shutil.copyfile(source_path, destination_path)
            persisted[stem_name] = destination_path

        if "vocals" in persisted:
            persisted["vocals"] = workspace.vocals_path
        if "accompaniment" in persisted:
            persisted["accompaniment"] = workspace.accompaniment_path

        return persisted
