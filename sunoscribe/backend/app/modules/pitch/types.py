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
class PitchPipelineRequest:
    lead_audio_path: str
    source_audio_path: Optional[str] = None
    rhythm_audio_path: Optional[str] = None
    key_audio_path: Optional[str] = None
    harmony_audio_path: Optional[str] = None
    bass_audio_path: Optional[str] = None
    source_stems: Dict[str, str] = field(default_factory=dict)


@dataclass
class NoteCandidateSet:
    role: str
    source_stem: Optional[str] = None
    input_audio_path: Optional[str] = None
    notes: List[Note] = field(default_factory=list)
    selected_notes: List[Note] = field(default_factory=list)
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MelodySourceCandidate:
    source_id: str
    backend: str
    source_stem: Optional[str] = None
    input_audio_path: Optional[str] = None
    notes: List[Note] = field(default_factory=list)
    f0_track: Optional["F0Track"] = None
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class F0Frame:
    time_sec: float
    frequency_hz: float
    confidence: float
    voiced: bool
    pitch_midi: Optional[float] = None


@dataclass
class VocalActivitySegment:
    start_time: float
    end_time: float
    state: str
    voiced_ratio: float
    mean_confidence: float
    source_stem: Optional[str] = None
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class F0Track:
    source_stem: Optional[str] = None
    input_audio_path: Optional[str] = None
    backend: Optional[str] = None
    frames: List[F0Frame] = field(default_factory=list)
    vocal_activity: List[VocalActivitySegment] = field(default_factory=list)
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RhythmGrid:
    source_stem: Optional[str]
    input_audio_path: Optional[str]
    beat_times: List[float] = field(default_factory=list)
    downbeat_times: List[float] = field(default_factory=list)
    bpm: float = 0.0
    bpm_confidence: float = 0.0
    beats_per_bar: int = 4
    beat_unit: int = 4
    beat_duration_sec: float = 0.0
    rhythm_type: str = "stable"
    stability_score: float = 0.0
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArrangementSegmentDecision:
    start_time: float
    end_time: float
    state: str
    lead_source_id: Optional[str] = None
    support_source_id: Optional[str] = None
    selected_lead_count: int = 0
    selected_support_count: int = 0
    suppressed_count: int = 0
    max_polyphony: int = 1
    transition_window_sec: float = 0.0
    analysis_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArrangementDecision:
    selected_lead_notes: List[Note] = field(default_factory=list)
    selected_support_notes: List[Note] = field(default_factory=list)
    segment_decisions: List[ArrangementSegmentDecision] = field(default_factory=list)
    suppressed_candidates: List[Dict[str, Any]] = field(default_factory=list)
    lead_source_id: Optional[str] = None
    support_source_id: Optional[str] = None
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    analysis_info: Dict[str, Any] = field(default_factory=dict)

    @property
    def lead_notes(self) -> List[Note]:
        return self.selected_lead_notes

    @property
    def support_notes(self) -> List[Note]:
        return self.selected_support_notes


@dataclass
class SemanticAudioResult:
    source_stems: Dict[str, str] = field(default_factory=dict)
    f0_track: Optional[F0Track] = None
    melody_candidates: NoteCandidateSet = field(
        default_factory=lambda: NoteCandidateSet(role="melody_candidates")
    )
    harmony_candidates: NoteCandidateSet = field(
        default_factory=lambda: NoteCandidateSet(role="harmony_candidates")
    )
    bass_root_candidates: NoteCandidateSet = field(
        default_factory=lambda: NoteCandidateSet(role="bass_root_candidates")
    )
    rhythm_grid: Optional[RhythmGrid] = None


@dataclass
class PitchAnalysisResult:
    version: str
    meta: MetaInfo
    analysis_info: Dict[str, Any] = field(default_factory=dict)
    measures: List[Dict[str, Any]] = field(default_factory=list)
    lead_notes: List[Note] = field(default_factory=list)
    raw_notes: List[Note] = field(default_factory=list)
    f0_track: Optional[F0Track] = None
    semantic_audio: Optional[SemanticAudioResult] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
