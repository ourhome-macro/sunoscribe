from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.types import (
    AgentPatchOperation,
    DiagnosisAction,
    DiagnosisIssue,
    DiagnosisSectionFinding,
    UncertainNoteDiagnosis,
)


class _AgentWorkflowSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentDiagnoseResponse(_AgentWorkflowSchema):
    summary: str
    section_findings: list[DiagnosisSectionFinding] = Field(default_factory=list)
    suspected_issues: list[DiagnosisIssue] = Field(default_factory=list)
    uncertain_notes: list[UncertainNoteDiagnosis] = Field(default_factory=list)
    recommended_actions: list[DiagnosisAction] = Field(default_factory=list)


class ProposeAgentScorePatchRequest(_AgentWorkflowSchema):
    instruction: str = Field(min_length=1, max_length=2000)


class PatchValidationStatus(_AgentWorkflowSchema):
    accepted: bool
    errors: list[Any] = Field(default_factory=list)


class ScoreNoteClientSummary(_AgentWorkflowSchema):
    note_id: str
    pitch: str
    onset_tick: int | None = None
    duration_tick: int | None = None
    measure: int | None = None
    beat: float | None = None
    confidence: float | None = None
    uncertain: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    source_candidate_id: str | None = None
    quantized_note_id: str | None = None


class ScoreRevisionClientSummary(_AgentWorkflowSchema):
    revision_id: uuid.UUID
    parent_revision_id: uuid.UUID | None = None
    note_count: int
    uncertain_note_count: int
    low_confidence_note_count: int
    low_confidence_regions: list[dict[str, Any]] = Field(default_factory=list)
    export_status: str
    score_notes: list[ScoreNoteClientSummary] = Field(default_factory=list)


class AgentScorePatchProposalResponse(_AgentWorkflowSchema):
    base_revision_id: uuid.UUID
    operations: list[AgentPatchOperation] = Field(default_factory=list)
    rationale: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    validation: PatchValidationStatus


class ApplyAgentScorePatchRequest(_AgentWorkflowSchema):
    base_revision_id: uuid.UUID
    operations: list[AgentPatchOperation] = Field(min_length=1, max_length=128)
    rationale: str | None = Field(default=None, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_operation_count(self) -> "ApplyAgentScorePatchRequest":
        if not self.operations:
            raise ValueError("operations must not be empty")
        return self


class ScoreRevisionSummaryResponse(_AgentWorkflowSchema):
    id: uuid.UUID
    project_id: uuid.UUID
    score_id: uuid.UUID
    parent_revision_id: uuid.UUID | None = None
    revision_number: int
    revision_type: str
    score_type: str
    key: str
    artifact_ids: dict[str, uuid.UUID] = Field(default_factory=dict)
    client_summary: ScoreRevisionClientSummary | None = None
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PrepareRvcJobRequest(_AgentWorkflowSchema):
    voice_model_id: str = Field(min_length=1, max_length=128)
    transpose_semitones: int = Field(default=0, ge=-24, le=24)


class RvcJobSpecResponse(_AgentWorkflowSchema):
    project_id: uuid.UUID
    revision_id: uuid.UUID
    vocal_stem_artifact_id: uuid.UUID | None = None
    accompaniment_artifact_id: uuid.UUID | None = None
    corrected_f0_artifact_id: uuid.UUID | None = None
    voice_model_id: str
    transpose_semitones: int
    warnings: list[str] = Field(default_factory=list)


class PublicArtifactResponse(_AgentWorkflowSchema):
    id: uuid.UUID
    artifact_type: str
    status: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    checksum: str | None = None
    created_at: datetime | None = None


class RegenerateExportsResponse(_AgentWorkflowSchema):
    revision_id: uuid.UUID
    artifacts: dict[str, PublicArtifactResponse] = Field(default_factory=dict)
