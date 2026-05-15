from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STEM_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(slots=True)
class ProjectWorkspace:
    """Manage per-project folders and artifact paths."""

    project_id: str
    projects_root: Path = Path("data/projects")

    def __post_init__(self) -> None:
        self.project_id = str(self.project_id).strip()
        if not self.project_id:
            raise ValueError("project_id cannot be empty")
        if not PROJECT_ID_PATTERN.fullmatch(self.project_id):
            raise ValueError("project_id contains unsupported characters")
        if not self._is_within_projects_root():
            raise ValueError("project_id resolves outside projects_root")

    @property
    def project_dir(self) -> Path:
        return self.projects_root / self.project_id

    @property
    def input_dir(self) -> Path:
        return self.project_dir / "input"

    @property
    def preprocess_dir(self) -> Path:
        return self.project_dir / "preprocess"

    @property
    def separation_dir(self) -> Path:
        return self.project_dir / "separation"

    @property
    def lyrics_dir(self) -> Path:
        return self.project_dir / "lyrics"

    @property
    def pitch_dir(self) -> Path:
        return self.project_dir / "pitch"

    @property
    def score_dir(self) -> Path:
        return self.project_dir / "score"

    @property
    def alignment_dir(self) -> Path:
        return self.project_dir / "alignment"

    @property
    def exports_dir(self) -> Path:
        return self.project_dir / "exports"

    def revision_dir(self, revision_id: str) -> Path:
        normalized_revision_id = str(revision_id).strip()
        if not normalized_revision_id:
            raise ValueError("revision_id cannot be empty")
        return self.project_dir / "revisions" / normalized_revision_id

    def revision_exports_dir(self, revision_id: str) -> Path:
        return self.revision_dir(revision_id) / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.project_dir / "logs"

    @property
    def jobs_dir(self) -> Path:
        return self.project_dir / "jobs"

    def job_dir(self, task_id: str) -> Path:
        normalized_task_id = str(task_id).strip()
        if not normalized_task_id:
            raise ValueError("task_id cannot be empty")
        return self.jobs_dir / normalized_task_id

    def job_manifest_path(self, task_id: str) -> Path:
        return self.job_dir(task_id) / "manifest.json"

    def job_runtime_dir(self, task_id: str) -> Path:
        return self.job_dir(task_id) / "runtime"

    @property
    def canonical_audio_path(self) -> Path:
        return self.preprocess_dir / "source.wav"

    @property
    def normalized_audio_path(self) -> Path:
        return self.canonical_audio_path

    @property
    def vocals_path(self) -> Path:
        return self.separation_dir / "vocals.wav"

    @property
    def accompaniment_path(self) -> Path:
        return self.separation_dir / "accompaniment.wav"

    @property
    def separation_manifest_path(self) -> Path:
        return self.separation_dir / "stems.json"

    @property
    def lyrics_segments_path(self) -> Path:
        return self.lyrics_dir / "lyrics_segments.json"

    @property
    def whisper_raw_path(self) -> Path:
        return self.lyrics_dir / "whisper_raw.json"

    @property
    def pitch_result_path(self) -> Path:
        return self.pitch_dir / "pitch_result.json"

    @property
    def f0_track_path(self) -> Path:
        return self.pitch_dir / "f0_track.json"

    @property
    def pitch_contours_path(self) -> Path:
        return self.pitch_dir / "pitch_contours.json"

    @property
    def note_candidates_path(self) -> Path:
        return self.pitch_dir / "note_candidates.json"

    @property
    def selected_melody_path(self) -> Path:
        return self.pitch_dir / "selected_melody.json"

    @property
    def quantized_notes_path(self) -> Path:
        return self.pitch_dir / "quantized_notes.json"

    @property
    def rhythm_grid_path(self) -> Path:
        return self.pitch_dir / "rhythm_grid.json"

    @property
    def vocal_activity_path(self) -> Path:
        return self.pitch_dir / "vocal_activity.json"

    @property
    def raw_pitch_midi_path(self) -> Path:
        return self.pitch_dir / "raw_pitch.mid"

    @property
    def score_ir_path(self) -> Path:
        return self.score_dir / "score_ir.json"

    @property
    def score_data_path(self) -> Path:
        return self.score_dir / "score_data.json"

    @property
    def semantic_audio_path(self) -> Path:
        return self.score_dir / "semantic_audio.json"

    @property
    def analysis_ir_path(self) -> Path:
        return self.score_dir / "analysis_ir.json"

    @property
    def baseline_alignment_path(self) -> Path:
        return self.alignment_dir / "baseline_alignment.json"

    @property
    def baseline_validator_warnings_path(self) -> Path:
        return self.alignment_dir / "baseline_validator_warnings.json"

    @property
    def refine_response_path(self) -> Path:
        return self.alignment_dir / "refine_response.json"

    @property
    def final_alignment_path(self) -> Path:
        return self.alignment_dir / "final_alignment.json"

    @property
    def refine_debug_path(self) -> Path:
        return self.alignment_dir / "refine_debug.json"

    @property
    def final_midi_path(self) -> Path:
        return self.exports_dir / "final_score.mid"

    @property
    def pipeline_log_path(self) -> Path:
        return self.logs_dir / "pipeline.log"

    @staticmethod
    def normalize_stem_name(stem_name: str) -> str:
        normalized = str(stem_name or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"voice", "vocal"}:
            normalized = "vocals"
        normalized = re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")
        if not normalized:
            raise ValueError("stem_name cannot be empty")
        if not STEM_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("stem_name contains unsupported characters")
        return normalized

    def stem_path(self, stem_name: str) -> Path:
        normalized = self.normalize_stem_name(stem_name)
        path = self.separation_dir / f"{normalized}.wav"
        resolved_root = self.separation_dir.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("stem_name resolves outside separation_dir") from exc
        return path

    def ensure_structure(self) -> None:
        for folder in (
            self.input_dir,
            self.preprocess_dir,
            self.separation_dir,
            self.lyrics_dir,
            self.pitch_dir,
            self.score_dir,
            self.alignment_dir,
            self.exports_dir,
            self.logs_dir,
            self.jobs_dir,
        ):
            folder.mkdir(parents=True, exist_ok=True)

    def save_input_copy(self, source_audio_path: str | Path) -> Path:
        src = Path(source_audio_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"Input audio file not found: {src}")

        self.ensure_structure()
        suffix = src.suffix or ".bin"
        dst = self.input_dir / f"source{suffix}"
        shutil.copy2(src, dst)
        return dst

    def _is_within_projects_root(self) -> bool:
        root = self.projects_root.resolve(strict=False)
        target = (self.projects_root / self.project_id).resolve(strict=False)
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False
