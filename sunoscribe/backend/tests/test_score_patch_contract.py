from __future__ import annotations

import importlib
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
    raise AssertionError("No ScorePatch schema found. Tried:\n" + "\n".join(errors))


def _validate_model(model_cls: Any, payload: dict[str, Any]) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls(**payload)


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _field_names(model_cls: Any) -> set[str]:
    if hasattr(model_cls, "model_fields"):
        return set(model_cls.model_fields)
    if hasattr(model_cls, "__fields__"):
        return set(model_cls.__fields__)
    return set(getattr(model_cls, "__annotations__", {}))


def _op(name: str, **fields: Any) -> dict[str, Any]:
    return {"op": name, "type": name, **fields}


class TestScorePatchContract(unittest.TestCase):
    def _load_schema(self) -> Any:
        return _load_first_attr(
            ("app.schemas.score_patch", "ScorePatch"),
            ("app.schemas.patch", "ScorePatch"),
            ("app.schemas.score_revision", "ScorePatch"),
        )

    def test_schema_declares_operations_field(self) -> None:
        schema = self._load_schema()
        self.assertIn("operations", _field_names(schema))

    def test_schema_accepts_small_auditable_operations(self) -> None:
        schema = self._load_schema()
        payload = {
            "operations": [
                _op("replace_note_pitch", note_id="n1", pitch_midi=62),
                _op("adjust_note_duration", note_id="n1", duration_beats=0.5),
                _op("delete_note", note_id="n2"),
                _op("merge_notes", note_ids=["n3", "n4"]),
                _op("bind_lyric_token", note_id="n1", lyric_token_id="t1"),
            ]
        }

        model = _validate_model(schema, payload)
        dumped = _dump_model(model)
        self.assertEqual(len(dumped["operations"]), 5)
        self.assertNotIn("score_ir", dumped)
        self.assertNotIn("measures", dumped)

    def test_schema_rejects_empty_operations(self) -> None:
        schema = self._load_schema()
        with self.assertRaises(Exception):
            _validate_model(schema, {"operations": []})

    def test_schema_rejects_unknown_operation_type(self) -> None:
        schema = self._load_schema()
        with self.assertRaises(Exception):
            _validate_model(schema, {"operations": [_op("rewrite_full_score", score_ir={"notes": []})]})

    def test_schema_rejects_root_level_full_score_replacement_payload(self) -> None:
        schema = self._load_schema()
        with self.assertRaises(Exception):
            _validate_model(
                schema,
                {
                    "operations": [_op("delete_note", note_id="n1")],
                    "score_ir": {"notes": [{"id": "n1"}]},
                },
            )


if __name__ == "__main__":
    unittest.main()
