from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.artifact import Artifact
from app.models.score_revision import ScoreRevision
from app.modules.agents import AgentScorePatch
from app.schemas.agent_workflow import (
    AgentDiagnoseResponse,
    AgentScorePatchProposalResponse,
    ApplyAgentScorePatchRequest,
    PatchValidationStatus,
    PrepareRvcJobRequest,
    ProposeAgentScorePatchRequest,
    PublicArtifactResponse,
    RegenerateExportsResponse,
    RvcJobSpecResponse,
    ScoreRevisionSummaryResponse,
)
from app.services.agent_workflow_service import agent_workflow_service
from app.utils.dependencies import get_current_user
from app.utils.errors import ValidationAppError
from app.utils.responses import success_response

router = APIRouter(prefix="/score-revisions", tags=["agent-workflows"])


@router.post("/{revision_id}/agent/diagnose")
def diagnose_revision_api(
    revision_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    diagnosis = agent_workflow_service.diagnose_transcription(
        db,
        user=current_user,
        revision_id=str(revision_id),
    )
    response = AgentDiagnoseResponse.model_validate(diagnosis.model_dump())
    return success_response(response.model_dump(mode="json"))


@router.post("/{revision_id}/agent/patch/propose")
def propose_agent_score_patch_api(
    revision_id: uuid.UUID,
    payload: ProposeAgentScorePatchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    proposal = agent_workflow_service.propose_score_patch(
        db,
        user=current_user,
        revision_id=str(revision_id),
        instruction=payload.instruction.strip(),
    )
    response = AgentScorePatchProposalResponse(
        base_revision_id=uuid.UUID(str(proposal.base_revision_id)),
        operations=proposal.operations,
        rationale=proposal.rationale,
        confidence=proposal.confidence,
        validation=PatchValidationStatus(accepted=True, errors=[]),
    )
    return success_response(response.model_dump(mode="json"))


@router.post("/{revision_id}/agent/patch/apply")
def apply_agent_score_patch_api(
    revision_id: uuid.UUID,
    payload: ApplyAgentScorePatchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if uuid.UUID(str(payload.base_revision_id)) != revision_id:
        raise ValidationAppError("path revision_id must match patch base_revision_id")

    proposal = AgentScorePatch(
        base_revision_id=str(payload.base_revision_id),
        operations=payload.operations,
        rationale=payload.rationale,
        confidence=payload.confidence,
    )
    revision = agent_workflow_service.apply_score_patch(db, user=current_user, proposal=proposal)
    response = _revision_summary(revision)
    return success_response(response.model_dump(mode="json"), "agent score patch applied")


@router.post("/{revision_id}/agent/rvc/prepare")
def prepare_agent_rvc_job_api(
    revision_id: uuid.UUID,
    payload: PrepareRvcJobRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    spec = agent_workflow_service.prepare_rvc_job(
        db,
        user=current_user,
        revision_id=str(revision_id),
        voice_model_id=payload.voice_model_id,
        transpose_semitones=payload.transpose_semitones,
    )
    response = RvcJobSpecResponse.model_validate(spec.model_dump())
    return success_response(response.model_dump(mode="json"))


@router.post("/{revision_id}/exports/regenerate")
def regenerate_revision_exports_api(
    revision_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    artifacts = agent_workflow_service.regenerate_exports(
        db,
        user=current_user,
        revision_id=str(revision_id),
    )
    response = RegenerateExportsResponse(
        revision_id=revision_id,
        artifacts={
            str(artifact_type): _public_artifact(artifact)
            for artifact_type, artifact in artifacts.items()
        },
    )
    return success_response(response.model_dump(mode="json"), "revision exports regenerated")


def _revision_summary(revision: ScoreRevision) -> ScoreRevisionSummaryResponse:
    artifact_ids: dict[str, uuid.UUID] = {}
    for artifact in list(getattr(revision, "artifacts", None) or []):
        artifact_type = str(getattr(artifact, "artifact_type", "") or "")
        artifact_id = getattr(artifact, "id", None)
        if artifact_type and artifact_id is not None:
            artifact_ids[artifact_type] = uuid.UUID(str(artifact_id))

    return ScoreRevisionSummaryResponse(
        id=uuid.UUID(str(revision.id)),
        project_id=uuid.UUID(str(revision.project_id)),
        score_id=uuid.UUID(str(revision.score_id)),
        parent_revision_id=uuid.UUID(str(revision.parent_revision_id)) if revision.parent_revision_id else None,
        revision_number=int(revision.revision_number),
        revision_type=str(revision.revision_type),
        score_type=str(revision.score_type),
        key=str(revision.key),
        artifact_ids=artifact_ids,
        created_at=revision.created_at,
        updated_at=revision.updated_at,
    )


def _public_artifact(artifact: Artifact) -> PublicArtifactResponse:
    return PublicArtifactResponse(
        id=uuid.UUID(str(artifact.id)),
        artifact_type=str(artifact.artifact_type),
        status=str(artifact.status or "") if artifact.status is not None else None,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
        file_size_bytes=artifact.file_size_bytes,
        checksum=artifact.checksum,
        created_at=artifact.created_at,
    )
