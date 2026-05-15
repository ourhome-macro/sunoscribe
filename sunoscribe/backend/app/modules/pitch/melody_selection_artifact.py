from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from statistics import mean
from typing import Any

from .note_utils import midi_to_note, note_to_midi
from .phrase_postprocessor import PhraseAwarePostprocessor, PhrasePostprocessConfig
from .reason_codes import (
    BRIDGE_CONFIDENCE_GUARDED,
    BRIDGE_FROM_F0_CONTOUR,
    BRIDGE_FROM_VOICED_CONTOUR,
    BRIDGE_LOW_CONFIDENCE_LONG_CONTOUR,
    BRIDGE_NO_SELECTED_GAP,
    BRIDGE_OVERLAPS_RAW_CANDIDATE,
    BRIDGE_OVERLAPS_SELECTED_NOTE,
    BRIDGE_UNSTABLE_CONTOUR_GUARDED,
    BRIDGE_VOCAL_ACTIVITY_UNSUPPORTED,
    CONTOUR_TO_CANDIDATE_BRIDGE,
    LOW_CONFIDENCE,
    LOW_VOICED_RATIO,
    OUTSIDE_VOCAL_RANGE,
    OVERLAPS_STRONGER_CANDIDATE,
    POST_F0_CONTOUR_BRIDGE,
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
    post_f0_contour_bridge_enabled: bool = True
    bridge_min_confidence: float = 0.70
    bridge_min_voiced_ratio: float = 0.9
    bridge_min_duration_sec: float = 0.18
    bridge_max_duration_sec: float = 2.5
    bridge_low_confidence_long_contour_sec: float = 2.5
    bridge_high_confidence_floor: float = 0.74
    bridge_min_selected_gap_sec: float = 0.5
    bridge_min_vocal_activity_overlap_ratio: float = 0.6


class RuleBasedMelodySelector:
    def __init__(self, config: MelodySelectionConfig | None = None) -> None:
        self.config = config or MelodySelectionConfig()
        self.postprocessor = PhraseAwarePostprocessor(self._postprocess_config())

    def select(
        self,
        *,
        note_candidates: dict[str, Any] | None,
        pitch_contours: dict[str, Any] | None = None,
        vocal_activity: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        candidates, input_source = self._candidate_items(note_candidates, pitch_contours)
        if not candidates:
            return None
        if _is_note_candidate_set_v2(note_candidates):
            self._validate_v2_candidate_input(candidates, input_source=input_source)

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
        bridge_result = self._bridge_from_contours(
            raw_candidates=self._raw_candidate_items(note_candidates),
            selected=selected,
            pitch_contours=pitch_contours,
            vocal_activity=vocal_activity,
        )
        selected.extend(bridge_result["accepted_candidates"])
        rejected.extend(bridge_result["rejected_candidates"])
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
            "schema_version": "selected_melody_v2",
            "lineage_contract": {
                "stage": "MelodySelection",
                "input_stage": "NoteCandidateSet",
                "required_selected_fields": [
                    "candidate_id",
                    "source_candidate_id",
                    "source_candidate_ids",
                    "source_contour_ids",
                    "source_f0_frame_range",
                ],
            },
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
                "bridge_accepted_count": bridge_result["accepted_count"],
                "bridge_candidate_count": bridge_result["candidate_count"],
            },
            "bridge": bridge_result["summary"],
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
                "post_f0_contour_bridge_enabled": self._contour_bridge_enabled(),
                "bridge_min_confidence": self.config.bridge_min_confidence,
                "bridge_min_voiced_ratio": self.config.bridge_min_voiced_ratio,
                "bridge_min_duration_sec": self.config.bridge_min_duration_sec,
                "bridge_max_duration_sec": self.config.bridge_max_duration_sec,
                "bridge_low_confidence_long_contour_sec": self.config.bridge_low_confidence_long_contour_sec,
                "bridge_high_confidence_floor": self.config.bridge_high_confidence_floor,
                "bridge_min_selected_gap_sec": self.config.bridge_min_selected_gap_sec,
                "bridge_min_vocal_activity_overlap_ratio": self.config.bridge_min_vocal_activity_overlap_ratio,
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
        if _is_note_candidate_set_v2(note_candidates):
            return [], "note_candidate_set_v2.notes_empty"
        contours = pitch_contours.get("contours") if isinstance(pitch_contours, dict) else None
        if isinstance(contours, list):
            return [self._candidate_from_contour(contour, index) for index, contour in enumerate(contours, start=1) if isinstance(contour, dict)], "pitch_contours.contours_legacy"
        return [], "none"

    def _raw_candidate_items(self, note_candidates: dict[str, Any] | None) -> list[dict[str, Any]]:
        raw_notes = _extract_raw_candidate_notes(note_candidates)
        return [self._normalize_candidate(note, index) for index, note in enumerate(raw_notes, start=1)]

    @staticmethod
    def _validate_v2_candidate_input(candidates: list[dict[str, Any]], *, input_source: str) -> None:
        if input_source != "melody_candidates.notes":
            raise RuntimeError(f"melody_selection_requires_note_candidate_set_v2_notes:input_source={input_source}")
        violations: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            candidate_id = str(candidate.get("candidate_id") or f"#{index}")
            if not candidate.get("source_candidate_id") and not candidate.get("candidate_id"):
                violations.append(f"missing_source_candidate_id:{candidate_id}")
            if not candidate.get("source_candidate_ids"):
                violations.append(f"missing_source_candidate_ids:{candidate_id}")
            if not candidate.get("source_contour_ids"):
                violations.append(f"missing_source_contour_ids:{candidate_id}")
            if not candidate.get("source_f0_frame_range"):
                violations.append(f"missing_source_f0_frame_range:{candidate_id}")
        if violations:
            raise RuntimeError("melody_selection_lineage_contract_failed:" + ";".join(violations))

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
        normalized = {
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
            "source_f0_frame_range": dict(note.get("source_f0_frame_range") or {}),
            "reason_codes": _unique([str(item) for item in note.get("reason_codes") or []]),
        }
        if note.get("source_candidate_id") is not None and not normalized["source_candidate_ids"]:
            normalized["source_candidate_ids"] = [str(note.get("source_candidate_id"))]
        if note.get("candidate_origin") is not None:
            normalized["candidate_origin"] = str(note.get("candidate_origin"))
        if isinstance(note.get("contour_bridge_evidence"), dict):
            normalized["contour_bridge_evidence"] = dict(note["contour_bridge_evidence"])
        if "contour_bridge_guard_reason_codes" in note:
            normalized["contour_bridge_guard_reason_codes"] = list(note.get("contour_bridge_guard_reason_codes") or [])
        if isinstance(note.get("segmentation_evidence"), dict):
            normalized["segmentation_evidence"] = dict(note["segmentation_evidence"])
        return normalized

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

    def _bridge_from_contours(
        self,
        *,
        raw_candidates: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        pitch_contours: dict[str, Any] | None,
        vocal_activity: dict[str, Any] | None,
    ) -> dict[str, Any]:
        contours = pitch_contours.get("contours") if isinstance(pitch_contours, dict) else None
        summary = {
            "version": "post_f0_contour_bridge_v1",
            "enabled": self._contour_bridge_enabled(),
            "candidate_count": len(contours) if isinstance(contours, list) else 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "guard_reason_counts": {},
            "accepted_candidates": [],
            "rejected_candidates": [],
        }
        if not self._contour_bridge_enabled() or not isinstance(contours, list) or not raw_candidates:
            return {"accepted_candidates": [], "rejected_candidates": [], "candidate_count": summary["candidate_count"], "accepted_count": 0, "summary": summary}

        selected_gaps = self._selected_gaps(selected)
        vocal_segments = _vocal_activity_segments(vocal_activity)
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        guard_counts: Counter[str] = Counter()
        for index, contour in enumerate(contours, start=1):
            if not isinstance(contour, dict):
                continue
            span_candidates = self._bridge_candidate_spans(contour, selected_gaps)
            if not span_candidates:
                span_candidates = [None]
            for span in span_candidates:
                candidate = self._bridge_candidate_from_contour(contour, index, span=span)
                evidence = self._bridge_evidence(
                    candidate=candidate,
                    contour=contour,
                    selected=selected,
                    raw_candidates=raw_candidates,
                    selected_gaps=selected_gaps,
                    vocal_segments=vocal_segments,
                )
                guard_reasons = self._bridge_guard_reasons(candidate, evidence, vocal_segments_available=bool(vocal_segments))
                candidate["bridge_evidence"] = evidence
                candidate["bridge_guard_reason_codes"] = guard_reasons
                if guard_reasons:
                    rejected_item = self._rejected(candidate, guard_reasons)
                    rejected_item["bridge_evidence"] = evidence
                    rejected_item["bridge_guard_reason_codes"] = guard_reasons
                    rejected.append(rejected_item)
                    for reason in guard_reasons:
                        guard_counts[reason] += 1
                    continue
                accepted_candidate = self._selected(candidate)
                accepted_candidate["bridge_evidence"] = evidence
                accepted.append(accepted_candidate)
                guard_counts[BRIDGE_CONFIDENCE_GUARDED] += 1

        summary["accepted_count"] = len(accepted)
        summary["rejected_count"] = len(rejected)
        summary["guard_reason_counts"] = dict(sorted(guard_counts.items()))
        summary["accepted_candidates"] = [self._bridge_summary_item(item) for item in accepted]
        summary["rejected_candidates"] = [self._bridge_summary_item(item) for item in rejected]
        return {
            "accepted_candidates": accepted,
            "rejected_candidates": rejected,
            "candidate_count": summary["candidate_count"],
            "accepted_count": len(accepted),
            "summary": summary,
        }

    def _bridge_candidate_from_contour(
        self,
        contour: dict[str, Any],
        index: int,
        *,
        span: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = self._candidate_from_contour(contour, index)
        base_id = candidate["candidate_id"]
        if isinstance(span, dict):
            start = float(span["start_time_sec"])
            end = float(span["end_time_sec"])
            candidate["candidate_id"] = f"post_f0_bridge:{base_id}:gap_{span['gap_index']:05d}"
            candidate["start_time_sec"] = start
            candidate["end_time_sec"] = end
            candidate["duration_sec"] = max(0.0, end - start)
            candidate["bridge_gap_index"] = int(span["gap_index"])
        else:
            candidate["candidate_id"] = f"post_f0_bridge:{base_id}"
        candidate["reason_codes"] = _unique(
            list(candidate.get("reason_codes") or [])
            + [POST_F0_CONTOUR_BRIDGE, BRIDGE_FROM_VOICED_CONTOUR, BRIDGE_CONFIDENCE_GUARDED]
        )
        candidate["immutable_post_f0_bridge"] = True
        return candidate

    def _bridge_candidate_spans(self, contour: dict[str, Any], selected_gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contour_start = _safe_float(_first(contour, "start_time_sec", "start_time", "start"))
        contour_end = _safe_float(_first(contour, "end_time_sec", "end_time", "end"))
        if contour_start is None or contour_end is None or contour_end <= contour_start:
            return []
        spans: list[dict[str, Any]] = []
        for gap_index, gap in enumerate(selected_gaps, start=1):
            if float(gap.get("duration_sec") or 0.0) < float(self.config.bridge_min_selected_gap_sec):
                continue
            start = max(float(contour_start), _record_start(gap))
            end = min(float(contour_end), _record_end(gap))
            if end - start < float(self.config.bridge_min_duration_sec):
                continue
            spans.append(
                {
                    "gap_index": gap_index,
                    "start_time_sec": round(start, 6),
                    "end_time_sec": round(end, 6),
                    "duration_sec": round(end - start, 6),
                }
            )
        return spans

    def _bridge_evidence(
        self,
        *,
        candidate: dict[str, Any],
        contour: dict[str, Any],
        selected: list[dict[str, Any]],
        raw_candidates: list[dict[str, Any]],
        selected_gaps: list[dict[str, Any]],
        vocal_segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        start = float(candidate["start_time_sec"])
        end = float(candidate["end_time_sec"])
        selected_overlap = _max_overlap_duration(selected, start, end)
        raw_overlap = _max_overlap_duration(raw_candidates, start, end)
        nearest_gap = _nearest_gap(selected_gaps, start, end)
        vocal_overlap = _total_overlap_duration(vocal_segments, start, end)
        duration = max(0.0, end - start)
        contour_start = _safe_float(_first(contour, "start_time_sec", "start_time", "start"))
        contour_end = _safe_float(_first(contour, "end_time_sec", "end_time", "end"))
        nearest_gap_overlap = (
            _overlap_seconds(start, end, _record_start(nearest_gap), _record_end(nearest_gap))
            if isinstance(nearest_gap, dict)
            else 0.0
        )
        return {
            "source_contour_id": str(contour.get("id") or candidate.get("source_contour_ids", [None])[0] or candidate["candidate_id"]),
            "source_start_time_sec": round(float(contour_start), 6) if contour_start is not None else round(start, 6),
            "source_end_time_sec": round(float(contour_end), 6) if contour_end is not None else round(end, 6),
            "bridge_start_time_sec": round(start, 6),
            "bridge_end_time_sec": round(end, 6),
            "duration_sec": round(duration, 6),
            "confidence": round(float(candidate.get("confidence") or 0.0), 6),
            "voiced_ratio": _round_optional(candidate.get("voiced_ratio")),
            "stability": _round_optional(candidate.get("stability")),
            "pitch_center_midi": _round_optional(candidate.get("pitch_center_midi")),
            "nearest_selected_gap": nearest_gap,
            "nearest_selected_gap_overlap_duration_sec": round(nearest_gap_overlap, 6),
            "selected_overlap_duration_sec": round(selected_overlap, 6),
            "raw_candidate_overlap_duration_sec": round(raw_overlap, 6),
            "vocal_activity_overlap_ratio": round(vocal_overlap / duration, 6) if duration > 0 else 0.0,
            "vocal_activity_available": bool(vocal_segments),
            "has_glide": bool(contour.get("has_glide")),
            "has_vibrato": bool(contour.get("has_vibrato")),
            "source_contour_reason_codes": list(contour.get("reason_codes") or []),
        }

    def _bridge_guard_reasons(
        self,
        candidate: dict[str, Any],
        evidence: dict[str, Any],
        *,
        vocal_segments_available: bool,
    ) -> list[str]:
        reasons = self._base_reasons(candidate)
        duration = float(candidate.get("duration_sec") or 0.0)
        if duration < float(self.config.bridge_min_duration_sec):
            reasons.append(TOO_SHORT)
        if duration > float(self.config.bridge_max_duration_sec):
            reasons.append(TOO_UNSTABLE)
        confidence = float(candidate.get("confidence") or 0.0)
        if confidence < float(self.config.bridge_min_confidence):
            reasons.append(LOW_CONFIDENCE)
        if (
            duration > float(self.config.bridge_low_confidence_long_contour_sec)
            and confidence < float(self.config.bridge_high_confidence_floor)
        ):
            reasons.append(BRIDGE_LOW_CONFIDENCE_LONG_CONTOUR)
        voiced_ratio = candidate.get("voiced_ratio")
        if voiced_ratio is None or float(voiced_ratio) < float(self.config.bridge_min_voiced_ratio):
            reasons.append(LOW_VOICED_RATIO)
        nearest_gap = evidence.get("nearest_selected_gap") if isinstance(evidence.get("nearest_selected_gap"), dict) else None
        nearest_gap_overlap = float(evidence.get("nearest_selected_gap_overlap_duration_sec") or 0.0)
        if (
            not nearest_gap
            or float(nearest_gap.get("duration_sec") or 0.0) < float(self.config.bridge_min_selected_gap_sec)
            or nearest_gap_overlap < float(self.config.bridge_min_duration_sec)
        ):
            reasons.append(BRIDGE_NO_SELECTED_GAP)
        if float(evidence.get("selected_overlap_duration_sec") or 0.0) > 0.0:
            reasons.append(BRIDGE_OVERLAPS_SELECTED_NOTE)
        if float(evidence.get("raw_candidate_overlap_duration_sec") or 0.0) > 0.0:
            reasons.append(BRIDGE_OVERLAPS_RAW_CANDIDATE)
        if vocal_segments_available and float(evidence.get("vocal_activity_overlap_ratio") or 0.0) < float(self.config.bridge_min_vocal_activity_overlap_ratio):
            reasons.append(BRIDGE_VOCAL_ACTIVITY_UNSUPPORTED)
        reasons = _unique(reasons)
        hard_reasons = [reason for reason in reasons if reason != TOO_UNSTABLE]
        if TOO_UNSTABLE in reasons and not hard_reasons:
            candidate["reason_codes"] = _unique(
                list(candidate.get("reason_codes") or []) + [BRIDGE_UNSTABLE_CONTOUR_GUARDED]
            )
            return []
        return reasons

    def _selected_gaps(self, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(selected, key=lambda item: (float(item["start_time_sec"]), float(item["end_time_sec"])))
        gaps: list[dict[str, Any]] = []
        for left, right in zip(ordered, ordered[1:]):
            start = float(left["end_time_sec"])
            end = float(right["start_time_sec"])
            if end <= start:
                continue
            gaps.append(
                {
                    "start_time_sec": round(start, 6),
                    "end_time_sec": round(end, 6),
                    "duration_sec": round(end - start, 6),
                    "left_candidate_id": left.get("candidate_id"),
                    "right_candidate_id": right.get("candidate_id"),
                }
            )
        return gaps

    @staticmethod
    def _bridge_summary_item(candidate: dict[str, Any]) -> dict[str, Any]:
        evidence = candidate.get("bridge_evidence") if isinstance(candidate.get("bridge_evidence"), dict) else {}
        return {
            "candidate_id": candidate.get("candidate_id"),
            "start_time_sec": candidate.get("start_time_sec"),
            "end_time_sec": candidate.get("end_time_sec"),
            "pitch_center_midi": candidate.get("pitch_center_midi"),
            "confidence": candidate.get("confidence"),
            "reason_codes": list(candidate.get("reason_codes") or []),
            "bridge_guard_reason_codes": list(candidate.get("bridge_guard_reason_codes") or []),
            "evidence": evidence,
        }

    def _contour_bridge_enabled(self) -> bool:
        return self._postprocess_profile() == "conservative" and bool(self.config.post_f0_contour_bridge_enabled)

    @staticmethod
    def _selected(candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(candidate["candidate_id"])
        source_candidate_ids = list(candidate.get("source_candidate_ids") or [])
        if candidate_id not in source_candidate_ids:
            source_candidate_ids = [candidate_id] + source_candidate_ids
        selected = {
            "candidate_id": candidate_id,
            "source_candidate_id": candidate_id,
            "start_time_sec": round(float(candidate["start_time_sec"]), 6),
            "end_time_sec": round(float(candidate["end_time_sec"]), 6),
            "duration_sec": round(float(candidate["duration_sec"]), 6),
            "pitch_center_midi": round(float(candidate["pitch_center_midi"]), 6) if candidate.get("pitch_center_midi") is not None else None,
            "confidence": round(float(candidate["confidence"]), 6),
            "source_contour_ids": list(candidate.get("source_contour_ids") or []),
            "source_candidate_ids": _unique(source_candidate_ids),
            "source_f0_frame_range": dict(candidate.get("source_f0_frame_range") or {}),
            "reason_codes": list(candidate.get("reason_codes") or []),
        }
        if isinstance(candidate.get("bridge_evidence"), dict):
            selected["bridge_evidence"] = dict(candidate["bridge_evidence"])
        if "bridge_guard_reason_codes" in candidate:
            selected["bridge_guard_reason_codes"] = list(candidate.get("bridge_guard_reason_codes") or [])
        if isinstance(candidate.get("contour_bridge_evidence"), dict):
            selected["contour_bridge_evidence"] = dict(candidate["contour_bridge_evidence"])
        if "contour_bridge_guard_reason_codes" in candidate:
            selected["contour_bridge_guard_reason_codes"] = list(candidate.get("contour_bridge_guard_reason_codes") or [])
        if isinstance(candidate.get("segmentation_evidence"), dict):
            selected["segmentation_evidence"] = dict(candidate["segmentation_evidence"])
        if candidate.get("candidate_origin") is not None:
            selected["candidate_origin"] = candidate.get("candidate_origin")
        return selected

    @staticmethod
    def _selected_from_postprocessed(candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(candidate["candidate_id"])
        source_candidate_ids = list(candidate.get("source_candidate_ids") or [])
        source_candidate_id = str(candidate.get("source_candidate_id") or candidate_id)
        if source_candidate_id not in source_candidate_ids:
            source_candidate_ids = [source_candidate_id] + source_candidate_ids
        if candidate_id not in source_candidate_ids:
            source_candidate_ids = [candidate_id] + source_candidate_ids
        selected = {
            "candidate_id": candidate_id,
            "source_candidate_id": source_candidate_id,
            "start_time_sec": round(float(candidate["start_time_sec"]), 6),
            "end_time_sec": round(float(candidate["end_time_sec"]), 6),
            "duration_sec": round(max(0.0, float(candidate["end_time_sec"]) - float(candidate["start_time_sec"])), 6),
            "pitch_center_midi": round(float(candidate["pitch_center_midi"]), 6) if candidate.get("pitch_center_midi") is not None else None,
            "confidence": round(float(candidate["confidence"]), 6),
            "source_contour_ids": list(candidate.get("source_contour_ids") or []),
            "source_candidate_ids": _unique(source_candidate_ids),
            "source_f0_frame_range": dict(candidate.get("source_f0_frame_range") or {}),
            "reason_codes": list(candidate.get("reason_codes") or []),
        }
        if isinstance(candidate.get("bridge_evidence"), dict):
            selected["bridge_evidence"] = dict(candidate["bridge_evidence"])
        if "bridge_guard_reason_codes" in candidate:
            selected["bridge_guard_reason_codes"] = list(candidate.get("bridge_guard_reason_codes") or [])
        if isinstance(candidate.get("contour_bridge_evidence"), dict):
            selected["contour_bridge_evidence"] = dict(candidate["contour_bridge_evidence"])
        if "contour_bridge_guard_reason_codes" in candidate:
            selected["contour_bridge_guard_reason_codes"] = list(candidate.get("contour_bridge_guard_reason_codes") or [])
        if isinstance(candidate.get("segmentation_evidence"), dict):
            selected["segmentation_evidence"] = dict(candidate["segmentation_evidence"])
        if candidate.get("candidate_origin") is not None:
            selected["candidate_origin"] = candidate.get("candidate_origin")
        return selected

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
        rejected = {
            "candidate_id": candidate["candidate_id"],
            "start_time_sec": round(float(candidate["start_time_sec"]), 6),
            "end_time_sec": round(float(candidate["end_time_sec"]), 6),
            "pitch_center_midi": round(float(pitch_center), 6) if pitch_center is not None else None,
            "confidence": round(float(candidate["confidence"]), 6),
            "reason_codes": reason_codes,
        }
        if isinstance(candidate.get("segmentation_evidence"), dict):
            rejected["segmentation_evidence"] = dict(candidate["segmentation_evidence"])
        return rejected


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
                "source_contour_ids": item.get("source_contour_ids") or [],
                "source_f0_frame_range": item.get("source_f0_frame_range") or {},
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
    if _is_note_candidate_set_v2(note_candidates):
        if isinstance(melody, dict):
            notes = melody.get("notes") if isinstance(melody.get("notes"), list) else None
            if notes:
                return [note for note in notes if isinstance(note, dict)], "melody_candidates.notes"
        return [], "melody_candidates.notes_empty"
    if prefer_preselected_notes:
        bridge_notes = _bridge_raw_candidate_notes(containers)
        for source, container in containers:
            if not isinstance(container, dict):
                continue
            notes = container.get("selected_notes") if isinstance(container.get("selected_notes"), list) else None
            if notes:
                selected = [note for note in notes if isinstance(note, dict)]
                if bridge_notes:
                    return _merge_note_records(selected, bridge_notes), f"{source}.selected_notes_preselected+contour_bridge_raw_notes"
                return selected, f"{source}.selected_notes_preselected"
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


def _bridge_raw_candidate_notes(containers: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _source, container in containers:
        if not isinstance(container, dict):
            continue
        notes = container.get("notes") if isinstance(container.get("notes"), list) else None
        if not notes:
            continue
        for note in notes:
            if not isinstance(note, dict):
                continue
            reasons = [str(item) for item in note.get("reason_codes") or []]
            if CONTOUR_TO_CANDIDATE_BRIDGE not in reasons and BRIDGE_FROM_F0_CONTOUR not in reasons:
                continue
            key = str(note.get("candidate_id") or note.get("id") or f"{note.get('pitch')}:{note.get('start_time')}:{note.get('end_time')}")
            if key in seen:
                continue
            seen.add(key)
            result.append(note)
    return result


def _merge_note_records(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(primary)
    seen = {
        str(note.get("candidate_id") or note.get("id") or f"{note.get('pitch')}:{note.get('start_time')}:{note.get('end_time')}")
        for note in merged
    }
    for note in extra:
        key = str(note.get("candidate_id") or note.get("id") or f"{note.get('pitch')}:{note.get('start_time')}:{note.get('end_time')}")
        if key in seen:
            continue
        seen.add(key)
        merged.append(note)
    return merged


def _extract_raw_candidate_notes(note_candidates: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(note_candidates, dict):
        return []
    melody = note_candidates.get("melody_candidates")
    for container in (melody, note_candidates):
        if not isinstance(container, dict):
            continue
        notes = container.get("notes") if isinstance(container.get("notes"), list) else None
        if notes:
            return [note for note in notes if isinstance(note, dict)]
    return []


def _is_note_candidate_set_v2(note_candidates: dict[str, Any] | None) -> bool:
    if not isinstance(note_candidates, dict):
        return False
    if str(note_candidates.get("schema_version") or "") == "note_candidate_set_v2":
        return True
    melody = note_candidates.get("melody_candidates")
    return isinstance(melody, dict) and str(melody.get("schema_version") or "") == "note_candidate_set_v2"


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



def _overlap_seconds(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    return max(0.0, min(float(left_end), float(right_end)) - max(float(left_start), float(right_start)))


def _total_overlap_duration(records: list[dict[str, Any]], start: float, end: float) -> float:
    return sum(_overlap_seconds(_record_start(record), _record_end(record), start, end) for record in records)


def _max_overlap_duration(records: list[dict[str, Any]], start: float, end: float) -> float:
    overlaps = [_overlap_seconds(_record_start(record), _record_end(record), start, end) for record in records]
    return max(overlaps) if overlaps else 0.0


def _nearest_gap(gaps: list[dict[str, Any]], start: float, end: float) -> dict[str, Any] | None:
    if not gaps:
        return None
    midpoint = (float(start) + float(end)) / 2.0
    ranked = sorted(
        gaps,
        key=lambda gap: (
            0 if _record_start(gap) <= midpoint <= _record_end(gap) else 1,
            abs(((_record_start(gap) + _record_end(gap)) / 2.0) - midpoint),
        ),
    )
    gap = ranked[0]
    return {
        "start_time_sec": round(_record_start(gap), 6),
        "end_time_sec": round(_record_end(gap), 6),
        "duration_sec": round(max(0.0, _record_end(gap) - _record_start(gap)), 6),
        "left_candidate_id": gap.get("left_candidate_id"),
        "right_candidate_id": gap.get("right_candidate_id"),
    }


def _vocal_activity_segments(vocal_activity: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(vocal_activity, dict):
        return []
    items = vocal_activity.get("segments")
    if not isinstance(items, list):
        return []
    segments: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        state = str(_first(item, "state", "label", "activity") or "").strip().lower()
        if state not in {"vocal", "active", "singing", "voiced"}:
            continue
        start = _safe_float(_first(item, "start_time_sec", "start_time", "start_sec", "start"))
        end = _safe_float(_first(item, "end_time_sec", "end_time", "end_sec", "end"))
        if start is None or end is None or end <= start:
            continue
        segments.append({"start_time_sec": float(start), "end_time_sec": float(end), "state": state})
    return segments


def _record_start(record: dict[str, Any]) -> float:
    return float(_safe_float(_first(record, "start_time_sec", "start_time", "start_sec", "start")) or 0.0)


def _record_end(record: dict[str, Any]) -> float:
    start = _record_start(record)
    end = _safe_float(_first(record, "end_time_sec", "end_time", "end_sec", "end"))
    if end is None:
        duration = _safe_float(_first(record, "duration_sec", "duration")) or 0.0
        end = start + duration
    return float(end)


def _round_optional(value: Any) -> float | None:
    parsed = _safe_float(value)
    return round(parsed, 6) if parsed is not None else None

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
