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
    raise AssertionError("No PatchValidator contract found. Tried:\n" + "\n".join(errors))


def _op(name: str, **fields: Any) -> dict[str, Any]:
    return {"op": name, "type": name, **fields}


def _sample_score_ir() -> dict[str, Any]:
    return {
        "notes": [
            {"id": "n1", "pitch_midi": 60, "measure_id": "m1", "offset_beats": 0.0, "duration_beats": 1.0},
            {"id": "n2", "pitch_midi": 62, "measure_id": "m1", "offset_beats": 1.0, "duration_beats": 1.0},
            {"id": "n3", "pitch_midi": 64, "measure_id": "m2", "offset_beats": 0.0, "duration_beats": 1.0},
        ],
        "measures": [
            {"id": "m1", "number": 1, "duration_beats": 4.0},
            {"id": "m2", "number": 2, "duration_beats": 4.0},
        ],
        "lyrics_tokens": [
            {"id": "t1", "text": "hel"},
            {"id": "t2", "text": "lo"},
        ],
    }


def _make_revision_payload() -> dict[str, Any]:
    return {
        "id": "rev-machine-001",
        "revision_kind": "machine",
        "score_ir": _sample_score_ir(),
    }


def _call_validator(validator_or_fn: Any, revision_payload: dict[str, Any], patch_payload: dict[str, Any]) -> Any:
    if inspect.isclass(validator_or_fn):
        validator = validator_or_fn()
        for method_name in ("validate_score_patch", "validate_patch", "validate"):
            if hasattr(validator, method_name):
                method = getattr(validator, method_name)
                break
        else:
            raise AssertionError(f"{validator_or_fn.__name__} is missing a validate method")
    else:
        method = validator_or_fn

    params = set(inspect.signature(method).parameters)
    if "score_ir" in params:
        return method(score_ir=revision_payload["score_ir"], patch=patch_payload)
    if "revision" in params:
        return method(revision=revision_payload, patch=patch_payload)
    if "score_revision" in params:
        return method(score_revision=revision_payload, patch=patch_payload)
    return method(revision_payload, patch_payload)


def _extract_validation_state(result: Any) -> tuple[bool, list[str]]:
    if result is None:
        return True, []
    if isinstance(result, bool):
        return result, []
    if isinstance(result, dict):
        accepted = result.get("accepted", result.get("valid", result.get("is_valid", True)))
        errors = result.get("errors") or result.get("messages") or []
        return bool(accepted), [str(item) for item in errors]
    for flag_name in ("accepted", "valid", "is_valid"):
        if hasattr(result, flag_name):
            accepted = bool(getattr(result, flag_name))
            errors = getattr(result, "errors", getattr(result, "messages", [])) or []
            return accepted, [str(item) for item in errors]
    return True, []


class TestPatchValidatorContract(unittest.TestCase):
    def _load_validator(self) -> Any:
        return _load_first_attr(
            ("app.services.patch_validator", "PatchValidator"),
            ("app.services.patch_validator", "validate_score_patch"),
            ("app.services.score_revision_service", "PatchValidator"),
            ("app.services.score_revision_service", "validate_score_patch"),
        )

    def test_validator_accepts_valid_pitch_replacement(self) -> None:
        validator = self._load_validator()
        result = _call_validator(
            validator,
            _make_revision_payload(),
            {"operations": [_op("replace_note_pitch", note_id="n1", pitch_midi=61)]},
        )
        accepted, errors = _extract_validation_state(result)
        self.assertTrue(accepted, f"valid patch should be accepted, got errors: {errors}")

    def test_validator_rejects_unknown_note_id(self) -> None:
        validator = self._load_validator()
        patch_payload = {"operations": [_op("replace_note_pitch", note_id="missing", pitch_midi=61)]}
        try:
            result = _call_validator(validator, _make_revision_payload(), patch_payload)
        except Exception:
            return
        accepted, errors = _extract_validation_state(result)
        self.assertFalse(accepted, "unknown note id must be rejected")
        self.assertTrue(errors)

    def test_validator_rejects_out_of_range_pitch(self) -> None:
        validator = self._load_validator()
        patch_payload = {"operations": [_op("replace_note_pitch", note_id="n1", pitch_midi=200)]}
        try:
            result = _call_validator(validator, _make_revision_payload(), patch_payload)
        except Exception:
            return
        accepted, _errors = _extract_validation_state(result)
        self.assertFalse(accepted, "pitch outside MIDI range must be rejected")

    def test_validator_rejects_negative_duration(self) -> None:
        validator = self._load_validator()
        patch_payload = {"operations": [_op("adjust_note_duration", note_id="n1", duration_beats=-0.5)]}
        try:
            result = _call_validator(validator, _make_revision_payload(), patch_payload)
        except Exception:
            return
        accepted, _errors = _extract_validation_state(result)
        self.assertFalse(accepted, "negative duration must be rejected")

    def test_validator_rejects_cross_measure_merge(self) -> None:
        validator = self._load_validator()
        patch_payload = {"operations": [_op("merge_notes", note_ids=["n2", "n3"])]}
        try:
            result = _call_validator(validator, _make_revision_payload(), patch_payload)
        except Exception:
            return
        accepted, _errors = _extract_validation_state(result)
        self.assertFalse(accepted, "merge across measures must be rejected")

    def test_validator_rejects_unknown_lyric_token_reference(self) -> None:
        validator = self._load_validator()
        patch_payload = {"operations": [_op("bind_lyric_token", note_id="n1", lyric_token_id="missing-token")]}
        try:
            result = _call_validator(validator, _make_revision_payload(), patch_payload)
        except Exception:
            return
        accepted, _errors = _extract_validation_state(result)
        self.assertFalse(accepted, "unknown lyric token reference must be rejected")


if __name__ == "__main__":
    unittest.main()
