from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.modules.pitch.config import PitchDetectionConfig
from app.services.pitch_runtime import (
    build_pitch_detection_config_from_settings,
    build_pitch_runtime_health,
    parse_pitch_backend_fallbacks,
)


class TestPitchRuntimeHealth(unittest.TestCase):
    def test_parse_pitch_backend_fallbacks_normalizes_aliases(self) -> None:
        self.assertEqual(
            parse_pitch_backend_fallbacks("CREPE,basic_pitch,crepe,r-mvpe"),
            ("crepe", "basic-pitch", "rmvpe"),
        )
        self.assertEqual(parse_pitch_backend_fallbacks(""), ())

    def test_build_pitch_detection_config_from_settings_defaults_to_rmvpe(self) -> None:
        config = build_pitch_detection_config_from_settings()

        self.assertEqual(config.pitch_backend, "rmvpe")
        self.assertEqual(config.pitch_backend_fallbacks, ())
        self.assertEqual(config.pitch_profile, "production")
        self.assertFalse(config.allow_backend_fallbacks)

    def test_build_pitch_detection_config_allows_diagnostic_fallback_profile(self) -> None:
        from app.services import pitch_runtime

        original_profile = pitch_runtime.settings.pitch_profile
        original_allow = pitch_runtime.settings.pitch_allow_backend_fallbacks
        original_fallbacks = pitch_runtime.settings.pitch_backend_fallbacks
        try:
            pitch_runtime.settings.pitch_profile = "diagnostic"
            pitch_runtime.settings.pitch_allow_backend_fallbacks = False
            pitch_runtime.settings.pitch_backend_fallbacks = "crepe,basic-pitch"
            config = build_pitch_detection_config_from_settings()
        finally:
            pitch_runtime.settings.pitch_profile = original_profile
            pitch_runtime.settings.pitch_allow_backend_fallbacks = original_allow
            pitch_runtime.settings.pitch_backend_fallbacks = original_fallbacks

        self.assertEqual(config.pitch_backend_fallbacks, ("crepe", "basic-pitch"))
        self.assertEqual(config.pitch_profile, "diagnostic")
        self.assertTrue(config.allow_backend_fallbacks)

    def test_health_reports_missing_cache_and_rmvpe_model_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_cache = Path(temp_dir) / "missing" / "pitch-cache"
            missing_model = Path(temp_dir) / "missing-rmvpe.pt"
            config = PitchDetectionConfig(
                pitch_backend="rmvpe",
                pitch_backend_fallbacks=("crepe",),
                cache_dir=str(missing_cache),
                rmvpe_model_path=str(missing_model),
            )

            health = build_pitch_runtime_health(config=config)

        self.assertEqual(health["status"], "fail")
        self.assertEqual(health["pitch_backend"], "rmvpe")
        self.assertEqual(health["cache"]["status"], "missing")
        self.assertEqual(health["rmvpe"]["status"], "missing_model")
        self.assertFalse(health["rmvpe"]["model_exists"])


if __name__ == "__main__":
    unittest.main()
