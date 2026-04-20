from __future__ import annotations

import unittest
from pathlib import Path

from app.services.workspace import ProjectWorkspace


class TestProjectWorkspaceSecurity(unittest.TestCase):
    def test_accepts_safe_project_id(self) -> None:
        ws = ProjectWorkspace(project_id="test_001", projects_root=Path("data/projects"))
        self.assertEqual(ws.project_dir, Path("data/projects") / "test_001")

    def test_rejects_unsafe_project_id(self) -> None:
        invalid_ids = ["", "..", "../escape", "a/b", "a\\b", "bad id", "中文"]
        for project_id in invalid_ids:
            with self.subTest(project_id=project_id):
                with self.assertRaises(ValueError):
                    ProjectWorkspace(project_id=project_id, projects_root=Path("data/projects"))


if __name__ == "__main__":
    unittest.main()
