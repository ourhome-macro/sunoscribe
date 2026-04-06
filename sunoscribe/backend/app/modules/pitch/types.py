from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NoteType(str, Enum):
    WHOLE = "whole"
    HALF = "half"
    QUARTER = "quarter"
    EIGHTH = "eighth"
    SIXTEENTH = "sixteenth"
    THIRTY_SECOND = "thirty_second"
    DOTTED_QUARTER = "dotted_quarter"
    DOTTED_EIGHTH = "dotted_eighth"
    TRIPLET = "triplet"


@dataclass
class Note:
    pitch: str
    start_time: float
    end_time: float
    confidence: float


@dataclass
class QuantizedNote(Note):
    duration_beats: float
    note_type: NoteType
    measure_num: Optional[int] = None
    beat_position: Optional[float] = None
    lyric: Optional[str] = None


@dataclass
class MetaInfo:
    bpm: float
    bpm_confidence: float
    key: str
    key_confidence: float
    duration_sec: float
    time_signature: str = "4/4"
    rhythm_type: str = "stable"
    total_measures: Optional[int] = None


@dataclass
class PitchAnalysisResult:
    version: str
    meta: MetaInfo
    analysis_info: Dict[str, Any] = field(default_factory=dict)
    measures: List[Dict[str, Any]] = field(default_factory=list)
    raw_notes: List[Note] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
