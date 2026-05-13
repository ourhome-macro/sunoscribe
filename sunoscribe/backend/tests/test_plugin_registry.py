from __future__ import annotations

import unittest

from app.services.plugins import CallablePlugin, PluginContext, PluginRegistry, PluginResult
from app.utils.errors import ValidationAppError


class TestPluginRegistry(unittest.TestCase):
    def test_registry_runs_registered_builtin_plugin(self) -> None:
        registry = PluginRegistry()
        registry.register(
            CallablePlugin(
                name="diagnosis",
                kind="diagnosis",
                handler=lambda context: {"warnings": list(context.warnings)},
            )
        )

        result = registry.run("diagnosis", PluginContext(warnings=("missing_f0",)))

        self.assertIsInstance(result, PluginResult)
        self.assertEqual(result.plugin_name, "diagnosis")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.payload, {"warnings": ["missing_f0"]})
        self.assertEqual(result.warnings, ("missing_f0",))

    def test_registry_rejects_unknown_plugin(self) -> None:
        registry = PluginRegistry()

        with self.assertRaisesRegex(ValidationAppError, "plugin is not registered"):
            registry.run("unknown", PluginContext())

    def test_registry_rejects_duplicate_plugin_names(self) -> None:
        registry = PluginRegistry([
            CallablePlugin(name="rvc-prepare", kind="rvc", handler=lambda _context: None),
        ])

        with self.assertRaisesRegex(ValidationAppError, "already registered"):
            registry.register(CallablePlugin(name="rvc_prepare", kind="rvc", handler=lambda _context: None))


if __name__ == "__main__":
    unittest.main()
