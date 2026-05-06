from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.artifact import Artifact
from app.models.enums import ScoreRevisionType
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.models.user import User
from app.modules.agents import (
    AgentRevisionContext,
    AgentScorePatch,
    AgentScorePatchValidator,
    ArtifactReference,
    DiagnosisAgent,
    RvcJobSpec,
    RvcPrepareAgent,
    RvcSpecValidator,
    ScorePatchAgent,
    AgentSkillContext,
    AgentSkillRegistry,
    TranscriptionDiagnosis,
)
from app.modules.agents.llm_client import ScorePatchLLMClient, make_openai_score_patch_llm_client
from app.services.render_export_service import RenderExportService
from app.services.score_revision_service import get_score_revision_by_id
from app.utils.errors import ValidationAppError


class AgentWorkflowService:
    """Post-ScoreRevision agent orchestration over typed artifacts."""

    def __init__(
        self,
        *,
        diagnosis_agent: DiagnosisAgent | None = None,
        score_patch_agent: ScorePatchAgent | None = None,
        rvc_prepare_agent: RvcPrepareAgent | None = None,
        score_patch_validator: AgentScorePatchValidator | None = None,
        rvc_spec_validator: RvcSpecValidator | None = None,
        skill_registry: AgentSkillRegistry | None = None,
        export_service: RenderExportService | None = None,
        score_patch_llm_client: ScorePatchLLMClient | None = None,
        auto_configure_llm_client: bool = True,
    ) -> None:
        self.diagnosis_agent = diagnosis_agent or DiagnosisAgent()
        self.score_patch_agent = score_patch_agent or ScorePatchAgent()
        self.rvc_prepare_agent = rvc_prepare_agent or RvcPrepareAgent()
        self.score_patch_validator = score_patch_validator or AgentScorePatchValidator()
        self.rvc_spec_validator = rvc_spec_validator or RvcSpecValidator()
        self.skill_registry = skill_registry or AgentSkillRegistry()
        self.export_service = export_service or RenderExportService()
        self.score_patch_llm_client = score_patch_llm_client or (
            self._try_make_score_patch_llm_client() if auto_configure_llm_client else None
        )

    def load_context(
        self,
        db: Session,
        *,
        user: User,
        revision_id: str,
        skill_profile: str | None = None,
    ) -> AgentRevisionContext:
        revision = get_score_revision_by_id(db, user=user, revision_id=revision_id)
        artifacts = list(self._list_revision_artifacts(db, revision_id=str(revision.id)))
        return self.build_context_from_revision(
            revision=revision,
            artifacts=artifacts,
            skill_profile=skill_profile,
        )

    def build_context_from_revision(
        self,
        *,
        revision: ScoreRevision,
        artifacts: list[Artifact],
        skill_profile: str | None = None,
    ) -> AgentRevisionContext:
        artifact_refs = [self._artifact_ref(artifact) for artifact in artifacts]
        warnings = self._collect_context_warnings(revision=revision, artifacts=artifacts)
        skill_context = self._load_skill_context(skill_profile)
        warnings.extend(skill_context.warnings)

        f0_track = self._read_json_artifact_by_type(artifacts, "f0_track", warnings)
        note_candidates = self._read_json_artifact_by_type(artifacts, "note_candidates", warnings)
        rhythm_grid = self._read_json_artifact_by_type(artifacts, "rhythm_grid", warnings)
        vocal_activity = self._extract_vocal_activity(f0_track=f0_track)
        if vocal_activity is None:
            warnings.append("agent_context_missing_vocal_activity")

        if f0_track is None:
            warnings.append("agent_context_missing_f0_track")
        if note_candidates is None:
            warnings.append("agent_context_missing_note_candidates")
        if rhythm_grid is None:
            warnings.append("agent_context_missing_rhythm_grid")

        return AgentRevisionContext(
            project_id=str(revision.project_id),
            revision_id=str(revision.id),
            score_ir=dict(revision.score_ir or {}),
            artifacts=artifact_refs,
            f0_track=f0_track,
            note_candidates=note_candidates,
            rhythm_grid=rhythm_grid,
            vocal_activity=vocal_activity,
            skill_context=skill_context,
            warnings=self._dedupe_strings(warnings),
        )

    def diagnose_transcription(self, db: Session, *, user: User, revision_id: str) -> TranscriptionDiagnosis:
        context = self.load_context(db, user=user, revision_id=revision_id, skill_profile="diagnosis")
        return self.diagnosis_agent.run(context)

    def propose_score_patch(
        self,
        db: Session,
        *,
        user: User,
        revision_id: str,
        instruction: str | dict[str, Any] | AgentScorePatch,
    ) -> AgentScorePatch:
        context = self.load_context(db, user=user, revision_id=revision_id, skill_profile="score_patch")
        proposal = self._propose_score_patch(context=context, instruction=instruction)
        validation = self.score_patch_validator.validate(context=context, proposal=proposal)
        if not bool(validation.get("accepted", False)):
            raise ValidationAppError("agent-generated score patch proposal is invalid", details=validation)
        return proposal

    def _propose_score_patch(
        self,
        *,
        context: AgentRevisionContext,
        instruction: str | dict[str, Any] | AgentScorePatch,
    ) -> AgentScorePatch:
        if isinstance(instruction, AgentScorePatch) or isinstance(instruction, dict):
            return self.score_patch_agent.propose(context, instruction)
        if self.score_patch_llm_client is not None:
            return self.score_patch_llm_client.propose_score_patch(context=context, instruction=str(instruction or ""))
        return self.score_patch_agent.propose(context, instruction)

    def apply_score_patch(
        self,
        db: Session,
        *,
        user: User,
        proposal: AgentScorePatch | dict[str, Any],
    ) -> ScoreRevision:
        score_patch = proposal if isinstance(proposal, AgentScorePatch) else AgentScorePatch.model_validate(proposal)
        base_revision = get_score_revision_by_id(db, user=user, revision_id=score_patch.base_revision_id)
        if base_revision.score is None:
            raise ValidationAppError("base revision is detached from its score")
        context = self.build_context_from_revision(
            revision=base_revision,
            artifacts=list(self._list_revision_artifacts(db, revision_id=str(base_revision.id))),
            skill_profile="score_patch",
        )
        return self.apply_patch_to_revision(
            db,
            base_revision=base_revision,
            score=base_revision.score,
            user=user,
            context=context,
            proposal=score_patch,
            commit=True,
        )

    def apply_patch_to_revision(
        self,
        db: Session | None,
        *,
        base_revision: ScoreRevision,
        score: Score,
        user: User,
        context: AgentRevisionContext,
        proposal: AgentScorePatch | dict[str, Any],
        commit: bool = False,
    ) -> ScoreRevision:
        score_patch = proposal if isinstance(proposal, AgentScorePatch) else AgentScorePatch.model_validate(proposal)
        validation_result = self.score_patch_validator.validate_and_apply(context=context, proposal=score_patch)
        patched_score_data = self.score_patch_validator._patch_validator._build_score_data_from_score_ir(
            validation_result.score_ir,
            score_data=deepcopy(base_revision.score_data) if isinstance(base_revision.score_data, dict) else {},
        )

        revision = ScoreRevision(
            id=uuid.uuid4(),
            project_id=base_revision.project_id,
            score_id=base_revision.score_id,
            parent_revision_id=base_revision.id,
            created_by_user_id=user.id,
            revision_number=self._next_revision_number(db, score),
            revision_type=ScoreRevisionType.USER.value,
            score_type=base_revision.score_type,
            key=base_revision.key,
            vocal_range=base_revision.vocal_range,
            recommended_voice=base_revision.recommended_voice,
            emotion=base_revision.emotion,
            score_ir=validation_result.score_ir,
            score_data=patched_score_data,
            patch_data=validation_result.patch_data,
            revision_metadata={
                **(base_revision.revision_metadata if isinstance(base_revision.revision_metadata, dict) else {}),
                "base_revision_id": str(base_revision.id),
                "agent_workflow": {
                    "rationale": score_patch.rationale,
                    "confidence": score_patch.confidence,
                    "operation_count": len(score_patch.operations),
                },
            },
        )
        revision.score = score
        score.current_revision = revision
        score.current_revision_id = revision.id
        score.score_data = dict(patched_score_data or {})

        if db is not None:
            db.add(score)
            db.add(revision)
            self.export_service.ensure_core_exports(db, score=score, revision=revision)
            if commit:
                db.commit()
                db.refresh(revision)
        return revision

    def prepare_rvc_job(
        self,
        db: Session,
        *,
        user: User,
        revision_id: str,
        voice_model_id: str,
        transpose_semitones: int = 0,
    ) -> RvcJobSpec:
        context = self.load_context(db, user=user, revision_id=revision_id, skill_profile="rvc")
        spec = self.rvc_prepare_agent.prepare(
            context,
            voice_model_id=voice_model_id,
            transpose_semitones=transpose_semitones,
        )
        validation = self.rvc_spec_validator.validate(context=context, spec=spec)
        if not validation.accepted:
            raise ValidationAppError("agent-generated RVC job spec is invalid", details={"errors": validation.errors})
        return spec

    def regenerate_exports(
        self,
        db: Session,
        *,
        user: User,
        revision_id: str,
    ) -> dict[str, Artifact]:
        revision = get_score_revision_by_id(db, user=user, revision_id=revision_id)
        if revision.score is None:
            raise ValidationAppError("revision is detached from its score")
        artifacts = self.export_service.ensure_core_exports(db, score=revision.score, revision=revision)
        db.commit()
        return artifacts

    def _list_revision_artifacts(self, db: Session, *, revision_id: str) -> list[Artifact]:
        revision_uuid = uuid.UUID(str(revision_id))
        stmt = (
            select(Artifact)
            .where(Artifact.score_revision_id == revision_uuid)
            .order_by(Artifact.created_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    def _artifact_ref(self, artifact: Artifact) -> ArtifactReference:
        return ArtifactReference(
            id=str(artifact.id),
            artifact_type=str(artifact.artifact_type),
            status=str(artifact.status or ""),
            filename=artifact.filename,
            mime_type=artifact.mime_type,
            storage_path=artifact.storage_path,
            score_revision_id=str(artifact.score_revision_id) if artifact.score_revision_id else None,
            artifact_metadata=dict(artifact.artifact_metadata or {}),
        )

    def _collect_context_warnings(self, *, revision: ScoreRevision, artifacts: list[Artifact]) -> list[str]:
        warnings: list[str] = []
        score_ir = revision.score_ir if isinstance(revision.score_ir, dict) else {}
        for item in score_ir.get("warnings") or []:
            text = str(item).strip()
            if text:
                warnings.append(text)
        metadata = revision.revision_metadata if isinstance(revision.revision_metadata, dict) else {}
        for item in metadata.get("warnings") or []:
            text = str(item).strip()
            if text:
                warnings.append(text)
        if not artifacts:
            warnings.append("agent_context_has_no_artifacts")
        return warnings

    def _read_json_artifact_by_type(
        self,
        artifacts: list[Artifact],
        artifact_type: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        candidates = [
            artifact
            for artifact in artifacts
            if str(artifact.artifact_type or "").strip().lower() == str(artifact_type or "").strip().lower()
        ]
        for artifact in candidates:
            payload = self._read_json_artifact(artifact, warnings)
            if payload is not None:
                return payload
        return None

    def _read_json_artifact(self, artifact: Artifact, warnings: list[str]) -> dict[str, Any] | None:
        path_text = str(artifact.storage_path or "").strip()
        if not path_text:
            warnings.append(f"artifact_missing_storage_path:{artifact.artifact_type}")
            return None
        target = Path(path_text)
        if not target.exists() or not target.is_file():
            warnings.append(f"artifact_missing_file:{artifact.artifact_type}")
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            warnings.append(f"artifact_invalid_json:{artifact.artifact_type}")
            return None
        return payload if isinstance(payload, dict) else {"value": payload}

    def _load_skill_context(self, skill_profile: str | None) -> AgentSkillContext:
        if not skill_profile:
            return AgentSkillContext()
        return self.skill_registry.context_for_profile(skill_profile)

    def _extract_vocal_activity(self, *, f0_track: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(f0_track, dict):
            return None
        raw = f0_track.get("vocal_activity")
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, list):
            return {"segments": list(raw)}
        return None

    def _next_revision_number(self, db: Session | None, score: Score) -> int:
        revisions = list(getattr(score, "revisions", None) or [])
        if revisions:
            return max(int(revision.revision_number) for revision in revisions) + 1
        if db is None:
            current = int(getattr(getattr(score, "current_revision", None), "revision_number", 0) or 0)
            return current + 1
        stmt = select(func.max(ScoreRevision.revision_number)).where(ScoreRevision.score_id == score.id)
        value = db.execute(stmt).scalar_one_or_none()
        return int(value or 0) + 1

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in deduped:
                deduped.append(text)
        return deduped

    @staticmethod
    def _try_make_score_patch_llm_client() -> ScorePatchLLMClient | None:
        if not bool(getattr(settings, "agent_llm_enabled", False)):
            return None
        if str(getattr(settings, "agent_llm_provider", "openai") or "openai").strip().lower() != "openai":
            return None
        return make_openai_score_patch_llm_client(
            api_key=getattr(settings, "openai_api_key", None),
            model=getattr(settings, "agent_llm_model", "gpt-5.4-mini"),
        )


agent_workflow_service = AgentWorkflowService()

