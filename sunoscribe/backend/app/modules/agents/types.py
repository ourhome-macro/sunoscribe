from __future__ import annotations

from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactReference(_AgentModel):
    id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    status: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    storage_path: str | None = None
    score_revision_id: str | None = None
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSkill(_AgentModel):
    name: str = Field(min_length=1)
    description: str | None = None
    path: str
    content: str = Field(min_length=1)
    agent_config_path: str | None = None
    agent_config_content: str | None = None


class AgentSkillContext(_AgentModel):
    skills: list[AgentSkill] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def names(self) -> list[str]:
        return [skill.name for skill in self.skills]


class AgentRevisionContext(_AgentModel):
    project_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    score_ir: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    f0_track: dict[str, Any] | None = None
    note_candidates: dict[str, Any] | None = None
    rhythm_grid: dict[str, Any] | None = None
    vocal_activity: dict[str, Any] | None = None
    skill_context: AgentSkillContext = Field(default_factory=AgentSkillContext)
    warnings: list[str] = Field(default_factory=list)

    def artifact_ids_by_type(self, artifact_type: str) -> list[str]:
        target = str(artifact_type or "").strip().lower()
        return [
            artifact.id
            for artifact in self.artifacts
            if str(artifact.artifact_type or "").strip().lower() == target
        ]

    def skill_names(self) -> list[str]:
        return self.skill_context.names()


class DiagnosisSectionFinding(_AgentModel):
    label: str
    summary: str
    measure_start: int | None = None
    measure_end: int | None = None
    issue_tags: list[str] = Field(default_factory=list)


class DiagnosisIssue(_AgentModel):
    code: str
    severity: Literal["low", "medium", "high"]
    summary: str
    note_ids: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class DiagnosisAction(_AgentModel):
    action: str
    rationale: str


class TranscriptionDiagnosis(_AgentModel):
    summary: str
    section_findings: list[DiagnosisSectionFinding] = Field(default_factory=list)
    suspected_issues: list[DiagnosisIssue] = Field(default_factory=list)
    recommended_actions: list[DiagnosisAction] = Field(default_factory=list)


class _BasePatchOperation(_AgentModel):
    op: str
    reason: str | None = Field(default=None, max_length=500)


class ReplacePitchOperation(_BasePatchOperation):
    op: Literal["replace_pitch"]
    note_id: str = Field(min_length=1)
    pitch_midi: int = Field(ge=0, le=127)


class ShiftOctaveOperation(_BasePatchOperation):
    op: Literal["shift_octave"]
    note_id: str = Field(min_length=1)
    octaves: int = Field(ge=-3, le=3)

    @model_validator(mode="after")
    def _validate_non_zero(self) -> "ShiftOctaveOperation":
        if self.octaves == 0:
            raise ValueError("octaves must not be zero")
        return self


class MergeNotesPatchOperation(_BasePatchOperation):
    op: Literal["merge_notes"]
    note_ids: list[str] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def _validate_unique(self) -> "MergeNotesPatchOperation":
        unique_ids = {note_id.strip() for note_id in self.note_ids if str(note_id).strip()}
        if len(unique_ids) != len(self.note_ids):
            raise ValueError("note_ids must be unique and non-empty")
        return self


class SplitNoteOperation(_BasePatchOperation):
    op: Literal["split_note"]
    note_id: str = Field(min_length=1)
    split_at_time: float | None = Field(default=None, gt=0.0)
    split_ratio: float | None = Field(default=None, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _validate_payload(self) -> "SplitNoteOperation":
        if self.split_at_time is None and self.split_ratio is None:
            raise ValueError("split_note requires split_at_time or split_ratio")
        return self


class DeleteNotePatchOperation(_BasePatchOperation):
    op: Literal["delete_note"]
    note_id: str = Field(min_length=1)


class AdjustDurationOperation(_BasePatchOperation):
    op: Literal["adjust_duration"]
    note_id: str = Field(min_length=1)
    duration_sec: float | None = Field(default=None, gt=0.0)
    duration_beats: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _validate_duration(self) -> "AdjustDurationOperation":
        if self.duration_sec is None and self.duration_beats is None:
            raise ValueError("adjust_duration requires duration_sec or duration_beats")
        return self


class MoveNoteToGridOperation(_BasePatchOperation):
    op: Literal["move_note_to_grid"]
    note_id: str = Field(min_length=1)
    beat_position: float = Field(gt=0.0)
    measure_num: int | None = Field(default=None, ge=1)
    preserve_duration: bool = True


class MarkUncertainOperation(_BasePatchOperation):
    op: Literal["mark_uncertain"]
    note_id: str = Field(min_length=1)


AgentPatchOperation = Annotated[
    Union[
        ReplacePitchOperation,
        ShiftOctaveOperation,
        MergeNotesPatchOperation,
        SplitNoteOperation,
        DeleteNotePatchOperation,
        AdjustDurationOperation,
        MoveNoteToGridOperation,
        MarkUncertainOperation,
    ],
    Field(discriminator="op"),
]


class AgentScorePatch(_AgentModel):
    base_revision_id: str = Field(min_length=1)
    operations: list[AgentPatchOperation] = Field(min_length=1, max_length=128)
    rationale: str | None = Field(default=None, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)


class RvcJobSpec(_AgentModel):
    project_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    vocal_stem_artifact_id: str | None = None
    accompaniment_artifact_id: str | None = None
    corrected_f0_artifact_id: str | None = None
    voice_model_id: str = Field(min_length=1)
    transpose_semitones: int = Field(ge=-24, le=24, default=0)
    warnings: list[str] = Field(default_factory=list)
