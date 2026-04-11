from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..score_ir.types import ScoreIR
from .types import AlignmentDraft


@dataclass
class AlignmentRefineRequest:
    score_ir: ScoreIR
    draft: AlignmentDraft
    use_validator_warnings: bool = True
    allow_fallback_to_original: bool = True
    metadata: Dict[str, Any] | None = None


@dataclass
class AlignmentRefineDebugInfo:
    payload: dict | None = None
    llm_raw_output: str | None = None
    parser_error: str | None = None
    policy_reasons: list[str] | None = None
    exception_message: str | None = None


@dataclass
class AlignmentRefineResponse:
    draft: AlignmentDraft
    accepted: bool
    source: str
    warnings: List[str] = field(default_factory=list)
    validator_warnings_before: List[str] = field(default_factory=list)
    validator_warnings_after: List[str] = field(default_factory=list)
    debug: Optional[AlignmentRefineDebugInfo] = None
