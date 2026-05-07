from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ScoreMeta:
    source_version: str
    bpm: float
    bpm_confidence: float
    key: str
    key_confidence: float
    duration_sec: float
    time_signature: str
    rhythm_type: str
    total_measures: Optional[int]
    has_anacrusis: bool
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreNote:
    id: str
    pitch: str
    pitch_midi: Optional[int]
    start_time: float
    end_time: float
    duration_sec: float
    duration_beats: Optional[float]
    note_type: Optional[str]
    measure_num: Optional[int]
    beat_position: Optional[float]
    confidence: float
    lyric: Optional[str]
    is_raw: bool
    is_candidate_ornament: bool
    tie_candidate: bool
    source: str


@dataclass
class ScoreMeasure:
    measure_num: int
    start_time: float
    end_time: float
    duration_sec: float
    is_anacrusis: bool
    note_ids: List[str] = field(default_factory=list)


@dataclass
class ScoreChord:
    id: str
    start_time: float
    end_time: float
    measure_num: Optional[int]
    symbol: str
    root: str
    quality: str
    bass: Optional[str]
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreSection:
    id: str
    label: str
    start_time: float
    end_time: float
    measure_start: Optional[int]
    measure_end: Optional[int]
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LyricsToken:
    id: str
    text: str
    segment_id: str
    lang: Optional[str]
    index_in_segment: int


@dataclass
class LyricsSegment:
    id: str
    start: float
    end: float
    text: str
    raw_text: str
    tokens: List[LyricsToken] = field(default_factory=list)


@dataclass
class IssueSpot:
    type: str
    severity: str
    measure_num: Optional[int]
    note_ids: List[str] = field(default_factory=list)
    segment_ids: List[str] = field(default_factory=list)
    message: str = ""


@dataclass
class AnalysisHints:
    downbeat_confidence: Optional[float]
    rhythm_stability: Optional[float]
    has_accompaniment: Optional[bool]
    detector: Optional[str]
    beat_backend: Optional[str]
    key_backend: Optional[str]
    quantize_mode: Optional[str]
    issue_count: int = 0


@dataclass
class ScoreIR:
    meta: ScoreMeta
    notes: List[ScoreNote] = field(default_factory=list)
    instrumental_melody_notes: List[ScoreNote] = field(default_factory=list)
    bassline_notes: List[ScoreNote] = field(default_factory=list)
    measures: List[ScoreMeasure] = field(default_factory=list)
    chord_timeline: List[ScoreChord] = field(default_factory=list)
    form_sections: List[ScoreSection] = field(default_factory=list)
    lyrics_segments: List[LyricsSegment] = field(default_factory=list)
    analysis_hints: AnalysisHints = field(
        default_factory=lambda: AnalysisHints(
            downbeat_confidence=None,
            rhythm_stability=None,
            has_accompaniment=None,
            detector=None,
            beat_backend=None,
            key_backend=None,
            quantize_mode=None,
        )
    )
    issue_spots: List[IssueSpot] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
