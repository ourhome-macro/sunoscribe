from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.models.artifact import Artifact
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.models.user import User
from app.modules.agents import AgentScorePatch, RvcJobSpec, TranscriptionDiagnosis
from app.modules.agents.types import AgentSkill, AgentSkillContext
from app.modules.agents.validators import RvcSpecValidationResult
from app.services.agent_workflow_service import AgentWorkflowService


def _build_revision() -> tuple[Score, ScoreRevision]:
    score = Score(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        score_type="staff",
        key="C Major",
        score_data={"meta": {"bpm": 120.0}},
    )
    revision = ScoreRevision(
        id=uuid.uuid4(),
        project_id=score.project_id,
        score_id=score.id,
        revision_number=1,
        revision_type="machine",
        score_type="staff",
        key="C Major",
        score_ir={
            "meta": {"time_signature": "4/4"},
            "notes": [
                {
                    "id": "n1",
                    "pitch": "C4",
                    "pitch_midi": 60,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "duration_sec": 1.0,
                    "duration_beats": 2.0,
                    "measure_num": 1,
                    "beat_position": 1.0,
                    "confidence": 0.9,
                    "lyric": None,
                }
            ],
            "measures": [
                {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "is_anacrusis": False, "note_ids": ["n1"]}
            ],
            "warnings": [],
        },
        score_data={"meta": {"bpm": 120.0}, "analysis_ir": {"version": "analysis_ir_v1"}},
        patch_data={},
        revision_metadata={},
    )
    revision.score = score
    score.revisions = [revision]
    score.current_revision = revision
    score.current_revision_id = revision.id
    return score, revision


