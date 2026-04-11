from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..score_ir.types import ScoreIR
from .types import AlignmentDraft, TokenNoteAlignment


class AlignmentValidator:
    """校验 AlignmentDraft 的结构、引用与顺序一致性。"""

    def validate(self, score_ir: ScoreIR, draft: AlignmentDraft) -> List[str]:
        warnings: List[str] = []

        token_order, valid_token_ids = self._build_token_order(score_ir)
        note_order, valid_note_ids, ornament_note_ids = self._build_note_order(score_ir)

        used_token_ids: Set[str] = set()
        used_note_ids: Set[str] = set()
        last_token_order = -1
        last_note_order = -1

        for idx, alignment in enumerate(draft.alignments):
            entry_warnings, last_token_order, last_note_order = self._validate_alignment_entry(
                alignment=alignment,
                idx=idx,
                valid_token_ids=valid_token_ids,
                valid_note_ids=valid_note_ids,
                token_order=token_order,
                note_order=note_order,
                used_token_ids=used_token_ids,
                used_note_ids=used_note_ids,
                last_token_order=last_token_order,
                last_note_order=last_note_order,
                ornament_note_ids=ornament_note_ids,
            )
            warnings.extend(entry_warnings)

        warnings.extend(
            self._validate_unassigned_ids(
                draft=draft,
                valid_note_ids=valid_note_ids,
                valid_token_ids=valid_token_ids,
            )
        )

        return warnings

    def _build_token_order(self, score_ir: ScoreIR) -> Tuple[Dict[str, int], Set[str]]:
        ordered_token_ids: List[str] = []
        for segment in score_ir.lyrics_segments:
            for token in sorted(segment.tokens, key=lambda t: (t.index_in_segment, t.id)):
                ordered_token_ids.append(token.id)

        token_order = {token_id: idx for idx, token_id in enumerate(ordered_token_ids)}
        return token_order, set(ordered_token_ids)

    def _build_note_order(self, score_ir: ScoreIR) -> Tuple[Dict[str, int], Set[str], Set[str]]:
        ordered_notes = sorted(score_ir.notes, key=lambda n: (n.start_time, n.end_time, n.id))
        note_order = {note.id: idx for idx, note in enumerate(ordered_notes)}
        valid_note_ids = {note.id for note in ordered_notes}
        ornament_note_ids = {note.id for note in ordered_notes if note.is_candidate_ornament}
        return note_order, valid_note_ids, ornament_note_ids

    def _validate_alignment_entry(
        self,
        alignment: TokenNoteAlignment,
        idx: int,
        valid_token_ids: Set[str],
        valid_note_ids: Set[str],
        token_order: Dict[str, int],
        note_order: Dict[str, int],
        used_token_ids: Set[str],
        used_note_ids: Set[str],
        last_token_order: int,
        last_note_order: int,
        ornament_note_ids: Set[str],
    ) -> Tuple[List[str], int, int]:
        warnings: List[str] = []

        token_id = alignment.token_id
        note_ids = alignment.note_ids or []

        if token_id in used_token_ids:
            warnings.append(f"duplicate token_id in alignments: {token_id}")
        else:
            used_token_ids.add(token_id)

        if token_id not in valid_token_ids:
            warnings.append(f"unknown token_id: {token_id}")
            current_token_order = last_token_order
        else:
            current_token_order = token_order[token_id]
            if current_token_order < last_token_order:
                warnings.append(f"token order rollback at alignment index {idx}: {token_id}")
            last_token_order = max(last_token_order, current_token_order)

        if not note_ids:
            warnings.append(f"empty note_ids for token_id: {token_id}")

        if alignment.melisma and len(note_ids) < 2:
            warnings.append(f"melisma true but note_ids<2 for token_id: {token_id}")
        if (not alignment.melisma) and len(note_ids) > 1:
            warnings.append(f"melisma false but note_ids>1 for token_id: {token_id}")

        local_orders: List[int] = []
        for note_id in note_ids:
            if note_id not in valid_note_ids:
                warnings.append(f"unknown note_id: {note_id}")
                continue

            if note_id in used_note_ids:
                warnings.append(f"duplicate note_id in alignments: {note_id}")
            else:
                used_note_ids.add(note_id)

            if note_id in ornament_note_ids:
                warnings.append(f"assigned ornament note: {note_id}")

            local_orders.append(note_order[note_id])

        if local_orders:
            if not self._is_non_decreasing(local_orders):
                warnings.append(f"note order rollback inside alignment for token_id: {token_id}")

            first_order = local_orders[0]
            if first_order < last_note_order:
                warnings.append(f"note timeline rollback at token_id: {token_id}")

            last_note_order = max(last_note_order, local_orders[-1])

        return warnings, last_token_order, last_note_order

    def _validate_unassigned_ids(
        self,
        draft: AlignmentDraft,
        valid_note_ids: Set[str],
        valid_token_ids: Set[str],
    ) -> List[str]:
        warnings: List[str] = []

        for note_id in draft.unassigned_note_ids:
            if note_id not in valid_note_ids:
                warnings.append(f"unknown unassigned_note_id: {note_id}")

        for token_id in draft.unassigned_token_ids:
            if token_id not in valid_token_ids:
                warnings.append(f"unknown unassigned_token_id: {token_id}")

        return warnings

    def _is_non_decreasing(self, values: List[int]) -> bool:
        if not values:
            return True
        previous = values[0]
        for current in values[1:]:
            if current < previous:
                return False
            previous = current
        return True
