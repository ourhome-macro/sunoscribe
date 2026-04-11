from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .types import AlignmentDraft, TokenNoteAlignment


@dataclass
class LLMAlignmentItem:
    token_id: str
    note_ids: List[str]
    melisma: bool = False
    confidence: float | None = None


@dataclass
class LLMAlignmentResult:
    alignments: List[LLMAlignmentItem] = field(default_factory=list)
    unassigned_note_ids: List[str] = field(default_factory=list)
    unassigned_token_ids: List[str] = field(default_factory=list)
    confidence: float | None = None
    warnings: List[str] | None = None
    reasoning: str | None = None

    def to_alignment_draft(self, method: str = "llm_refine") -> AlignmentDraft:
        return AlignmentDraft(
            alignments=[
                TokenNoteAlignment(
                    token_id=item.token_id,
                    note_ids=list(item.note_ids),
                    melisma=bool(item.melisma),
                    confidence=float(item.confidence) if item.confidence is not None else 0.0,
                )
                for item in self.alignments
            ],
            unassigned_note_ids=list(self.unassigned_note_ids),
            unassigned_token_ids=list(self.unassigned_token_ids),
            confidence=float(self.confidence) if self.confidence is not None else 0.0,
            method=method,
            warnings=list(self.warnings or []),
        )