class TestAgentWorkflowService(unittest.TestCase):
    def test_build_context_from_revision_reads_json_artifacts(self) -> None:
        score, revision = _build_revision()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            note_candidates_path = root / "note_candidates.json"
            rhythm_grid_path = root / "rhythm_grid.json"
            f0_path.write_text(
                json.dumps({"frames": [], "vocal_activity": [{"state": "vocal", "start_time": 0.0, "end_time": 1.0}]}),
                encoding="utf-8",
            )
            note_candidates_path.write_text(json.dumps({"role": "melody_candidates"}), encoding="utf-8")
            rhythm_grid_path.write_text(json.dumps({"beats_per_bar": 4}), encoding="utf-8")

            artifacts = [
                Artifact(
                    id=uuid.uuid4(),
                    project_id=score.project_id,
                    score_id=score.id,
                    score_revision_id=revision.id,
                    artifact_type="f0_track",
                    storage_path=str(f0_path),
                ),
                Artifact(
                    id=uuid.uuid4(),
                    project_id=score.project_id,
                    score_id=score.id,
                    score_revision_id=revision.id,
                    artifact_type="note_candidates",
                    storage_path=str(note_candidates_path),
                ),
                Artifact(
                    id=uuid.uuid4(),
                    project_id=score.project_id,
                    score_id=score.id,
                    score_revision_id=revision.id,
                    artifact_type="rhythm_grid",
                    storage_path=str(rhythm_grid_path),
                ),
            ]

            context = AgentWorkflowService(auto_configure_llm_client=False).build_context_from_revision(revision=revision, artifacts=artifacts)

        self.assertIsNotNone(context.f0_track)
        self.assertIsNotNone(context.note_candidates)
        self.assertIsNotNone(context.rhythm_grid)
        self.assertIsNotNone(context.vocal_activity)
        self.assertEqual(context.vocal_activity["segments"][0]["state"], "vocal")

    def test_agent_methods_attach_profile_skill_context_from_registry(self) -> None:
        _, revision = _build_revision()
        diagnosis_agent = _SpyDiagnosisAgent()
        patch_agent = _SpyScorePatchAgent()
        rvc_agent = _SpyRvcPrepareAgent()
        service = AgentWorkflowService(
            diagnosis_agent=diagnosis_agent,
            score_patch_agent=patch_agent,
            rvc_prepare_agent=rvc_agent,
            score_patch_validator=_AcceptingPatchValidator(),
            rvc_spec_validator=_AcceptingRvcValidator(),
            auto_configure_llm_client=False,
        )
        service.skill_registry = _StaticSkillRegistry()
        service._list_revision_artifacts = lambda *args, **kwargs: []
        user = User(id=uuid.uuid4(), username="agent", email="agent@example.com", password_hash="x")

        with patch("app.services.agent_workflow_service.get_score_revision_by_id", return_value=revision):
            service.diagnose_transcription(None, user=user, revision_id=str(revision.id))
            service.propose_score_patch(None, user=user, revision_id=str(revision.id), instruction="patch n1")
            service.prepare_rvc_job(
                None,
                user=user,
                revision_id=str(revision.id),
                voice_model_id="voice-model-1",
            )

        self.assertEqual(diagnosis_agent.context.skill_context.names(), ["mir-transcription", "debug-diagnosis"])
        self.assertEqual(patch_agent.context.skill_context.names(), ["score-ir-editing"])
        self.assertEqual(rvc_agent.context.skill_context.names(), ["rvc-cover"])

    def test_apply_patch_to_revision_creates_new_revision(self) -> None:
        score, revision = _build_revision()
        user = User(id=uuid.uuid4(), username="agent", email="agent@example.com", password_hash="x")
        service = AgentWorkflowService(auto_configure_llm_client=False)
        context = service.build_context_from_revision(revision=revision, artifacts=[])

        new_revision = service.apply_patch_to_revision(
            None,
            base_revision=revision,
            score=score,
            user=user,
            context=context,
            proposal={
                "base_revision_id": str(revision.id),
                "confidence": 0.91,
                "rationale": "raise the opening note",
                "operations": [{"op": "shift_octave", "note_id": "n1", "octaves": 1}],
            },
            commit=False,
        )

        self.assertEqual(new_revision.parent_revision_id, revision.id)
        self.assertEqual(new_revision.score_ir["notes"][0]["pitch_midi"], 72)
        self.assertEqual(score.current_revision, new_revision)

    def test_score_patch_text_instruction_uses_llm_client_when_configured(self) -> None:
        _, revision = _build_revision()
        llm_client = _SpyScorePatchLLMClient()
        service = AgentWorkflowService(
            score_patch_llm_client=llm_client,
            score_patch_validator=_AcceptingPatchValidator(),
            skill_registry=_StaticSkillRegistry(),
        )
        service._list_revision_artifacts = lambda *args, **kwargs: []
        user = User(id=uuid.uuid4(), username="agent", email="agent@example.com", password_hash="x")

        with patch("app.services.agent_workflow_service.get_score_revision_by_id", return_value=revision):
            proposal = service.propose_score_patch(
                None,
                user=user,
                revision_id=str(revision.id),
                instruction="raise n1 one octave",
            )

        self.assertEqual(llm_client.instruction, "raise n1 one octave")
        self.assertEqual(llm_client.context.skill_context.names(), ["score-ir-editing"])
        self.assertEqual(proposal.operations[0].op, "mark_uncertain")

    def test_structured_score_patch_bypasses_llm_client(self) -> None:
        _, revision = _build_revision()
        llm_client = _SpyScorePatchLLMClient()
        service = AgentWorkflowService(
            score_patch_llm_client=llm_client,
            score_patch_validator=_AcceptingPatchValidator(),
            skill_registry=_StaticSkillRegistry(),
        )
        service._list_revision_artifacts = lambda *args, **kwargs: []
        user = User(id=uuid.uuid4(), username="agent", email="agent@example.com", password_hash="x")

        with patch("app.services.agent_workflow_service.get_score_revision_by_id", return_value=revision):
            proposal = service.propose_score_patch(
                None,
                user=user,
                revision_id=str(revision.id),
                instruction={
                    "base_revision_id": str(revision.id),
                    "operations": [{"op": "shift_octave", "note_id": "n1", "octaves": 1}],
                    "confidence": 0.8,
                },
            )

        self.assertIsNone(llm_client.instruction)
        self.assertEqual(proposal.operations[0].op, "shift_octave")


