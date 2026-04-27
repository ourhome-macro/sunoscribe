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
    raise AssertionError("Missing revision workflow entrypoint. Tried:\n" + "\n".join(errors))


class TestRevisionFlowIntegrationContracts(unittest.TestCase):
    def test_revision_flow_exposes_machine_create_patch_apply_and_export_steps(self) -> None:
        create_machine = _load_first_attr(
            ("app.services.score_revision_service", "create_machine_score_revision"),
            ("app.services.score_revision_service", "create_machine_revision"),
        )
        apply_patch = _load_first_attr(
            ("app.services.score_revision_service", "apply_score_patch"),
            ("app.services.score_patch_service", "apply_score_patch"),
        )
        export_revision = _load_first_attr(
            ("app.services.score_revision_service", "export_score_revision"),
            ("app.services.score_export_service", "export_score_revision"),
        )

        self.assertTrue(callable(create_machine))
        self.assertTrue(callable(apply_patch))
        self.assertTrue(callable(export_revision))

    def test_patch_application_and_export_are_both_revision_based(self) -> None:
        apply_patch = _load_first_attr(
            ("app.services.score_revision_service", "apply_score_patch"),
            ("app.services.score_patch_service", "apply_score_patch"),
        )
        export_revision = _load_first_attr(
            ("app.services.score_revision_service", "export_score_revision"),
            ("app.services.score_export_service", "export_score_revision"),
        )

        patch_params = set(inspect.signature(apply_patch).parameters)
        export_params = set(inspect.signature(export_revision).parameters)

        self.assertTrue({"score_revision_id", "revision_id", "base_revision_id"} & patch_params)
        self.assertTrue({"score_revision_id", "revision_id"} & export_params)

    def test_machine_creation_and_user_patch_paths_are_separate(self) -> None:
        create_machine = _load_first_attr(
            ("app.services.score_revision_service", "create_machine_score_revision"),
            ("app.services.score_revision_service", "create_machine_revision"),
        )
        apply_patch = _load_first_attr(
            ("app.services.score_revision_service", "apply_score_patch"),
            ("app.services.score_patch_service", "apply_score_patch"),
        )

        create_params = set(inspect.signature(create_machine).parameters)
        patch_params = set(inspect.signature(apply_patch).parameters)

        self.assertTrue({"analysis_result", "score_ir", "score_data", "project_id"} & create_params)
        self.assertFalse(
            {"analysis_result", "score_ir", "score_data"} & patch_params,
            "user patch application should consume a validated patch against an existing revision, not rebuild from raw analysis",
        )
        self.assertIn("patch", patch_params)


if __name__ == "__main__":
    unittest.main()
