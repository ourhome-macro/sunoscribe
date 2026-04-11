from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .llm_schema import LLMAlignmentItem, LLMAlignmentResult


class AlignmentLLMParser:
    _FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)

    def parse(self, raw: str | dict) -> LLMAlignmentResult:
        data = self._parse_raw_to_dict(raw)
        return self._to_result(data)

    def _parse_raw_to_dict(self, raw: str | dict) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            raise ValueError("Invalid LLM response: expected str or dict")

        text = raw.strip()
        if not text:
            raise ValueError("Invalid LLM response: empty content")

        stripped = self._strip_code_fence(text)

        data = self._try_json_loads(stripped)
        if isinstance(data, dict):
            return data

        extracted = self._extract_outer_object(stripped)
        if extracted is not None:
            data = self._try_json_loads(extracted)
            if isinstance(data, dict):
                return data

        raise ValueError("Invalid LLM response: JSON object not found")

    def _strip_code_fence(self, text: str) -> str:
        match = self._FENCE_PATTERN.match(text)
        if match:
            return match.group(1).strip()
        return text

    def _extract_outer_object(self, text: str) -> str | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1].strip()

    def _try_json_loads(self, text: str) -> Any:
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _to_result(self, data: Dict[str, Any]) -> LLMAlignmentResult:
        raw_alignments = data.get("alignments", [])
        alignments = self._parse_alignments(raw_alignments)

        result = LLMAlignmentResult(
            alignments=alignments,
            unassigned_note_ids=self._as_str_list(data.get("unassigned_note_ids", [])),
            unassigned_token_ids=self._as_str_list(data.get("unassigned_token_ids", [])),
            confidence=self._as_optional_float(data.get("confidence")),
            warnings=self._as_optional_str_list(data.get("warnings")),
            reasoning=self._as_optional_str(data.get("reasoning")),
        )
        return result

    def _parse_alignments(self, raw_alignments: Any) -> List[LLMAlignmentItem]:
        if not isinstance(raw_alignments, list):
            return []

        items: List[LLMAlignmentItem] = []
        for item in raw_alignments:
            if not isinstance(item, dict):
                continue

            token_id = self._as_str(item.get("token_id", "")).strip()
            if not token_id:
                continue

            note_ids = self._normalize_note_ids(item.get("note_ids", []))
            melisma = self._as_bool(item.get("melisma", False))
            confidence = self._as_optional_float(item.get("confidence"))

            items.append(
                LLMAlignmentItem(
                    token_id=token_id,
                    note_ids=note_ids,
                    melisma=melisma,
                    confidence=confidence,
                )
            )

        return items

    def _normalize_note_ids(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [self._as_str(v).strip() for v in value if self._as_str(v).strip()]

        single = self._as_str(value).strip()
        if not single:
            return []
        return [single]

    def _as_str_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        result: List[str] = []
        for item in value:
            text = self._as_str(item).strip()
            if text:
                result.append(text)
        return result

    def _as_optional_str_list(self, value: Any) -> List[str] | None:
        if value is None:
            return None
        return self._as_str_list(value)

    def _as_optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _as_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = self._as_str(value).strip()
        return text or None

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
            return False
        return bool(value)

    def _as_str(self, value: Any) -> str:
        return "" if value is None else str(value)
