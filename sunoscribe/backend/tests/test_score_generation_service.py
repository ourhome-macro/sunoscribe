from __future__ import annotations

import importlib
import inspect
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


def _load_first_attr(*candidates: tuple[str, str]) -> tuple[Any, str]:
    errors: list[str] = []
    for module_name, attr_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
            continue
        if hasattr(module, attr_name):
            return getattr(module, attr_name), module_name
        errors.append(f"{module_name}: missing {attr_name}")
    raise AssertionError("No generation entrypoint found. Tried:\n" + "\n".join(errors))


def _call_with_known_kwargs(fn: Any, pool: dict[str, Any]) -> Any:
    signature = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    missing: list[str] = []

    for name, parameter in signature.parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in pool:
            kwargs[name] = pool[name]
            continue
        if parameter.default is inspect._empty:
            missing.append(name)

    if missing:
        raise AssertionError(f"Cannot call {fn.__module__}.{fn.__name__}; missing required params: {missing}")
    return fn(**kwargs)


def _fallback_analysis_result(project_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        project_id=project_id,
        source_audio_path=f"data/projects/{project_id}/input/source.wav",
        normalized_audio_path=None,
        vocals_path=f"data/projects/{project_id}/separation/vocals.wav",
        accompaniment_path=f"data/projects/{project_id}/separation/accompaniment.wav",
        lyrics_segments=[],
        pitch_result={"analysis_info": {"detector": "rmvpe"}},
        analysis_ir={"summary": "fallback"},
        score_data={"meta": {"analysis_info": {"fallback": True}}, "measures": []},
        score_ir={"meta": {"analysis_info": {"fallback": True}}, "notes": []},
        baseline_alignment={},
        baseline_validator_warnings=[],
        refined_alignment=None,
        final_alignment={},
        alignment_source="baseline",
        alignment_accepted=False,
        refine_warnings=[],
        validator_warnings_before=[],
        validator_warnings_after=[],
        refine_debug=None,
        midi_path=None,
        stem_paths={},
        semantic_audio=None,
        warnings=["score_ir_is_empty_fallback"],
    )


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.added: list[Any] = []
        self.commit_count = 0

    def execute(self, _stmt: Any) -> _ScalarResult:
        if not self._responses:
            raise AssertionError("FakeSession exhausted")
        return _ScalarResult(self._responses.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commit_count += 1

    def refresh(self, _obj: Any) -> None:
        return None


class TestScoreGenerationServiceContracts(unittest.TestCase):
    def _load_generation_entrypoint(self) -> tuple[Any, str]:
        return _load_first_attr(
            ("app.services.score_revision_service", "create_machine_score_revision"),
            ("app.services.score_revision_service", "create_machine_revision"),
            ("app.services.score_revision_service", "create_revision_from_analysis"),
            ("app.services.score_service", "generate_or_regenerate_score"),
        )

    def test_generation_entrypoint_requires_project_context(self) -> None:
        entrypoint, _module_name = self._load_generation_entrypoint()
        params = set(inspect.signature(entrypoint).parameters)
        self.assertTrue({"project_id", "project"} & params, "generation must be project scoped")
        self.assertTrue(
            {"analysis_result", "score_ir", "score_data"} & params or "project_id" in params,
            "generation must consume typed analysis outputs or a project that can produce them",
        )

    def test_generation_rejects_missing_audio_instead_of_backend_stub_fallback(self) -> None:
        entrypoint, _module_name = self._load_generation_entrypoint()
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=user.id,
            audio_path=None,
            status="processing",
            progress=30,
        )
        db = _FakeSession([project, None, None])

        call_pool = {
            "db": db,
            "session": db,
            "user": user,
            "current_user": user,
            "project": project,
            "project_id": str(project.id),
            "score_type": "staff",
            "key": "C Major",
        }

        with self.assertRaises(Exception):
            _call_with_known_kwargs(entrypoint, call_pool)

        self.assertEqual(db.commit_count, 0, "missing required audio should fail before persisting fallback score data")

    def test_generation_rejects_fallback_analysis_result(self) -> None:
        entrypoint, module_name = self._load_generation_entrypoint()
        module = importlib.import_module(module_name)
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=user.id,
            audio_path="/tmp/project-input.wav",
            status="processing",
            progress=5,
        )
        db = _FakeSession([project, None, None])
        analysis_result = _fallback_analysis_result(str(project.id))

        call_pool = {
            "db": db,
            "session": db,
            "user": user,
            "current_user": user,
            "project": project,
            "project_id": str(project.id),
            "score_type": "staff",
            "key": "C Major",
            "analysis_result": analysis_result,
            "score_ir": analysis_result.score_ir,
            "score_data": analysis_result.score_data,
        }

        if "analysis_result" in inspect.signature(entrypoint).parameters:
            with self.assertRaises(Exception):
                _call_with_known_kwargs(entrypoint, call_pool)
            return

        if hasattr(module, "_run_audio_analysis"):
            with patch.object(module, "_run_audio_analysis", return_value=analysis_result):
                with self.assertRaises(Exception):
                    _call_with_known_kwargs(entrypoint, call_pool)
            return

        self.fail(
            "generation contract must either accept analysis_result directly or expose an internal analysis hook "
            "that can be validated against fallback outputs"
        )


if __name__ == "__main__":
    unittest.main()
