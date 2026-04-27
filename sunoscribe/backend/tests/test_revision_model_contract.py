from __future__ import annotations

import importlib
import unittest
import uuid
from typing import Any


def _load_first_attr(*candidates: tuple[str, str]) -> Any:
    errors: list[str] = []
    for module_name, attr_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
            continue
        if hasattr(module, attr_name):
            return getattr(module, attr_name)
        errors.append(f"{module_name}: missing {attr_name}")
    raise AssertionError("Required revision/artifact model is missing. Tried:\n" + "\n".join(errors))


def _column_names(model_cls: Any) -> set[str]:
    table = getattr(model_cls, "__table__", None)
    if table is not None:
        return {str(column.name) for column in table.columns}
    return set(getattr(model_cls, "__annotations__", {}))


def _pick_name(names: set[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in names:
            return candidate
    return None


class TestRevisionModelContracts(unittest.TestCase):
    def _load_score_revision(self) -> Any:
        return _load_first_attr(
            ("app.models.score_revision", "ScoreRevision"),
            ("app.models.revision", "ScoreRevision"),
        )

    def _load_artifact(self) -> Any:
        return _load_first_attr(
            ("app.models.artifact", "Artifact"),
            ("app.models.score_revision", "Artifact"),
        )

    def test_score_revision_model_supports_multiple_revisions_per_project(self) -> None:
        score_revision = self._load_score_revision()
        project_column = getattr(getattr(score_revision, "__table__", None), "columns", {}).get("project_id")
        self.assertIsNotNone(project_column, "ScoreRevision must keep project lineage")
        self.assertFalse(bool(getattr(project_column, "unique", False)), "project_id must not be unique on revisions")

    def test_score_revision_model_has_parent_and_revision_kind_fields(self) -> None:
        score_revision = self._load_score_revision()
        columns = _column_names(score_revision)
        self.assertIsNotNone(
            _pick_name(columns, "parent_revision_id", "base_revision_id", "source_revision_id"),
            "ScoreRevision must record lineage to a prior revision when applicable",
        )
        self.assertIsNotNone(
            _pick_name(columns, "revision_kind", "revision_type", "author_type", "source_type", "created_by_type"),
            "ScoreRevision must distinguish machine and user revisions",
        )

    def test_artifact_model_is_revision_scoped(self) -> None:
        artifact = self._load_artifact()
        columns = _column_names(artifact)
        self.assertIsNotNone(
            _pick_name(columns, "score_revision_id", "revision_id"),
            "Artifact must point to the ScoreRevision it was produced from",
        )
        self.assertIsNotNone(
            _pick_name(columns, "artifact_type", "kind", "type"),
            "Artifact must record what kind of export/debug asset it stores",
        )
        self.assertIsNotNone(
            _pick_name(columns, "path", "storage_path", "object_path", "uri"),
            "Artifact must keep a stable storage locator",
        )

    def test_machine_and_user_revisions_can_be_represented_separately(self) -> None:
        score_revision = self._load_score_revision()
        columns = _column_names(score_revision)
        kind_field = _pick_name(columns, "revision_kind", "revision_type", "author_type", "source_type", "created_by_type")
        parent_field = _pick_name(columns, "parent_revision_id", "base_revision_id", "source_revision_id")
        payload_field = _pick_name(columns, "score_ir", "score_data", "revision_data")

        self.assertIsNotNone(kind_field)
        self.assertIsNotNone(parent_field)
        self.assertIsNotNone(payload_field)

        machine = score_revision(
            project_id=uuid.uuid4(),
            **{
                kind_field: "machine",
                payload_field: {"notes": [{"id": "n1", "pitch_midi": 60}]},
            },
        )
        user = score_revision(
            project_id=uuid.uuid4(),
            **{
                kind_field: "user",
                parent_field: uuid.uuid4(),
                payload_field: {"notes": [{"id": "n1", "pitch_midi": 62}]},
            },
        )

        self.assertEqual(getattr(machine, kind_field), "machine")
        self.assertEqual(getattr(user, kind_field), "user")
        self.assertIsNotNone(getattr(user, parent_field))


if __name__ == "__main__":
    unittest.main()
