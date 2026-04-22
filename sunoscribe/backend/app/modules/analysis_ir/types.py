from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.modules.pitch.types import Note


@dataclass
class AnalysisIRMeta:
    source_version: str
    bpm: float
    key: str
    time_signature: str
    duration_sec: float
    total_measures: Optional[int] = None


@dataclass
class ChordSpan:
    start_time: float
    end_time: float
    measure_num: Optional[int]
    symbol: str
    root: str
    quality: str
    bass: Optional[str] = None
    confidence: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FormSection:
    id: str
    label: str
    start_time: float
    end_time: float
    measure_start: Optional[int] = None
    measure_end: Optional[int] = None
    confidence: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisIR:
    version: str
    meta: AnalysisIRMeta
    source_stems: Dict[str, str] = field(default_factory=dict)
    lead_source_stem: Optional[str] = None
    bass_source_stem: Optional[str] = None
    selected_lead_melody: List[Note] = field(default_factory=list)
    chord_timeline: List[ChordSpan] = field(default_factory=list)
    selected_bassline: List[Note] = field(default_factory=list)
    form_sections: List[FormSection] = field(default_factory=list)
    confidence: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
