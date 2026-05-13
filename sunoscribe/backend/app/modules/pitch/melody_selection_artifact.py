from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from statistics import mean
from typing import Any

from .note_utils import midi_to_note, note_to_midi
from .phrase_postprocessor import PhraseAwarePostprocessor, PhrasePostprocessConfig
from .reason_codes import (
    LOW_CONFIDENCE,
    LOW_VOICED_RATIO,
    OUTSIDE_VOCAL_RANGE,
    OVERLAPS_STRONGER_CANDIDATE,
    TOO_SHORT,
    TOO_UNSTABLE,
    UNCERTAIN,
)


@dataclass(frozen=True)
class MelodySelectionConfig:
    prefer_preselected_notes: bool = True
    postprocess_profile: str = "conservative"
    min_confidence: float = 0.52
    min_duration_sec: float = 0.12
    min_voiced_ratio: float = 0.5
    min_stability: float = 0.35
    vocal_min_midi: float = 48.0
    vocal_max_midi: float = 84.0
    overlap_window_sec: float = 0.02
    phrase_postprocess_enabled: bool = True
    phrase_max_gap_sec: float = 0.12
    phrase_short_gap_sec: float = 0.08
    phrase_same_pitch_tolerance_semitones: int = 1
    phrase_short_note_sec: float = 0.18
    phrase_short_note_neighbor_min_sec: float = 0.12
    phrase_octave_jump_semitones: int = 9
    phrase_octave_neighbor_tolerance_semitones: int = 2
    phrase_median_window: int = 5
    phrase_median_deviation_semitones: int = 2
    phrase_median_max_adjust_semitones: int = 4
    phrase_median_max_note_sec: float = 0.24
    phrase_remove_isolated_fragments_enabled: bool = False
    phrase_isolated_fragment_max_sec: float = 0.16
    phrase_isolated_fragment_max_confidence: float = 0.58
    phrase_isolated_fragment_min_jump_semitones: int = 7
    phrase_sustain_short_gaps_enabled: bool = True
    phrase_sustain_gap_sec: float = 0.18
    phrase_sustain_max_pitch_delta_semitones: int = 2
    phrase_max_iterations: int = 2


