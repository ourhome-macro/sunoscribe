from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _AudioAnalysisSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioAnalysisPitch(_AudioAnalysisSchema):
    available: bool
    note_count: int = 0
    voiced_frame_count: int = 0
    pitch_class_histogram: dict[str, int] = Field(default_factory=dict)
    most_common_pitch_classes: list[str] = Field(default_factory=list)
    melodic_direction: Literal["ascending_bias", "descending_bias", "balanced"] | None = None
    ascending_interval_count: int = 0
    descending_interval_count: int = 0
    repeated_interval_count: int = 0
    average_note_confidence: float | None = None
    evidence: str


class AudioAnalysisExpression(_AudioAnalysisSchema):
    available: bool
    vibrato_segment_count: int = 0
    slide_segment_count: int = 0
    long_note_stability: float | None = None
    vibrato_segments: list[dict[str, Any]] = Field(default_factory=list)
    slide_segments: list[dict[str, Any]] = Field(default_factory=list)
    suspicious_pitch_note_ids: list[str] = Field(default_factory=list)
    evidence: str


class AudioAnalysisRange(_AudioAnalysisSchema):
    available: bool
    lowest_pitch: str | None = None
    highest_pitch: str | None = None
    lowest_pitch_midi: int | None = None
    highest_pitch_midi: int | None = None
    span_semitones: int | None = None
    tessitura_low_midi: int | None = None
    tessitura_high_midi: int | None = None
    tessitura_low: str | None = None
    tessitura_high: str | None = None
    highest_note_locations: list[dict[str, Any]] = Field(default_factory=list)
    section_ranges: list[dict[str, Any]] = Field(default_factory=list)
    evidence: str


class AudioAnalysisRhythm(_AudioAnalysisSchema):
    available: bool
    bpm: float | None = None
    bpm_confidence: float | None = None
    rhythm_type: str | None = None
    stability_score: float | None = None
    beat_count: int = 0
    average_grid_offset_sec: float | None = None
    median_grid_offset_sec: float | None = None
    syncopation_note_count: int = 0
    weak_beat_start_count: int = 0
    average_duration_beats: float | None = None
    evidence: str


class AudioAnalysisLyrics(_AudioAnalysisSchema):
    available: bool
    status: Literal["ok", "missing_lyrics"]
    line_count: int = 0
    keyword_candidates: list[str] = Field(default_factory=list)
    sentiment_label: Literal["positive", "negative", "mixed", "neutral"] | None = None
    sentiment_score: int | None = None
    positive_keyword_hits: list[str] = Field(default_factory=list)
    negative_keyword_hits: list[str] = Field(default_factory=list)
    emotion_curve: list[dict[str, Any]] = Field(default_factory=list)
    evidence: str


class AudioAnalysisSummary(_AudioAnalysisSchema):
    headline: str
    highlights: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)


class AudioAnalysisReport(_AudioAnalysisSchema):
    version: str
    project_id: str
    revision_id: str
    status: Literal["ok", "partial", "failed"]
    pitch: AudioAnalysisPitch
    expression: AudioAnalysisExpression
    range: AudioAnalysisRange
    rhythm: AudioAnalysisRhythm
    lyrics: AudioAnalysisLyrics
    summary: AudioAnalysisSummary
    warnings: list[str] = Field(default_factory=list)


class AudioAnalysisReportResponse(_AudioAnalysisSchema):
    artifact_id: uuid.UUID | None = None
    artifact_status: str | None = None
    artifact_created_at: datetime | None = None
    report: AudioAnalysisReport
