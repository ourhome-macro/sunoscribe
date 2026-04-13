from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(slots=True)
class ProjectWorkspace:
    """Manage per-project folders and artifact paths."""

    project_id: str
    projects_root: Path = Path("data/projects")

    def __post_init__(self) -> None:
        self.project_id = str(self.project_id).strip()
        if not self.project_id:
            raise ValueError("project_id cannot be empty")

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

    @property
    def logs_dir(self) -> Path:
        return self.project_dir / "logs"

    @property
    def normalized_audio_path(self) -> Path:
        return self.preprocess_dir / "normalized.wav"

    @property
    def vocals_path(self) -> Path:
        return self.separation_dir / "vocals.wav"

    @property
    def accompaniment_path(self) -> Path:
        return self.separation_dir / "accompaniment.wav"

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
    def raw_pitch_midi_path(self) -> Path:
        return self.pitch_dir / "raw_pitch.mid"

    @property
    def score_ir_path(self) -> Path:
        return self.score_dir / "score_ir.json"

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