class RuleBasedMelodySelector:
    def __init__(self, config: MelodySelectionConfig | None = None) -> None:
        self.config = config or MelodySelectionConfig()
        self.postprocessor = PhraseAwarePostprocessor(self._postprocess_config())

    def select(
        self,
        *,
        note_candidates: dict[str, Any] | None,
        pitch_contours: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        candidates, input_source = self._candidate_items(note_candidates, pitch_contours)
        if not candidates:
            return None

        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for candidate in candidates:
            reasons = self._base_reasons(candidate)
            if reasons:
                rejected.append(self._rejected(candidate, reasons))
            else:
                selected.append(self._selected(candidate))

        selected, overlap_rejected = self._resolve_overlaps(selected)
        rejected.extend(overlap_rejected)
        inherited_reason_counts = Counter(reason for item in selected for reason in item.get("reason_codes", []))
        postprocess_result = self.postprocessor.process_dict_notes(selected)
        selected = [self._selected_from_postprocessed(item) for item in postprocess_result.notes]
        selected.sort(key=lambda item: (item["start_time_sec"], item["end_time_sec"], item["pitch_center_midi"]))
        rejected.sort(key=lambda item: (item["start_time_sec"], item["end_time_sec"], str(item["candidate_id"])))
        reason_counts = Counter(reason for item in rejected for reason in item.get("reason_codes", []))
        selected_reason_counts = Counter(reason for item in selected for reason in item.get("reason_codes", []))
        selected_conf = [float(item["confidence"]) for item in selected]
        rejected_conf = [float(item["confidence"]) for item in rejected]
        postprocess_diagnostics = postprocess_result.diagnostics()
        action_dicts = postprocess_diagnostics.get("actions") if isinstance(postprocess_diagnostics, dict) else None
        if isinstance(action_dicts, list):
            for action in action_dicts:
                if isinstance(action, dict):
                    details = action.get("details") if isinstance(action.get("details"), dict) else {}
                    action["details"] = {"profile": self._postprocess_profile(), **details}
        inherited_reason_code_counts = dict(sorted(inherited_reason_counts.items()))
        return {
            "version": "selected_melody_v1",
            "selected_notes": selected,
            "rejected_candidates": rejected,
            "summary": {
                "input_candidate_count": len(candidates),
                "input_source": input_source,
                "prefer_preselected_notes": self.config.prefer_preselected_notes,
                "pre_postprocess_selected_count": postprocess_result.input_count,
                "selected_count": len(selected),
                "rejected_count": len(rejected),
                "rejection_reason_counts": dict(sorted(reason_counts.items())),
                "selected_reason_counts": dict(sorted(selected_reason_counts.items())),
                "inherited_reason_code_counts": inherited_reason_code_counts,
                "postprocess_action_counts": postprocess_diagnostics["action_counts"],
                "postprocess_reason_code_counts": postprocess_diagnostics["reason_code_counts"],
                "mean_selected_confidence": round(mean(selected_conf), 6) if selected_conf else 0.0,
                "mean_rejected_confidence": round(mean(rejected_conf), 6) if rejected_conf else 0.0,
            },
            "postprocess": {
                **postprocess_diagnostics,
                "inherited_reason_code_counts": inherited_reason_code_counts,
            },
            "config": {
                "phrase_postprocess_enabled": self.config.phrase_postprocess_enabled,
                "postprocess_profile": self._postprocess_profile(),
                "phrase_max_gap_sec": self.config.phrase_max_gap_sec,
                "phrase_short_gap_sec": self.config.phrase_short_gap_sec,
                "phrase_short_note_sec": self.config.phrase_short_note_sec,
                "phrase_octave_jump_semitones": self.config.phrase_octave_jump_semitones,
                "phrase_median_window": self.config.phrase_median_window,
                "phrase_remove_isolated_fragments_enabled": self._isolated_fragment_remove_enabled(),
                "phrase_sustain_short_gaps_enabled": self.config.phrase_sustain_short_gaps_enabled,
                "input_source": input_source,
                "prefer_preselected_notes": self.config.prefer_preselected_notes,
            },
        }

    def _candidate_items(
        self,
        note_candidates: dict[str, Any] | None,
        pitch_contours: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], str]:
        raw_notes, input_source = _extract_candidate_notes(
            note_candidates,
            prefer_preselected_notes=bool(self.config.prefer_preselected_notes),
        )
        if raw_notes:
            return [self._normalize_candidate(note, index) for index, note in enumerate(raw_notes, start=1)], input_source
        contours = pitch_contours.get("contours") if isinstance(pitch_contours, dict) else None
        if isinstance(contours, list):
            return [self._candidate_from_contour(contour, index) for index, contour in enumerate(contours, start=1) if isinstance(contour, dict)], "pitch_contours.contours"
        return [], "none"

    def _normalize_candidate(self, note: dict[str, Any], index: int) -> dict[str, Any]:
        start = _safe_float(_first(note, "start_time_sec", "start_time", "onset_sec")) or 0.0
        end = _safe_float(_first(note, "end_time_sec", "end_time", "offset_sec"))
        duration = _safe_float(_first(note, "duration_sec", "duration"))
        if end is None and duration is not None:
            end = start + duration
        if end is None:
            end = start
        pitch_center = _pitch_center(note)
        confidence = _safe_float(note.get("confidence"))
        if confidence is None:
            confidence = _safe_float(note.get("mean_confidence")) or 0.0
        source_contours = note.get("source_contours") or note.get("source_contour_ids") or []
        source_candidate_ids = note.get("source_candidate_ids") or []
        return {
            "candidate_id": str(note.get("id") or note.get("candidate_id") or f"cand_{index:05d}"),
            "start_time_sec": float(start),
            "end_time_sec": float(end),
            "duration_sec": max(0.0, float(end) - float(start)),
            "pitch_center_midi": pitch_center,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "voiced_ratio": _safe_float(note.get("voiced_ratio")),
            "stability": _safe_float(note.get("stability")),
            "source_contour_ids": [str(item) for item in source_contours] if isinstance(source_contours, list) else [],
            "source_candidate_ids": [str(item) for item in source_candidate_ids] if isinstance(source_candidate_ids, list) else [],
            "reason_codes": _unique([str(item) for item in note.get("reason_codes") or []]),
        }

    def _candidate_from_contour(self, contour: dict[str, Any], index: int) -> dict[str, Any]:
        return self._normalize_candidate(
            {
                "id": contour.get("id") or f"contour_{index:05d}",
                "start_time_sec": contour.get("start_time_sec"),
                "end_time_sec": contour.get("end_time_sec"),
                "pitch_center_midi": contour.get("pitch_center_midi"),
                "confidence": contour.get("mean_confidence"),
                "voiced_ratio": contour.get("voiced_ratio"),
                "stability": contour.get("stability"),
                "source_contour_ids": [contour.get("id")],
            },
            index,
        )

    def _base_reasons(self, candidate: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if float(candidate["confidence"]) < self.config.min_confidence:
            reasons.append(LOW_CONFIDENCE)
        if float(candidate["duration_sec"]) < self.config.min_duration_sec:
            reasons.append(TOO_SHORT)
        pitch_center = candidate.get("pitch_center_midi")
        if pitch_center is None or not (self.config.vocal_min_midi <= float(pitch_center) <= self.config.vocal_max_midi):
            reasons.append(OUTSIDE_VOCAL_RANGE)
        voiced_ratio = candidate.get("voiced_ratio")
        if voiced_ratio is not None and float(voiced_ratio) < self.config.min_voiced_ratio:
            reasons.append(LOW_VOICED_RATIO)
        stability = candidate.get("stability")
        if stability is not None and float(stability) < self.config.min_stability:
            reasons.append(TOO_UNSTABLE)
        return _unique(reasons)

    def _resolve_overlaps(self, selected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        kept: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for note in sorted(selected, key=lambda item: (item["start_time_sec"], -item["confidence"], -item["duration_sec"])):
            overlap_index = next((idx for idx, current in enumerate(kept) if _overlaps(note, current, self.config.overlap_window_sec)), None)
            if overlap_index is None:
                kept.append(note)
                continue
            current = kept[overlap_index]
            if _priority(note) > _priority(current):
                rejected.append(self._rejected(current, [OVERLAPS_STRONGER_CANDIDATE]))
                kept[overlap_index] = note
            else:
                rejected.append(self._rejected(note, [OVERLAPS_STRONGER_CANDIDATE]))
        return kept, rejected

    @staticmethod
    def _selected(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate["candidate_id"],
            "start_time_sec": round(float(candidate["start_time_sec"]), 6),
            "end_time_sec": round(float(candidate["end_time_sec"]), 6),
            "duration_sec": round(float(candidate["duration_sec"]), 6),
            "pitch_center_midi": round(float(candidate["pitch_center_midi"]), 6) if candidate.get("pitch_center_midi") is not None else None,
            "confidence": round(float(candidate["confidence"]), 6),
            "source_contour_ids": list(candidate.get("source_contour_ids") or []),
            "source_candidate_ids": list(candidate.get("source_candidate_ids") or []),
            "reason_codes": list(candidate.get("reason_codes") or []),
        }

    @staticmethod
    def _selected_from_postprocessed(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate["candidate_id"],
            "start_time_sec": round(float(candidate["start_time_sec"]), 6),
            "end_time_sec": round(float(candidate["end_time_sec"]), 6),
            "duration_sec": round(max(0.0, float(candidate["end_time_sec"]) - float(candidate["start_time_sec"])), 6),
            "pitch_center_midi": round(float(candidate["pitch_center_midi"]), 6) if candidate.get("pitch_center_midi") is not None else None,
            "confidence": round(float(candidate["confidence"]), 6),
            "source_contour_ids": list(candidate.get("source_contour_ids") or []),
            "source_candidate_ids": list(candidate.get("source_candidate_ids") or []),
            "reason_codes": list(candidate.get("reason_codes") or []),
        }

    def _postprocess_config(self) -> PhrasePostprocessConfig:
        profile = self._postprocess_profile()
        return PhrasePostprocessConfig(
            enabled=bool(self.config.phrase_postprocess_enabled),
            profile=profile,
            max_phrase_gap_sec=float(self.config.phrase_max_gap_sec),
            short_gap_sec=float(self.config.phrase_short_gap_sec),
            same_pitch_tolerance_semitones=int(self.config.phrase_same_pitch_tolerance_semitones),
            short_note_sec=float(self.config.phrase_short_note_sec),
            short_note_neighbor_min_sec=float(self.config.phrase_short_note_neighbor_min_sec),
            octave_jump_semitones=int(self.config.phrase_octave_jump_semitones),
            octave_neighbor_tolerance_semitones=int(self.config.phrase_octave_neighbor_tolerance_semitones),
            median_window=int(self.config.phrase_median_window),
            median_deviation_semitones=int(self.config.phrase_median_deviation_semitones),
            median_max_adjust_semitones=int(self.config.phrase_median_max_adjust_semitones),
            median_max_note_sec=float(self.config.phrase_median_max_note_sec),
            remove_isolated_fragments_enabled=self._isolated_fragment_remove_enabled(),
            isolated_fragment_max_sec=float(self.config.phrase_isolated_fragment_max_sec),
            isolated_fragment_max_confidence=float(self.config.phrase_isolated_fragment_max_confidence),
            isolated_fragment_min_jump_semitones=int(self.config.phrase_isolated_fragment_min_jump_semitones),
            sustain_short_gaps_enabled=bool(self.config.phrase_sustain_short_gaps_enabled),
            sustain_gap_sec=float(self.config.phrase_sustain_gap_sec),
            sustain_max_pitch_delta_semitones=int(self.config.phrase_sustain_max_pitch_delta_semitones),
            vocal_min_midi=int(self.config.vocal_min_midi),
            vocal_max_midi=int(self.config.vocal_max_midi),
            max_iterations=int(self.config.phrase_max_iterations),
        )

    def _postprocess_profile(self) -> str:
        profile = str(self.config.postprocess_profile or "conservative").strip().lower()
        return profile if profile in {"conservative", "cleanup_aggressive"} else "conservative"

    def _isolated_fragment_remove_enabled(self) -> bool:
        return self._postprocess_profile() == "cleanup_aggressive" and bool(self.config.phrase_remove_isolated_fragments_enabled)

    @staticmethod
    def _rejected(candidate: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
        reason_codes = _unique(reasons + ([UNCERTAIN] if reasons else []))
        pitch_center = candidate.get("pitch_center_midi")
        return {
            "candidate_id": candidate["candidate_id"],
            "start_time_sec": round(float(candidate["start_time_sec"]), 6),
            "end_time_sec": round(float(candidate["end_time_sec"]), 6),
            "pitch_center_midi": round(float(pitch_center), 6) if pitch_center is not None else None,
            "confidence": round(float(candidate["confidence"]), 6),
            "reason_codes": reason_codes,
        }


def selected_notes_to_pitch_notes(selected_melody: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(selected_melody, dict):
        return []
    notes = []
    for item in selected_melody.get("selected_notes") or []:
        if not isinstance(item, dict):
            continue
        pitch_center = _safe_float(item.get("pitch_center_midi"))
        if pitch_center is None:
            continue
        notes.append(
            {
                "id": item.get("candidate_id"),
                "pitch": midi_to_note(pitch_center),
                "pitch_midi_float": pitch_center,
                "pitch_center_midi": pitch_center,
                "start_time": item.get("start_time_sec"),
                "end_time": item.get("end_time_sec"),
                "confidence": item.get("confidence", 0.0),
                "source_candidate_id": item.get("candidate_id"),
                "source_candidate_ids": item.get("source_candidate_ids") or [],
                "source_contours": item.get("source_contour_ids") or [],
                "reason_codes": item.get("reason_codes") or [],
            }
        )
    return notes


def _extract_candidate_notes(
    note_candidates: dict[str, Any] | None,
    *,
    prefer_preselected_notes: bool,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(note_candidates, dict):
        return [], "none"
    melody = note_candidates.get("melody_candidates")
    containers = [("melody_candidates", melody), ("note_candidates", note_candidates)]
    if prefer_preselected_notes:
        for source, container in containers:
            if not isinstance(container, dict):
                continue
            notes = container.get("selected_notes") if isinstance(container.get("selected_notes"), list) else None
            if notes:
                return [note for note in notes if isinstance(note, dict)], f"{source}.selected_notes_preselected"
    for source, container in containers:
        if not isinstance(container, dict):
            continue
        notes = container.get("notes") if isinstance(container.get("notes"), list) else None
        if notes:
            return [note for note in notes if isinstance(note, dict)], f"{source}.notes"
    for source, container in containers:
        if not isinstance(container, dict):
            continue
        notes = container.get("selected_notes") if isinstance(container.get("selected_notes"), list) else None
        if notes:
            return [note for note in notes if isinstance(note, dict)], f"{source}.selected_notes_legacy_fallback"
    return [], "none"


def _pitch_center(note: dict[str, Any]) -> float | None:
    value = _safe_float(_first(note, "pitch_center_midi", "midi_float", "pitch_midi", "midi_pitch"))
    if value is not None:
        return value
    pitch = note.get("pitch") or note.get("pitch_name")
    if isinstance(pitch, str) and pitch.strip():
        try:
            return float(note_to_midi(pitch))
        except Exception:
            return None
    frequency = _safe_float(_first(note, "f0_hz", "frequency_hz", "frequency"))
    if frequency is not None and frequency > 0:
        return 69.0 + 12.0 * math.log2(frequency / 440.0)
    return None


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _overlaps(left: dict[str, Any], right: dict[str, Any], window_sec: float) -> bool:
    return float(left["start_time_sec"]) < float(right["end_time_sec"]) - window_sec and float(right["start_time_sec"]) < float(left["end_time_sec"]) - window_sec


def _priority(item: dict[str, Any]) -> tuple[float, float, float]:
    return (float(item["confidence"]), float(item["duration_sec"]), float(item.get("pitch_center_midi") or 0.0))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
