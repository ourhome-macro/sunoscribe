from __future__ import annotations

import importlib
import inspect
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.modules.agents import AgentRevisionContext, AgentScorePatchValidator
from app.services.agent_workflow_service import AgentWorkflowService


ALLOWED_SKILLS = {
    "mir-transcription",
    "score-ir-editing",
    "debug-diagnosis",
    "rvc-cover",
}


def _load_registry_class() -> type[Any]:
    errors: list[str] = []
    candidates = (
        ("app.modules.agents.skill_registry", "AgentSkillRegistry"),
        ("app.modules.agents.skill_registry", "SkillRegistry"),
        ("app.services.agent_skill_registry", "AgentSkillRegistry"),
        ("app.services.agent_skill_registry", "SkillRegistry"),
    )
    for module_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except Exception as exc:
            errors.append(f"{module_name}.{class_name}: {exc}")
    raise AssertionError("agent skill registry is missing. Tried:\n" + "\n".join(errors))


def _make_registry(skills_root: Path) -> Any:
    registry_cls = _load_registry_class()
    signature = inspect.signature(registry_cls)
    kwargs: dict[str, Any] = {}
    root_names = {"skills_root", "skill_root", "root_path", "base_path", "base_dir"}
    allowed_names = {"allowed_skills", "whitelist", "skill_whitelist"}

    for name in signature.parameters:
        if name in root_names:
            kwargs[name] = skills_root
        if name in allowed_names:
            kwargs[name] = set(ALLOWED_SKILLS)

    if kwargs:
        return registry_cls(**kwargs)
    return registry_cls(skills_root)


def _read_skill(registry: Any, skill_name: str) -> Any:
    for method_name in ("read_skill", "load_skill", "get_skill", "read_skill_context", "get_skill_context"):
        method = getattr(registry, method_name, None)
        if callable(method):
            return method(skill_name)
    raise AssertionError("agent skill registry must expose a read/load method for one skill")


def _payload_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return "\n".join(str(value) for value in payload.values())
    return str(payload)


def _get_value(payload: Any, key: str, default: Any = None) -> Any:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _write_skill(root: Path, name: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    agent_dir = skill_dir / "agents"
    agent_dir.mkdir()
    (agent_dir / "openai.yaml").write_text(
        f'interface:\n  display_name: "{name}"\n',
        encoding="utf-8",
    )


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
                }
            ],
            "measures": [
                {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "is_anacrusis": False, "note_ids": ["n1"]}
            ],
            "warnings": [],
        },
        score_data={"meta": {"bpm": 120.0}},
        patch_data={},
        revision_metadata={},
    )
    revision.score = score
    return score, revision


class TestAgentSkillRegistry(unittest.TestCase):
    def test_reads_only_whitelisted_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for skill_name in ALLOWED_SKILLS:
                _write_skill(root, skill_name, f"# {skill_name}\nallowed skill body")
            _write_skill(root, "not-approved", "# not-approved\nmust not be readable")

            registry = _make_registry(root)

            for skill_name in ALLOWED_SKILLS:
                payload = _read_skill(registry, skill_name)
                self.assertIn(skill_name, _payload_text(payload))
                self.assertIn(skill_name, _get_value(payload, "agent_config_content", ""))

            with self.assertRaises(Exception) as raised:
                _read_skill(registry, "not-approved")

        self.assertNotIn("must not be readable", str(raised.exception))

    def test_rejects_path_traversal_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret = root.parent / "agent_skill_secret.txt"
            secret.write_text("secret outside skill registry", encoding="utf-8")
            _write_skill(root, "mir-transcription", "# mir-transcription\nallowed")

            registry = _make_registry(root)
            malicious_names = [
                "../agent_skill_secret.txt",
                "..\\agent_skill_secret.txt",
                str(secret),
                "mir-transcription/../agent_skill_secret.txt",
            ]

            for skill_name in malicious_names:
                with self.subTest(skill_name=skill_name):
                    with self.assertRaises(Exception) as raised:
                        _read_skill(registry, skill_name)
                    self.assertNotIn("secret outside skill registry", str(raised.exception))

            secret.unlink(missing_ok=True)

    def test_workflow_context_includes_profile_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for skill_name in ALLOWED_SKILLS:
                _write_skill(root, skill_name, f"---\nname: {skill_name}\ndescription: {skill_name} guidance\n---\n# {skill_name}")

            _, revision = _build_revision()
            registry = _make_registry(root)
            service = AgentWorkflowService(skill_registry=registry)
            diagnosis_context = service.build_context_from_revision(
                revision=revision,
                artifacts=[],
                skill_profile="diagnosis",
            )
            patch_context = service.build_context_from_revision(
                revision=revision,
                artifacts=[],
                skill_profile="score_patch",
            )
            rvc_context = service.build_context_from_revision(
                revision=revision,
                artifacts=[],
                skill_profile="rvc",
            )

        self.assertEqual(diagnosis_context.skill_names(), ["mir-transcription", "debug-diagnosis"])
        self.assertEqual(patch_context.skill_names(), ["score-ir-editing"])
        self.assertEqual(rvc_context.skill_names(), ["rvc-cover"])

    def test_skill_context_does_not_bypass_patch_validation(self) -> None:
        context = AgentRevisionContext(
            project_id="project-001",
            revision_id="revision-001",
            score_ir={
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
                    }
                ],
                "measures": [
                    {
                        "measure_num": 1,
                        "start_time": 0.0,
                        "end_time": 2.0,
                        "note_ids": ["n1"],
                    }
                ],
            },
            skill_context={"skills": [{"name": "score-ir-editing", "path": "skills/score-ir-editing/SKILL.md", "content": "# ScoreIR Editing"}]},
        )

        validation = AgentScorePatchValidator().validate(
            context=context,
            proposal={
                "base_revision_id": "revision-001",
                "confidence": 0.9,
                "operations": [{"op": "replace_pitch", "note_id": "missing", "pitch_midi": 64}],
            },
        )

        self.assertFalse(validation["accepted"])


if __name__ == "__main__":
    unittest.main()
