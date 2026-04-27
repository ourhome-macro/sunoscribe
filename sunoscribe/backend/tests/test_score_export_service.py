from __future__ import annotations

import importlib
import inspect
import unittest
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
    raise AssertionError("No revision export entrypoint found. Tried:\n" + "\n".join(errors))


class TestScoreExportServiceContracts(unittest.TestCase):
    def _load_export_entrypoint(self) -> Any:
        return _load_first_attr(
            ("app.services.score_revision_service", "export_score_revision"),
            ("app.services.score_export_service", "export_score_revision"),
            ("app.services.score_service", "export_score_revision"),
        )

    def test_export_entrypoint_is_revision_scoped(self) -> None:
        export_entrypoint = self._load_export_entrypoint()
        params = set(inspect.signature(export_entrypoint).parameters)
        self.assertTrue(
            {"score_revision_id", "revision_id"} & params,
            "revision-scoped export must identify the exact ScoreRevision to export",
        )

    def test_export_entrypoint_keeps_format_selection_but_not_score_level_ambiguity(self) -> None:
        export_entrypoint = self._load_export_entrypoint()
        params = set(inspect.signature(export_entrypoint).parameters)
        self.assertTrue({"export_format", "format", "artifact_type"} & params)
        self.assertFalse(
            "score_id" in params and not ({"score_revision_id", "revision_id"} & params),
            "export should not be scoped only by Score/Project once multiple revisions exist",
        )

    def test_export_entrypoint_contract_exposes_user_access_check(self) -> None:
        export_entrypoint = self._load_export_entrypoint()
        params = set(inspect.signature(export_entrypoint).parameters)
        self.assertTrue({"db", "session"} & params, "export should resolve revisions through persisted lineage")
        self.assertTrue({"user", "current_user"} & params, "export should remain user access scoped")


if __name__ == "__main__":
    unittest.main()