class _StaticSkillRegistry:
    payload_by_profile = {
        "diagnosis": AgentSkillContext(
            skills=[
                AgentSkill(
                    name="mir-transcription",
                    path="skills/mir-transcription/SKILL.md",
                    content="mir transcription rules",
                ),
                AgentSkill(
                    name="debug-diagnosis",
                    path="skills/debug-diagnosis/SKILL.md",
                    content="debug diagnosis rules",
                ),
            ]
        ),
        "score_patch": AgentSkillContext(
            skills=[
                AgentSkill(
                    name="score-ir-editing",
                    path="skills/score-ir-editing/SKILL.md",
                    content="score patch rules",
                ),
            ]
        ),
        "rvc": AgentSkillContext(
            skills=[
                AgentSkill(
                    name="rvc-cover",
                    path="skills/rvc-cover/SKILL.md",
                    content="rvc cover rules",
                ),
            ]
        ),
    }
    all_skills = AgentSkillContext(
        skills=[
            AgentSkill(
                name="mir-transcription",
                path="skills/mir-transcription/SKILL.md",
                content="mir transcription rules",
            ),
            AgentSkill(
                name="score-ir-editing",
                path="skills/score-ir-editing/SKILL.md",
                content="score patch rules",
            ),
            AgentSkill(
                name="debug-diagnosis",
                path="skills/debug-diagnosis/SKILL.md",
                content="debug diagnosis rules",
            ),
            AgentSkill(
                name="rvc-cover",
                path="skills/rvc-cover/SKILL.md",
                content="rvc cover rules",
            ),
        ]
    )

    def build_context(self, *_args, **_kwargs) -> AgentSkillContext:
        return self.all_skills

    def read_skill_context(self, *_args, **_kwargs) -> AgentSkillContext:
        return self.all_skills

    def context_for_profile(self, profile: str) -> AgentSkillContext:
        return self.payload_by_profile[str(profile)]


class _SpyDiagnosisAgent:
    def __init__(self) -> None:
        self.context = None

    def run(self, context):
        self.context = context
        return TranscriptionDiagnosis(summary="ok")


class _SpyScorePatchAgent:
    def __init__(self) -> None:
        self.context = None

    def propose(self, context, _instruction):
        self.context = context
        return AgentScorePatch(
            base_revision_id=context.revision_id,
            operations=[{"op": "mark_uncertain", "note_id": "n1"}],
            rationale="test",
            confidence=0.9,
        )


class _SpyRvcPrepareAgent:
    def __init__(self) -> None:
        self.context = None

    def prepare(self, context, *, voice_model_id: str, transpose_semitones: int = 0):
        self.context = context
        return RvcJobSpec(
            project_id=context.project_id,
            revision_id=context.revision_id,
            voice_model_id=voice_model_id,
            transpose_semitones=transpose_semitones,
        )


class _SpyScorePatchLLMClient:
    def __init__(self) -> None:
        self.context = None
        self.instruction = None

    def propose_score_patch(self, *, context, instruction):
        self.context = context
        self.instruction = instruction
        return AgentScorePatch(
            base_revision_id=context.revision_id,
            operations=[{"op": "mark_uncertain", "note_id": "n1"}],
            rationale="llm proposal",
            confidence=0.75,
        )


class _AcceptingPatchValidator:
    def validate(self, *, context, proposal):
        self.context = context
        return {"accepted": True, "errors": []}


class _AcceptingRvcValidator:
    def validate(self, *, context, spec):
        self.context = context
        return RvcSpecValidationResult(accepted=True, errors=[])


if __name__ == "__main__":
    unittest.main()

