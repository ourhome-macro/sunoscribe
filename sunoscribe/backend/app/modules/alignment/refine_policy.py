from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..score_ir.types import ScoreIR
from .types import AlignmentDraft


class AlignmentRefinePolicy:
    def should_accept(
        self,
        score_ir: ScoreIR,
        original_draft: AlignmentDraft,
        refined_draft: AlignmentDraft,
        warnings_before: list[str],
        warnings_after: list[str],
    ) -> tuple[bool, list[str]]:
        reasons: List[str] = []

        items = self._extract_alignment_items(refined_draft)
        if not items:
            reasons.append("empty_alignments")

        valid_token_ids, token_order = self._collect_valid_token_ids(score_ir)
        valid_note_ids, note_order = self._collect_valid_note_ids(score_ir)

        for token_id, _ in items:
            if token_id not in valid_token_ids:
                reasons.append(f"unknown_token_id:{token_id}")

        for _, note_ids in items:
            for note_id in note_ids:
                if note_id not in valid_note_ids:
                    reasons.append(f"unknown_note_id:{note_id}")

        duplicate_tokens = self._check_duplicate_tokens(items)
        reasons.extend([f"duplicate_token_id:{token_id}" for token_id in duplicate_tokens])

        duplicate_notes = self._check_duplicate_notes(items)
        reasons.extend([f"duplicate_note_id:{note_id}" for note_id in duplicate_notes])

        if not self._check_token_order(items, token_order):
            reasons.append("token_order_regression")

        if not self._check_note_order(items, note_order):
            reasons.append("note_order_regression")

        original_unassigned_tokens = len(getattr(original_draft, "unassigned_token_ids", []) or [])
        refined_unassigned_tokens = len(getattr(refined_draft, "unassigned_token_ids", []) or [])
        if refined_unassigned_tokens > original_unassigned_tokens + 2:
            reasons.append("too_many_unassigned_tokens")

        if len(warnings_after) > len(warnings_before) + 3:
            reasons.append("validator_warnings_increased")

        reasons = self._unique_keep_order(reasons)
        return len(reasons) == 0, reasons

    def _collect_valid_token_ids(self, score_ir: ScoreIR) -> Tuple[Set[str], Dict[str, int]]:
        ordered_tokens: List[str] = []
        for segment in getattr(score_ir, "lyrics_segments", []) or []:
            tokens = getattr(segment, "tokens", []) or []
            sorted_tokens = sorted(
                tokens,
                key=lambda t: (
                    self._safe_int(getattr(t, "index_in_segment", 0), 0),
                    str(getattr(t, "id", "")),
                ),
            )
            for token in sorted_tokens:
                token_id = str(getattr(token, "id", "")).strip()
                if token_id:
                    ordered_tokens.append(token_id)

        token_order = {token_id: idx for idx, token_id in enumerate(ordered_tokens)}
        return set(ordered_tokens), token_order

    def _collect_valid_note_ids(self, score_ir: ScoreIR) -> Tuple[Set[str], Dict[str, int]]:
        notes = sorted(
            getattr(score_ir, "notes", []) or [],
            key=lambda n: (
                self._safe_float(getattr(n, "start_time", 0.0), 0.0),
                self._safe_float(getattr(n, "end_time", 0.0), 0.0),
                str(getattr(n, "id", "")),
            ),
        )

        ordered_note_ids: List[str] = []
        for note in notes:
            note_id = str(getattr(note, "id", "")).strip()
            if note_id:
                ordered_note_ids.append(note_id)

        note_order = {note_id: idx for idx, note_id in enumerate(ordered_note_ids)}
        return set(ordered_note_ids), note_order

    def _extract_alignment_items(self, draft: AlignmentDraft) -> List[Tuple[str, List[str]]]:
        items: List[Tuple[str, List[str]]] = []
        for item in getattr(draft, "alignments", []) or []:
            token_id = str(getattr(item, "token_id", "")).strip()
            if not token_id:
                continue

            raw_note_ids = getattr(item, "note_ids", [])
            if isinstance(raw_note_ids, list):
                note_ids = [str(nid).strip() for nid in raw_note_ids if str(nid).strip()]
            elif raw_note_ids is None:
                note_ids = []
            else:
                one = str(raw_note_ids).strip()
                note_ids = [one] if one else []

            items.append((token_id, note_ids))

        return items

    def _check_duplicate_tokens(self, items: List[Tuple[str, List[str]]]) -> List[str]:
        seen: Set[str] = set()
        duplicates: List[str] = []
        for token_id, _ in items:
            if token_id in seen:
                duplicates.append(token_id)
            else:
                seen.add(token_id)
        return self._unique_keep_order(duplicates)

    def _check_duplicate_notes(self, items: List[Tuple[str, List[str]]]) -> List[str]:
        seen: Set[str] = set()
        duplicates: List[str] = []
        for _, note_ids in items:
            for note_id in note_ids:
                if note_id in seen:
                    duplicates.append(note_id)
                else:
                    seen.add(note_id)
        return self._unique_keep_order(duplicates)

    def _check_token_order(self, items: List[Tuple[str, List[str]]], token_order: Dict[str, int]) -> bool:
        if not token_order:
            return True

        last_idx = -1
        for token_id, _ in items:
            idx = token_order.get(token_id)
            if idx is None:
                continue
            if idx < last_idx:
                return False
            last_idx = idx
        return True

    def _check_note_order(self, items: List[Tuple[str, List[str]]], note_order: Dict[str, int]) -> bool:
        if not note_order:
            return True

        last_global = -1
        for _, note_ids in items:
            local_indices: List[int] = []
            for note_id in note_ids:
                idx = note_order.get(note_id)
                if idx is None:
                    continue
                local_indices.append(idx)

            if not local_indices:
                continue

            if not self._is_non_decreasing(local_indices):
                return False

            if local_indices[0] < last_global:
                return False

            last_global = max(last_global, local_indices[-1])

        return True

    def _is_non_decreasing(self, values: List[int]) -> bool:
        if not values:
            return True
        prev = values[0]
        for value in values[1:]:
            if value < prev:
                return False
            prev = value
        return True

    def _unique_keep_order(self, values: List[str]) -> List[str]:
        seen: Set[str] = set()
        output: List[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output

    def _safe_float(self, value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
