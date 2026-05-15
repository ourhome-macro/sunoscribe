from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.modules.score_ir import ScoreIR, ScoreIRBuilder, ScoreIRSerializer


@dataclass(slots=True)
class ArtifactManifestItem:
    artifact_type: str
    path: str
    role: str
    score_revision_id: str | None = None
    required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MachineScoreRevisionState:
    """File-backed immutable machine revision state for pipeline-only runs."""

    revision_id: str
    project_id: str
    job_id: str | None
    revision_number: int
    revision_type: str
    score_type: str
    score_ir: dict[str, Any]
    score_data: dict[str, Any]
    artifact_manifest_path: str
    revision_dir: str
    artifact_manifest: list[ArtifactManifestItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_manifest"] = [item.to_dict() for item in self.artifact_manifest]
        return payload


class ScoreBuildService:
    """Build ScoreIR and export-facing score_data from transcription outputs."""

    def __init__(
        self,
        *,
        score_ir_builder: ScoreIRBuilder | None,
        invoke_builder: Callable[[Any, list[dict], Any | None], ScoreIR],
    ) -> None:
        self.score_ir_builder = score_ir_builder
        self.invoke_builder = invoke_builder

    def build(
        self,
        *,
        pitch_result_obj: Any,
        lyrics_segments: list[dict],
        analysis_ir_obj: Any | None = None,
    ) -> tuple[ScoreIR, dict | None]:
        if self.score_ir_builder is None:
            raise RuntimeError("score_ir_builder is not configured")
        score_ir_obj = self.invoke_builder(pitch_result_obj, lyrics_segments, analysis_ir_obj)
        return score_ir_obj, ScoreIRSerializer.to_score_data(score_ir_obj)

    def create_machine_revision_state(
        self,
        *,
        project_id: str,
        score_ir: dict[str, Any],
        score_data: dict[str, Any],
        project_dir: Path,
        job_id: str | None = None,
        score_type: str = "lead_vocal",
    ) -> MachineScoreRevisionState:
        """Create a new immutable machine revision identity without overwriting prior runs."""
        if not isinstance(score_ir, dict) or not score_ir:
            raise RuntimeError("machine score revision requires score_ir")
        if not isinstance(score_data, dict) or not score_data:
            raise RuntimeError("machine score revision requires score_data")

        revisions_root = project_dir / "revisions"
        revisions_root.mkdir(parents=True, exist_ok=True)
        revision_number = self._next_machine_revision_number(revisions_root)
        revision_id = f"machine-{revision_number:04d}-{uuid4().hex[:12]}"
        revision_dir = revisions_root / revision_id
        revision_dir.mkdir(parents=False, exist_ok=False)

        return MachineScoreRevisionState(
            revision_id=revision_id,
            project_id=str(project_id),
            job_id=str(job_id) if job_id else None,
            revision_number=revision_number,
            revision_type="machine",
            score_type=score_type,
            score_ir=score_ir,
            score_data=score_data,
            artifact_manifest_path=str(revision_dir / "artifact_manifest.json"),
            revision_dir=str(revision_dir),
        )

    @staticmethod
    def _next_machine_revision_number(revisions_root: Path) -> int:
        max_seen = 0
        for child in revisions_root.iterdir():
            if not child.is_dir() or not child.name.startswith("machine-"):
                continue
            parts = child.name.split("-")
            if len(parts) < 2:
                continue
            try:
                max_seen = max(max_seen, int(parts[1]))
            except ValueError:
                continue
        return max_seen + 1
