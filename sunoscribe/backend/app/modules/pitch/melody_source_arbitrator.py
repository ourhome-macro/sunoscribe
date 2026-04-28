from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .config import PitchDetectionConfig
from .note_utils import note_to_midi
from .types import (
    ArrangementDecision,
    ArrangementSegmentDecision,
    F0Track,
    MelodySourceCandidate,
    Note,
    RhythmGrid,
    VocalActivitySegment,
)


@dataclass
class SourceNote(Note):
    source: str = ""
    source_stem: str | None = None


class MelodySourceArbitrator:
    """Deterministic source arbitration for lead melody and support notes."""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    def arbitrate(
        self,
        *,
        rmvpe_notes: list[Any] | None = None,
        basic_pitch_notes: list[Any] | None = None,
        basic_notes: list[Any] | None = None,
        vocal_activity: list[Any] | None = None,
        max_polyphony: int | None = None,
    ) -> ArrangementDecision:
        rmvpe_source_notes = self._coerce_source_notes(
            rmvpe_notes or [],
            default_source="rmvpe",
            default_source_stem="vocals",
        )
        basic_source_notes = self._coerce_source_notes(
            basic_pitch_notes if basic_pitch_notes is not None else (basic_notes or []),
            default_source="basic-pitch",
            default_source_stem="mix",
        )
        f0_track = F0Track(
            source_stem="vocals",
            backend="rmvpe",
            vocal_activity=self._coerce_vocal_activity(vocal_activity or []),
        )
        original_vocal_limit = self.config.arrangement_vocal_support_max_polyphony
        original_climax_limit = self.config.arrangement_climax_support_max_polyphony
        original_instrumental_limit = self.config.arrangement_instrumental_max_polyphony
        if max_polyphony is not None:
            support_limit = max(0, int(max_polyphony) - max(1, int(self.config.arrangement_lead_max_polyphony)))
            self.config.arrangement_vocal_support_max_polyphony = support_limit
            self.config.arrangement_climax_support_max_polyphony = support_limit
            self.config.arrangement_instrumental_max_polyphony = max(0, int(max_polyphony))
        try:
            return self.decide(
                rmvpe_candidate=MelodySourceCandidate(
                    source_id="rmvpe:vocals",
                    backend="rmvpe",
                    source_stem="vocals",
                    notes=rmvpe_source_notes,
                    f0_track=f0_track,
                ),
                basic_pitch_candidate=MelodySourceCandidate(
                    source_id="basic-pitch:mix",
                    backend="basic-pitch",
                    source_stem="mix",
                    notes=basic_source_notes,
                ),
            )
        finally:
            self.config.arrangement_vocal_support_max_polyphony = original_vocal_limit
            self.config.arrangement_climax_support_max_polyphony = original_climax_limit
            self.config.arrangement_instrumental_max_polyphony = original_instrumental_limit

    def decide(
        self,
        *,
        rmvpe_candidate: MelodySourceCandidate,
        basic_pitch_candidate: MelodySourceCandidate | None = None,
        rhythm_grid: RhythmGrid | None = None,
    ) -> ArrangementDecision:
        if not bool(self.config.melody_arbitrator_enabled):
            lead_notes = self._clone_notes(rmvpe_candidate.notes)
            return ArrangementDecision(
                selected_lead_notes=lead_notes,
                lead_source_id=rmvpe_candidate.source_id,
                confidence=self._mean_confidence(lead_notes),
                analysis_info={
                    "enabled": False,
                    "selected_lead_count": len(lead_notes),
                },
            )

        basic_pitch_candidate = basic_pitch_candidate or MelodySourceCandidate(
            source_id="basic-pitch:none",
            backend="basic-pitch",
        )
        f0_track = rmvpe_candidate.f0_track
        transition_window_sec = self._transition_window_sec(rhythm_grid)
        segments = self._normalized_segments(
            f0_track=f0_track,
            rmvpe_notes=rmvpe_candidate.notes,
            basic_pitch_notes=basic_pitch_candidate.notes,
        )

        selected_lead: list[Note] = []
        selected_support: list[Note] = []
        suppressed: list[dict[str, object]] = []
        segment_decisions: list[ArrangementSegmentDecision] = []

        for segment in segments:
            segment_state = self._canonical_state(segment.state)
            segment_rmvpe = self._notes_overlapping_segment(rmvpe_candidate.notes, segment)
            segment_basic = self._notes_overlapping_segment(basic_pitch_candidate.notes, segment)
            is_climax = self._is_climax_segment(segment=segment, support_notes=segment_basic)

            if segment_state in {"vocal", "transition", "climax"}:
                lead_source_id = rmvpe_candidate.source_id
                segment_lead = self._limit_polyphony(
                    segment_rmvpe,
                    max_polyphony=max(1, int(self.config.arrangement_lead_max_polyphony)),
                )
                segment_suppressed = self._suppressed_from_difference(
                    source_id=rmvpe_candidate.source_id,
                    backend=rmvpe_candidate.backend,
                    candidates=segment_rmvpe,
                    kept=segment_lead,
                    reason="lead_polyphony_limiter",
                )
                support_limit = (
                    int(self.config.arrangement_climax_support_max_polyphony)
                    if is_climax
                    else int(self.config.arrangement_vocal_support_max_polyphony)
                )
                support_limit = max(0, support_limit)
                segment_support_candidates = self._remove_support_conflicts(
                    support_notes=segment_basic,
                    lead_notes=segment_lead,
                    transition_window_sec=transition_window_sec,
                )
                support_conflicts = self._suppressed_from_difference(
                    source_id=basic_pitch_candidate.source_id,
                    backend=basic_pitch_candidate.backend,
                    candidates=segment_basic,
                    kept=segment_support_candidates,
                    reason="support_conflicts_with_rmvpe_lead",
                )
                segment_support = self._limit_polyphony(
                    segment_support_candidates,
                    max_polyphony=support_limit,
                )
                segment_suppressed.extend(support_conflicts)
                segment_suppressed.extend(
                    self._suppressed_from_difference(
                        source_id=basic_pitch_candidate.source_id,
                        backend=basic_pitch_candidate.backend,
                        candidates=segment_support_candidates,
                        kept=segment_support,
                        reason="support_polyphony_limiter",
                    )
                )
            else:
                lead_source_id = None
                segment_lead = []
                segment_suppressed = [
                    self._suppressed_note_payload(
                        note=note,
                        source_id=rmvpe_candidate.source_id,
                        backend=rmvpe_candidate.backend,
                        reason="rmvpe_disabled_in_instrumental_segment",
                    )
                    for note in segment_rmvpe
                ]
                support_limit = max(0, int(self.config.arrangement_instrumental_max_polyphony))
                segment_support = self._limit_polyphony(segment_basic, max_polyphony=support_limit)
                segment_suppressed.extend(
                    self._suppressed_from_difference(
                        source_id=basic_pitch_candidate.source_id,
                        backend=basic_pitch_candidate.backend,
                        candidates=segment_basic,
                        kept=segment_support,
                        reason="instrumental_polyphony_limiter",
                    )
                )

            selected_lead.extend(segment_lead)
            selected_support.extend(segment_support)
            suppressed.extend(segment_suppressed)
            segment_decisions.append(
                ArrangementSegmentDecision(
                    start_time=float(segment.start_time),
                    end_time=float(segment.end_time),
                    state="climax" if is_climax and segment_state == "vocal" else segment_state,
                    lead_source_id=lead_source_id,
                    support_source_id=basic_pitch_candidate.source_id if segment_support else None,
                    selected_lead_count=len(segment_lead),
                    selected_support_count=len(segment_support),
                    suppressed_count=len(segment_suppressed),
                    max_polyphony=support_limit if segment_state == "instrumental" else max(1, int(self.config.arrangement_lead_max_polyphony)),
                    transition_window_sec=transition_window_sec,
                    analysis_info={
                        "rmvpe_candidate_count": len(segment_rmvpe),
                        "basic_pitch_candidate_count": len(segment_basic),
                        "support_max_polyphony": support_limit,
                    },
                )
            )

        selected_lead = self._dedupe_notes(selected_lead)
        selected_support = self._dedupe_notes(selected_support)
        warnings = self._build_warnings(
            f0_track=f0_track,
            lead_notes=selected_lead,
            rmvpe_candidate=rmvpe_candidate,
            basic_pitch_candidate=basic_pitch_candidate,
        )
        selected_state_counts = self._state_counts(segment_decisions)
        confidence = self._mean_confidence(selected_lead)

        return ArrangementDecision(
            selected_lead_notes=selected_lead,
            selected_support_notes=selected_support,
            segment_decisions=segment_decisions,
            suppressed_candidates=suppressed,
            lead_source_id=rmvpe_candidate.source_id if selected_lead else None,
            support_source_id=basic_pitch_candidate.source_id if selected_support else None,
            confidence=confidence,
            warnings=warnings,
            analysis_info={
                "enabled": True,
                "policy": "rmvpe_vocal_lead_basic_pitch_support",
                "rmvpe_candidate_count": len(rmvpe_candidate.notes),
                "basic_pitch_candidate_count": len(basic_pitch_candidate.notes),
                "selected_lead_count": len(selected_lead),
                "selected_support_count": len(selected_support),
                "suppressed_count": len(suppressed),
                "transition_window_sec": transition_window_sec,
                "lead_max_polyphony": max(1, int(self.config.arrangement_lead_max_polyphony)),
                "vocal_support_max_polyphony": max(0, int(self.config.arrangement_vocal_support_max_polyphony)),
                "climax_support_max_polyphony": max(0, int(self.config.arrangement_climax_support_max_polyphony)),
                "instrumental_max_polyphony": max(0, int(self.config.arrangement_instrumental_max_polyphony)),
                "segment_state_counts": selected_state_counts,
                "segment_decisions": [asdict(item) for item in segment_decisions],
            },
        )

    def _normalized_segments(
        self,
        *,
        f0_track: F0Track | None,
        rmvpe_notes: list[Note],
        basic_pitch_notes: list[Note],
    ) -> list[VocalActivitySegment]:
        if f0_track is not None and f0_track.vocal_activity:
            return sorted(
                [
                    VocalActivitySegment(
                        start_time=float(segment.start_time),
                        end_time=max(float(segment.end_time), float(segment.start_time)),
                        state=self._canonical_state(segment.state),
                        voiced_ratio=float(segment.voiced_ratio),
                        mean_confidence=float(segment.mean_confidence),
                        source_stem=segment.source_stem,
                        analysis_info=dict(segment.analysis_info or {}),
                    )
                    for segment in f0_track.vocal_activity
                    if float(segment.end_time) >= float(segment.start_time)
                ],
                key=lambda item: (item.start_time, item.end_time),
            )

        notes = list(rmvpe_notes or []) + list(basic_pitch_notes or [])
        if not notes:
            return []

        start = min(float(note.start_time) for note in notes)
        end = max(float(note.end_time) for note in notes)
        return [
            VocalActivitySegment(
                start_time=start,
                end_time=max(start, end),
                state="vocal" if rmvpe_notes else "instrumental",
                voiced_ratio=1.0 if rmvpe_notes else 0.0,
                mean_confidence=self._mean_confidence(rmvpe_notes),
                analysis_info={"inferred_from": "missing_f0_track"},
            )
        ]

    def _transition_window_sec(self, rhythm_grid: RhythmGrid | None) -> float:
        if rhythm_grid is None:
            return float(self.config.arrangement_min_transition_window_sec)
        beat_duration = float(rhythm_grid.beat_duration_sec or 0.0)
        if beat_duration <= 0.0 and float(rhythm_grid.bpm or 0.0) > 0.0:
            beat_duration = 60.0 / float(rhythm_grid.bpm)
        bar_duration = beat_duration * max(1, int(rhythm_grid.beats_per_bar or self.config.beats_per_bar))
        raw_window = bar_duration * max(0.0, float(self.config.arrangement_transition_window_bars))
        return round(
            max(
                float(self.config.arrangement_min_transition_window_sec),
                min(float(self.config.arrangement_max_transition_window_sec), raw_window),
            ),
            6,
        )

    def _notes_overlapping_segment(self, notes: Iterable[Note], segment: VocalActivitySegment) -> list[Note]:
        start = float(segment.start_time)
        end = float(segment.end_time)
        return [
            self._clone_note(note)
            for note in notes
            if float(note.end_time) > start and float(note.start_time) < end
        ]

    def _remove_support_conflicts(
        self,
        *,
        support_notes: list[Note],
        lead_notes: list[Note],
        transition_window_sec: float,
    ) -> list[Note]:
        if not support_notes or not lead_notes:
            return self._clone_notes(support_notes)
        conflict_window = max(
            float(self.config.arrangement_support_conflict_window_sec),
            min(float(transition_window_sec), float(self.config.arrangement_lead_conflict_window_sec)),
        )
        kept: list[Note] = []
        for support in support_notes:
            if any(self._notes_conflict(support, lead, window_sec=conflict_window) for lead in lead_notes):
                continue
            kept.append(self._clone_note(support))
        return kept

    def _limit_polyphony(self, notes: list[Note], *, max_polyphony: int) -> list[Note]:
        limit = max(0, int(max_polyphony))
        if limit <= 0 or not notes:
            return []

        selected: list[Note] = []
        ranked = sorted(
            self._clone_notes(notes),
            key=lambda note: (
                -float(note.confidence),
                -(float(note.end_time) - float(note.start_time)),
                float(note.start_time),
                self._note_midi(note),
                str(note.pitch),
            ),
        )
        for note in ranked:
            candidate = selected + [note]
            if self._max_overlap(candidate) <= limit:
                selected.append(note)

        return sorted(selected, key=lambda note: (float(note.start_time), float(note.end_time), str(note.pitch)))

    def _max_overlap(self, notes: list[Note]) -> int:
        if not notes:
            return 0
        timestamps = sorted(
            {
                float(note.start_time)
                for note in notes
            }
            | {
                max(float(note.start_time), float(note.end_time) - 1e-6)
                for note in notes
            }
            | {
                (float(note.start_time) + float(note.end_time)) / 2.0
                for note in notes
            }
        )
        max_count = 0
        for timestamp in timestamps:
            active = sum(
                1
                for note in notes
                if float(note.start_time) <= timestamp < float(note.end_time)
            )
            max_count = max(max_count, active)
        return max_count

    def _suppressed_from_difference(
        self,
        *,
        source_id: str,
        backend: str,
        candidates: list[Note],
        kept: list[Note],
        reason: str,
    ) -> list[dict[str, object]]:
        kept_keys = {self._note_key(note) for note in kept}
        return [
            self._suppressed_note_payload(
                note=note,
                source_id=source_id,
                backend=backend,
                reason=reason,
            )
            for note in candidates
            if self._note_key(note) not in kept_keys
        ]

    def _suppressed_note_payload(
        self,
        *,
        note: Note,
        source_id: str,
        backend: str,
        reason: str,
    ) -> dict[str, object]:
        return {
            "source_id": source_id,
            "backend": backend,
            "pitch": str(note.pitch),
            "start_time": float(note.start_time),
            "end_time": float(note.end_time),
            "confidence": float(note.confidence),
            "reason": reason,
        }

    def _build_warnings(
        self,
        *,
        f0_track: F0Track | None,
        lead_notes: list[Note],
        rmvpe_candidate: MelodySourceCandidate,
        basic_pitch_candidate: MelodySourceCandidate,
    ) -> list[str]:
        warnings: list[str] = []
        if f0_track is None:
            warnings.append("arrangement_arbitration_missing_f0_track")
        if not lead_notes and rmvpe_candidate.notes:
            warnings.append("arrangement_arbitration_removed_all_rmvpe_lead_notes")
        if basic_pitch_candidate.notes and not lead_notes:
            warnings.append("basic_pitch_candidates_kept_as_support_without_lead")
        return warnings

    @staticmethod
    def _canonical_state(raw_state: str) -> str:
        value = str(raw_state or "").strip().lower()
        if value in {"vocal", "voiced", "voice"}:
            return "vocal"
        if value in {"transition", "handoff"}:
            return "transition"
        if value in {"climax", "chorus"}:
            return "climax"
        if value in {"inactive", "instrumental", "silence", "unvoiced", "no_vocal"}:
            return "instrumental"
        return "vocal"

    def _is_climax_segment(self, *, segment: VocalActivitySegment, support_notes: list[Note]) -> bool:
        if self._canonical_state(segment.state) == "climax":
            return True
        duration = max(1e-6, float(segment.end_time) - float(segment.start_time))
        density = len(support_notes) / duration
        return (
            self._canonical_state(segment.state) == "vocal"
            and density >= float(self.config.arrangement_climax_support_density_per_sec)
        )

    def _notes_conflict(self, left: Note, right: Note, *, window_sec: float) -> bool:
        overlaps = float(left.end_time) > float(right.start_time) and float(right.end_time) > float(left.start_time)
        if not overlaps:
            return False
        left_midi = self._note_midi(left)
        right_midi = self._note_midi(right)
        if left_midi <= 0 or right_midi <= 0:
            return abs(float(left.start_time) - float(right.start_time)) <= max(0.0, float(window_sec))
        return abs(left_midi - right_midi) <= 2

    @staticmethod
    def _clone_note(note: Note) -> Note:
        source = getattr(note, "source", None)
        if source is None:
            source = getattr(note, "detector", None)
        source_stem = getattr(note, "source_stem", None)
        if source is not None or source_stem is not None:
            return SourceNote(
                pitch=str(note.pitch),
                start_time=float(note.start_time),
                end_time=float(note.end_time),
                confidence=float(note.confidence),
                source=str(source or ""),
                source_stem=str(source_stem) if source_stem is not None else None,
            )
        return Note(
            pitch=str(note.pitch),
            start_time=float(note.start_time),
            end_time=float(note.end_time),
            confidence=float(note.confidence),
        )

    def _clone_notes(self, notes: Iterable[Note]) -> list[Note]:
        return [self._clone_note(note) for note in notes or []]

    def _coerce_source_notes(
        self,
        notes: Iterable[Any],
        *,
        default_source: str,
        default_source_stem: str,
    ) -> list[SourceNote]:
        coerced: list[SourceNote] = []
        for raw in notes or []:
            if isinstance(raw, dict):
                pitch = raw.get("pitch", "")
                start_time = raw.get("start_time", raw.get("start", 0.0))
                end_time = raw.get("end_time", raw.get("end", start_time))
                confidence = raw.get("confidence", 0.0)
                source = raw.get("source", raw.get("detector", default_source))
                source_stem = raw.get("source_stem", default_source_stem)
            else:
                pitch = getattr(raw, "pitch", "")
                start_time = getattr(raw, "start_time", 0.0)
                end_time = getattr(raw, "end_time", start_time)
                confidence = getattr(raw, "confidence", 0.0)
                source = getattr(raw, "source", getattr(raw, "detector", default_source))
                source_stem = getattr(raw, "source_stem", default_source_stem)
            coerced.append(
                SourceNote(
                    pitch=str(pitch),
                    start_time=float(start_time),
                    end_time=float(end_time),
                    confidence=float(confidence),
                    source=str(source or default_source),
                    source_stem=str(source_stem or default_source_stem),
                )
            )
        return coerced

    def _coerce_vocal_activity(self, segments: Iterable[Any]) -> list[VocalActivitySegment]:
        result: list[VocalActivitySegment] = []
        for raw in segments or []:
            if isinstance(raw, VocalActivitySegment):
                result.append(raw)
                continue
            if isinstance(raw, dict):
                start_time = raw.get("start_time", raw.get("start", 0.0))
                end_time = raw.get("end_time", raw.get("end", start_time))
                state = raw.get("state", "vocal")
                voiced_ratio = raw.get("voiced_ratio", 1.0 if self._canonical_state(str(state)) == "vocal" else 0.0)
                mean_confidence = raw.get("mean_confidence", 0.0)
                source_stem = raw.get("source_stem")
                analysis_info = dict(raw.get("analysis_info") or {})
            else:
                start_time = getattr(raw, "start_time", 0.0)
                end_time = getattr(raw, "end_time", start_time)
                state = getattr(raw, "state", "vocal")
                voiced_ratio = getattr(raw, "voiced_ratio", 1.0)
                mean_confidence = getattr(raw, "mean_confidence", 0.0)
                source_stem = getattr(raw, "source_stem", None)
                analysis_info = dict(getattr(raw, "analysis_info", {}) or {})
            result.append(
                VocalActivitySegment(
                    start_time=float(start_time),
                    end_time=max(float(start_time), float(end_time)),
                    state=self._canonical_state(str(state)),
                    voiced_ratio=float(voiced_ratio),
                    mean_confidence=float(mean_confidence),
                    source_stem=str(source_stem) if source_stem is not None else None,
                    analysis_info=analysis_info,
                )
            )
        return result

    def _dedupe_notes(self, notes: list[Note]) -> list[Note]:
        seen: set[tuple[str, float, float]] = set()
        deduped: list[Note] = []
        for note in sorted(notes, key=lambda item: (float(item.start_time), float(item.end_time), str(item.pitch))):
            key = self._note_key(note)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(note)
        return deduped

    @staticmethod
    def _note_key(note: Note) -> tuple[str, float, float]:
        return (str(note.pitch), round(float(note.start_time), 6), round(float(note.end_time), 6))

    @staticmethod
    def _mean_confidence(notes: Iterable[Note]) -> float:
        values = [float(note.confidence) for note in notes or []]
        if not values:
            return 0.0
        return round(sum(values) / len(values), 6)

    @staticmethod
    def _note_midi(note: Note) -> int:
        try:
            return int(round(float(note_to_midi(str(note.pitch)))))
        except Exception:
            return 0

    @staticmethod
    def _state_counts(decisions: list[ArrangementSegmentDecision]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in decisions:
            counts[decision.state] = counts.get(decision.state, 0) + 1
        return counts
