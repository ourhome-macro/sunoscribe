from __future__ import annotations

from typing import List, Tuple

from ..score_ir.types import LyricsToken, ScoreIR, ScoreNote
from .types import AlignmentDraft, TokenNoteAlignment


class InitialLyricsAligner:
    """初始歌词-音符对齐器（baseline）。"""

    METHOD = "baseline_monotonic_v1"

    def align(self, score_ir: ScoreIR) -> AlignmentDraft:
        warnings: List[str] = []

        tokens = self._flatten_tokens(score_ir)
        assignable_notes, skipped_ornament_notes = self._collect_assignable_notes(score_ir)

        if not tokens:
            warnings.append("No lyrics tokens found in score_ir.")
        if not assignable_notes:
            warnings.append("No assignable non-raw notes found in score_ir.")

        alignments: List[TokenNoteAlignment] = []
        note_cursor = 0

        total_tokens = len(tokens)
        total_notes = len(assignable_notes)

        for token_idx, token in enumerate(tokens):
            if note_cursor >= total_notes:
                break

            remaining_tokens = total_tokens - token_idx
            remaining_notes = total_notes - note_cursor
            group_size = self._decide_group_size(remaining_notes, remaining_tokens)
            max_group_size = max(1, remaining_notes - (remaining_tokens - 1))
            group_size = min(group_size, max_group_size)

            note_group = assignable_notes[note_cursor : note_cursor + group_size]
            note_cursor += len(note_group)
            if not note_group:
                break

            melisma = len(note_group) > 1
            alignments.append(
                TokenNoteAlignment(
                    token_id=token.id,
                    note_ids=[note.id for note in note_group],
                    melisma=melisma,
                    confidence=self._estimate_alignment_confidence(token, note_group, melisma),
                )
            )

        aligned_token_ids = {item.token_id for item in alignments}
        aligned_note_ids = {nid for item in alignments for nid in item.note_ids}

        unassigned_token_ids = [token.id for token in tokens if token.id not in aligned_token_ids]
        unassigned_note_ids = [note.id for note in assignable_notes if note.id not in aligned_note_ids]
        unassigned_note_ids.extend(note.id for note in skipped_ornament_notes)

        if skipped_ornament_notes:
            warnings.append(
                f"Skipped {len(skipped_ornament_notes)} ornament candidate notes by baseline policy."
            )
        if unassigned_token_ids:
            warnings.append(f"Unassigned tokens: {len(unassigned_token_ids)}")
        if unassigned_note_ids:
            warnings.append(f"Unassigned notes: {len(unassigned_note_ids)}")

        draft_confidence = self._estimate_draft_confidence(
            alignments=alignments,
            total_tokens=total_tokens,
            total_assignable_notes=total_notes,
            unassigned_token_ids=unassigned_token_ids,
            unassigned_note_ids=unassigned_note_ids,
        )

        return AlignmentDraft(
            alignments=alignments,
            unassigned_note_ids=unassigned_note_ids,
            unassigned_token_ids=unassigned_token_ids,
            confidence=draft_confidence,
            method=self.METHOD,
            warnings=warnings,
        )

    def _flatten_tokens(self, score_ir: ScoreIR) -> List[LyricsToken]:
        tokens: List[LyricsToken] = []
        for segment in score_ir.lyrics_segments:
            if not segment.tokens:
                continue
            sorted_tokens = sorted(segment.tokens, key=lambda t: (t.index_in_segment, t.id))
            tokens.extend(sorted_tokens)
        return tokens

    def _collect_assignable_notes(self, score_ir: ScoreIR) -> Tuple[List[ScoreNote], List[ScoreNote]]:
        all_non_raw_notes = [note for note in score_ir.notes if not note.is_raw]
        all_non_raw_notes.sort(key=lambda n: (n.start_time, n.end_time, n.id))

        assignable: List[ScoreNote] = []
        skipped_ornaments: List[ScoreNote] = []
        for note in all_non_raw_notes:
            if note.is_candidate_ornament:
                skipped_ornaments.append(note)
            else:
                assignable.append(note)

        return assignable, skipped_ornaments

    def _decide_group_size(self, remaining_notes: int, remaining_tokens: int) -> int:
        if remaining_notes <= remaining_tokens:
            return 1

        excess = remaining_notes - remaining_tokens
        # 保守策略：只有“明显更多”时才做 melisma 合并。
        if excess >= 4:
            return 3
        if excess >= 2:
            return 2
        return 1

    def _estimate_alignment_confidence(
        self,
        token: LyricsToken,
        notes: List[ScoreNote],
        melisma: bool,
    ) -> float:
        if not notes:
            return 0.6

        avg_note_conf = sum(max(0.0, min(1.0, n.confidence)) for n in notes) / len(notes)
        base = 0.84 if not melisma else 0.74

        if token.lang == "zh":
            base += 0.01
        elif token.lang == "en":
            base += 0.0
        else:
            base -= 0.02

        score = (base * 0.7) + (avg_note_conf * 0.3)
        return max(0.6, min(0.9, round(score, 4)))

    def _estimate_draft_confidence(
        self,
        alignments: List[TokenNoteAlignment],
        total_tokens: int,
        total_assignable_notes: int,
        unassigned_token_ids: List[str],
        unassigned_note_ids: List[str],
    ) -> float:
        if not alignments:
            return 0.0

        avg_alignment_conf = sum(item.confidence for item in alignments) / len(alignments)

        token_cov = 1.0
        if total_tokens > 0:
            token_cov = 1.0 - (len(unassigned_token_ids) / total_tokens)

        note_cov = 1.0
        if total_assignable_notes > 0:
            effective_unassigned_notes = max(
                0,
                len(unassigned_note_ids),
            )
            note_cov = 1.0 - (effective_unassigned_notes / total_assignable_notes)

        score = (avg_alignment_conf * 0.5) + (token_cov * 0.35) + (note_cov * 0.15)
        return max(0.0, min(1.0, round(score, 4)))
