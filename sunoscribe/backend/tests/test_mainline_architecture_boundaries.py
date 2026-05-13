from __future__ import annotations

import ast
from pathlib import Path
import unittest


class TestMainlineArchitectureBoundaries(unittest.TestCase):
    def test_trunk_services_do_not_import_plugin_agent_or_rvc_layers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        trunk_files = [
            root / "app" / "services" / "media_ingest_service.py",
            root / "app" / "services" / "stem_service.py",
            root / "app" / "services" / "melody_transcription_service.py",
            root / "app" / "services" / "rhythm_quantization_service.py",
            root / "app" / "services" / "score_build_service.py",
            root / "app" / "services" / "render_export_service.py",
        ]
        forbidden_prefixes = (
            "app.services.plugins",
            "app.services.agent_workflow_service",
            "app.modules.agents",
        )
        forbidden_fragments = ("rvc", "diagnosis")

        violations: list[str] = []
        for path in trunk_files:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                        if module.startswith(forbidden_prefixes) or any(fragment in module.lower() for fragment in forbidden_fragments):
                            violations.append(f"{path.name}:{node.lineno}:{module}")
                    continue
                if module and (
                    module.startswith(forbidden_prefixes)
                    or any(fragment in module.lower() for fragment in forbidden_fragments)
                ):
                    violations.append(f"{path.name}:{node.lineno}:{module}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
