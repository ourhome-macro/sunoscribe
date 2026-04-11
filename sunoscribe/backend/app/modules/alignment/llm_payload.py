from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..score_ir.types import LyricsToken, ScoreIR, ScoreNote
from .types import AlignmentDraft


class AlignmentLLMPayloadBuilder:
    """Build compact, stable payload for LLM alignment refinement."""

    def build(
        self,
        score_ir: ScoreIR,
        draft: AlignmentDraft,
        warnings: list[str] | None = None,
    ) -> dict:
        payload: Dict[str, Any] = {
            "task": "lyrics_note_alignment_refine",
            "meta": self._build_meta(score_ir),
            "notes": self._build_notes(score_ir),
            "tokens": self._build_tokens(score_ir),
            "segments": self._build_segments(score_ir),
            "draft_alignment": self._build_draft(draft),
            "issues": self._build_issues(score_ir),
            "warnings": self._build_warnings(draft, warnings),
            "instructions": self._build_instructions(),
        }
        return payload

    def _build_meta(self, score_ir: ScoreIR) -> Dict[str, Any]:
        meta = score_ir.meta
        return {
            "bpm": meta.bpm,
            "key": meta.key,
            "time_signature": meta.time_signature,
            "total_measures": meta.total_measures,
            "has_anacrusis": meta.has_anacrusis,
        }

    def _build_notes(self, score_ir: ScoreIR) -> List[Dict[str, Any]]:
        notes: List[ScoreNote] = sorted(
            score_ir.notes,
            key=lambda n: (n.start_time, n.end_time, n.id),
        )
        result: List[Dict[str, Any]] = []
        for note in notes:
            result.append(
                {
                    "id": note.id,
                    "pitch": note.pitch,
                    "start_time": note.start_time,
                    "end_time": note.end_time,
                    "duration_beats": note.duration_beats,
                    "measure_num": note.measure_num,
                    "beat_position": note.beat_position,
                    "lyric": note.lyric,
                    "is_candidate_ornament": note.is_candidate_ornament,
                    "tie_candidate": note.tie_candidate,
                }
            )
        return result

    def _build_tokens(self, score_ir: ScoreIR) -> List[Dict[str, Any]]:
        flat_tokens: List[LyricsToken] = []
        for seg in score_ir.lyrics_segments:
            ordered_tokens = sorted(seg.tokens, key=lambda t: (t.index_in_segment, t.id))
            flat_tokens.extend(ordered_tokens)

        return [
            {
                "id": token.id,
                "text": token.text,
                "segment_id": token.segment_id,
                "index_in_segment": token.index_in_segment,
                "lang": token.lang,
            }
            for token in flat_tokens
        ]

    def _build_segments(self, score_ir: ScoreIR) -> List[Dict[str, Any]]:
        return [
            {
                "id": seg.id,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
            }
            for seg in score_ir.lyrics_segments
        ]

    def _build_draft(self, draft: AlignmentDraft) -> Dict[str, Any]:
        return {
            "alignments": [
                {
                    "token_id": item.token_id,
                    "note_ids": list(item.note_ids),
                    "melisma": item.melisma,
                    "confidence": item.confidence,
                }
                for item in draft.alignments
            ],
            "unassigned_note_ids": list(draft.unassigned_note_ids),
            "unassigned_token_ids": list(draft.unassigned_token_ids),
            "confidence": draft.confidence,
            "method": draft.method,
        }

    def _build_issues(self, score_ir: ScoreIR) -> List[Dict[str, Any]]:
        return [
            {
                "type": issue.type,
                "severity": issue.severity,
                "measure_num": issue.measure_num,
                "note_ids": list(issue.note_ids),
                "segment_ids": list(issue.segment_ids),
                "message": issue.message,
            }
            for issue in score_ir.issue_spots
        ]

    def _build_warnings(self, draft: AlignmentDraft, extra_warnings: Optional[List[str]]) -> List[str]:
        merged: List[str] = []
        for item in list(draft.warnings) + list(extra_warnings or []):
            text = str(item).strip()
            if not text:
                continue
            if text not in merged:
                merged.append(text)
        return merged

    def _build_instructions(self) -> List[str]:
        return [
            "Keep token order unchanged.",
            "Try to cover all lyric tokens whenever possible.",
            "Ornament notes can be ignored or merged into adjacent main notes.",
            "Set melisma=true when multiple notes map to one token.",
            "Do not create token_id or note_id that does not exist in input.",
            "Output must be a JSON object.",
        ]
