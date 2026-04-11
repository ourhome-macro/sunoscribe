from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class TokenNoteAlignment:
    token_id: str
    note_ids: List[str]
    melisma: bool = False
    confidence: float = 0.0


@dataclass
class AlignmentDraft:
    alignments: List[TokenNoteAlignment] = field(default_factory=list)
    unassigned_note_ids: List[str] = field(default_factory=list)
    unassigned_token_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "baseline_v1"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
