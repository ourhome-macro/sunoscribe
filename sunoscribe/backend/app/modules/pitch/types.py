from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class Note:
    pitch: str
    start_time: float
    end_time: float
    confidence: float


@dataclass
class MetaInfo:
    bpm: float
    bpm_confidence: float
    key: str
    key_confidence: float
    duration_sec: float


@dataclass
class PitchAnalysisResult:
    version: str
    meta: MetaInfo
    analysis_info: Dict[str, Any] = field(default_factory=dict)
    raw_notes: List[Note] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
