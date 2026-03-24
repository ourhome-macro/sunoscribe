from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict

from .types import PitchAnalysisResult


class PitchResultSerializer:
    """P0 结果序列化。"""

    @staticmethod
    def to_dict(result: PitchAnalysisResult) -> Dict[str, Any]:
        return asdict(result)

    @staticmethod
    def to_json(result: PitchAnalysisResult, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(
            PitchResultSerializer.to_dict(result),
            ensure_ascii=ensure_ascii,
            indent=indent,
        )
