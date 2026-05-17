from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from statistics import median, pstdev
from typing import Any

from .pitch_contours import PitchContourBuilder
from .reason_codes import (
    BRIDGE_FROM_F0_CONTOUR,
    BRIDGE_OVERLAPS_RAW_CANDIDATE,
    CONTOUR_SEGMENTATION_ALL_SEGMENTS_REJECTED,
    CONTOUR_SEGMENTATION_BRIDGE,
    CONTOUR_SEGMENTATION_NO_STABLE_SUBSEGMENT,
    LOW_CONFIDENCE,
    LOW_VOICED_RATIO,
    OUTSIDE_VOCAL_RANGE,
    SUSPECTED_GLIDE,
    SUSPECTED_VIBRATO,
    TOO_SHORT,
    TOO_UNSTABLE,
    UNCERTAIN,
)


@dataclass(frozen=True)
class NoteCandidateBuilderConfig:
    min_confidence: float = 0.58
    min_voiced_ratio: float = 0.72
    min_duration_sec: float = 0.04
    min_stability: float = 0.60
    max_pitch_range_semitones: float = 2.5
    max_raw_overlap_ratio: float = 0.55
    vocal_min_midi: float = 48.0
    vocal_max_midi: float = 84.0
    frame_match_tolerance_sec: float = 0.02
    segmentation_enabled: bool = True
    segmentation_min_source_duration_sec: float = 0.20
    segmentation_min_subsegment_duration_sec: float = 0.12
    segmentation_max_subsegment_duration_sec: float = 1.25
    segmentation_max_pitch_range_semitones: float = 1.00
    segmentation_max_pitch_stddev_semitones: float = 0.60
    segmentation_max_frame_gap_sec: float = 0.04
    segmentation_context_extension_sec: float = 0.35


class NoteCandidateBuilder:
    VERSION = "note_candidate_builder_v1"
    SCHEMA_VERSION = "note_candidate_set_v2"

    def __init__(self, config: NoteCandidateBuilderConfig | None = None) -> None:
        self.config = config or NoteCandidateBuilderConfig()
        self._contour_builder = PitchContourBuilder()

    def build(
        self,
        *,
        f0_track: dict[str, Any] | None,
        pitch_contours: dict[str, Any] | None,
        raw_candidates: Any = None,
    ) -> dict[str, Any]:
        normalized_frames = self._normalize_f0_frames(f0_track)
        contour_payload = self._resolve_pitch_contours(f0_track=f0_track, pitch_contours=pitch_contours)
        normalized_contours = self._normalize_contours(
            contour_payload=contour_payload,
            frames=normalized_frames,
            f0_track=f0_track,
        )
        raw_notes = self._normalize_raw_candidates(
            raw_candidates=raw_candidates,
            frames=normalized_frames,
            contours=normalized_contours,
            f0_track=f0_track,
        )

        accepted_notes = list(raw_notes)
        rejected_candidates: list[dict[str, Any]] = []
        rejection_reason_counts: Counter[str] = Counter()
        segmentation_counts: Counter[str] = Counter()

        for contour in normalized_contours:
            candidate = self._build_candidate_from_contour(
                contour=contour,
                frames=normalized_frames,
                source_backend=self._source_backend(f0_track=f0_track, contour_payload=contour_payload),
            )
            if candidate is None:
                continue

            rejection_reasons = self._contour_rejection_reasons(candidate=candidate, accepted_notes=accepted_notes)
            if rejection_reasons:
                segmented_notes = self._accepted_segment_candidates_from_contour(
                    contour=contour,
                    frames=normalized_frames,
                    source_backend=self._source_backend(f0_track=f0_track, contour_payload=contour_payload),
                    accepted_notes=accepted_notes,
                    rejection_reasons=rejection_reasons,
                    segmentation_counts=segmentation_counts,
                )
                if segmented_notes:
                    accepted_notes.extend(segmented_notes)
                    continue
                rejected = self._rejected_candidate_payload(candidate=candidate, rejection_reasons=rejection_reasons)
                rejected_candidates.append(rejected)
                for reason_code in rejection_reasons:
                    rejection_reason_counts[reason_code] += 1
                continue

            accepted_notes.append(candidate)

        accepted_notes.sort(
            key=lambda item: (
                float(item.get("start_time") or 0.0),
                float(item.get("end_time") or 0.0),
                float(item.get("pitch_center_midi") or 0.0),
                str(item.get("candidate_id") or ""),
            )
        )

        candidate_origin_counts = Counter(str(note.get("candidate_origin") or "unknown") for note in accepted_notes)
        analysis_info = {
            "builder_version": self.VERSION,
            "source_backend": self._source_backend(f0_track=f0_track, contour_payload=contour_payload),
            "f0_frame_count": len(normalized_frames),
            "contour_count": len(normalized_contours),
            "raw_candidate_input_count": self._raw_candidate_input_count(raw_candidates),
            "accepted_candidate_count": len(accepted_notes),
            "rejected_candidate_count": len(rejected_candidates),
            "raw_candidates_empty": len(raw_notes) == 0,
            "candidate_origin_counts": dict(sorted(candidate_origin_counts.items())),
            "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
            "rejected_candidates": rejected_candidates,
            "config": self._config_metadata(),
        }
        if segmentation_counts:
            analysis_info["segmentation_counts"] = dict(sorted(segmentation_counts.items()))

        melody_analysis = dict(analysis_info)
        melody_analysis["candidate_count"] = len(accepted_notes)
        melody_analysis["selected_count"] = 0

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "builder_version": self.VERSION,
            "lineage_contract": {
                "stage": "NoteCandidateSet",
                "input_stages": ["F0Track", "PitchContourSet"],
                "required_candidate_fields": [
                    "candidate_id",
                    "source_contour_ids",
                    "source_f0_frame_range",
                ],
            },
            "analysis_info": analysis_info,
            "melody_candidates": {
                "role": "melody_candidates",
                "schema_version": self.SCHEMA_VERSION,
                "source_stem": _as_optional_str((f0_track or {}).get("source_stem")),
                "input_audio_path": _as_optional_str((f0_track or {}).get("input_audio_path")),
                "notes": accepted_notes,
                "selected_notes": [],
                "raw_source": raw_candidates if isinstance(raw_candidates, dict) else {"notes": raw_candidates or []},
                "analysis_info": melody_analysis,
            },
        }

    def _config_metadata(self) -> dict[str, Any]:
        return {
            "min_confidence": float(self.config.min_confidence),
            "min_voiced_ratio": float(self.config.min_voiced_ratio),
            "min_duration_sec": float(self.config.min_duration_sec),
            "min_stability": float(self.config.min_stability),
            "max_pitch_range_semitones": float(self.config.max_pitch_range_semitones),
            "max_raw_overlap_ratio": float(self.config.max_raw_overlap_ratio),
            "vocal_min_midi": float(self.config.vocal_min_midi),
            "vocal_max_midi": float(self.config.vocal_max_midi),
            "frame_match_tolerance_sec": float(self.config.frame_match_tolerance_sec),
            "segmentation_enabled": bool(self.config.segmentation_enabled),
            "segmentation_min_source_duration_sec": float(self.config.segmentation_min_source_duration_sec),
            "segmentation_min_subsegment_duration_sec": float(self.config.segmentation_min_subsegment_duration_sec),
            "segmentation_max_subsegment_duration_sec": float(self.config.segmentation_max_subsegment_duration_sec),
            "segmentation_max_pitch_range_semitones": float(self.config.segmentation_max_pitch_range_semitones),
            "segmentation_max_pitch_stddev_semitones": float(self.config.segmentation_max_pitch_stddev_semitones),
            "segmentation_max_frame_gap_sec": float(self.config.segmentation_max_frame_gap_sec),
            "segmentation_context_extension_sec": float(self.config.segmentation_context_extension_sec),
        }

    def _resolve_pitch_contours(
        self,
        *,
        f0_track: dict[str, Any] | None,
        pitch_contours: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(pitch_contours, dict) and isinstance(pitch_contours.get("contours"), list):
            return pitch_contours
        derived = self._contour_builder.build(f0_track)
        if isinstance(derived, dict):
            return derived
        return {"version": "pitch_contours_v1", "contours": [], "summary": {}}

    def _normalize_f0_frames(self, f0_track: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(f0_track, dict):
            return []
        frames = f0_track.get("frames")
        if not isinstance(frames, list):
            return []

        normalized: list[dict[str, Any]] = []
        for default_index, raw_frame in enumerate(frames):
            if not isinstance(raw_frame, dict):
                continue
            time_sec = _safe_float(_first(raw_frame, "time_sec", "time"))
            if time_sec is None:
                continue
            pitch_midi = _extract_pitch_midi(raw_frame)
            confidence = _safe_float(raw_frame.get("confidence"))
            voiced = raw_frame.get("voiced")
            if voiced is None:
                voiced = pitch_midi is not None
            frame_index = _safe_int(_first(raw_frame, "frame_index", "index"))
            normalized.append(
                {
                    "frame_index": default_index if frame_index is None else frame_index,
                    "time_sec": round(float(time_sec), 6),
                    "pitch_midi": _round_optional(pitch_midi),
                    "confidence": _round_optional(confidence),
                    "voiced": bool(voiced),
                }
            )
        normalized.sort(key=lambda item: (float(item["time_sec"]), int(item["frame_index"])))
        return normalized

    def _normalize_contours(
        self,
        *,
        contour_payload: dict[str, Any],
        frames: list[dict[str, Any]],
        f0_track: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        contours = contour_payload.get("contours")
        if not isinstance(contours, list):
            return []

        normalized: list[dict[str, Any]] = []
        source_backend = self._source_backend(f0_track=f0_track, contour_payload=contour_payload)
        for index, raw_contour in enumerate(contours):
            if not isinstance(raw_contour, dict):
                continue
            start_time = _safe_float(_first(raw_contour, "start_time_sec", "start_time", "start"))
            end_time = _safe_float(_first(raw_contour, "end_time_sec", "end_time", "end"))
            duration = _safe_float(_first(raw_contour, "duration_sec", "duration"))
            if start_time is None:
                frame_samples = self._normalize_frame_samples(raw_contour.get("frame_samples"))
                if frame_samples:
                    start_time = frame_samples[0]["time_sec"]
            if end_time is None:
                frame_samples = self._normalize_frame_samples(raw_contour.get("frame_samples"))
                if frame_samples:
                    end_time = frame_samples[-1]["time_sec"]
                elif start_time is not None and duration is not None:
                    end_time = start_time + duration
            if start_time is None or end_time is None:
                continue
            source_frame_range = self._resolve_source_frame_range(
                frames=frames,
                start_time=start_time,
                end_time=end_time,
                frame_samples=raw_contour.get("frame_samples"),
            )
            range_frames = self._frames_in_range(frames=frames, frame_range=source_frame_range)
            frame_samples = self._normalize_frame_samples(raw_contour.get("frame_samples"))
            metrics_source = frame_samples if frame_samples else range_frames
            pitch_values = [float(item["pitch_midi"]) for item in metrics_source if _safe_float(item.get("pitch_midi")) is not None]
            confidence_values = [float(item["confidence"]) for item in metrics_source if _safe_float(item.get("confidence")) is not None]
            voiced_count = sum(1 for item in range_frames if bool(item.get("voiced")) and _safe_float(item.get("pitch_midi")) is not None)
            frame_count = max(len(range_frames), len(frame_samples), int(raw_contour.get("frame_count") or 0))
            pitch_center_midi = _safe_float(
                _first(raw_contour, "pitch_center_midi", "median_midi", "mean_midi", "pitch_midi")
            )
            if pitch_center_midi is None and pitch_values:
                pitch_center_midi = float(median(pitch_values))
            pitch_range = (max(pitch_values) - min(pitch_values)) if len(pitch_values) >= 2 else 0.0
            pitch_stddev = float(pstdev(pitch_values)) if len(pitch_values) >= 2 else 0.0
            stability = _safe_float(raw_contour.get("stability"))
            if stability is None:
                stability = _stability_from_pitch_range(pitch_range, self.config.max_pitch_range_semitones)
            mean_confidence = _safe_float(raw_contour.get("mean_confidence"))
            if mean_confidence is None and confidence_values:
                mean_confidence = sum(confidence_values) / len(confidence_values)
            voiced_ratio = _safe_float(raw_contour.get("voiced_ratio"))
            if voiced_ratio is None:
                voiced_ratio = voiced_count / max(1, frame_count)
            contour_id = _as_optional_str(raw_contour.get("id")) or self._stable_contour_id(
                source_backend=source_backend,
                start_time=start_time,
                end_time=end_time,
                pitch_center_midi=pitch_center_midi,
            )
            reason_codes = _unique_str_list(raw_contour.get("reason_codes"))
            normalized.append(
                {
                    "id": contour_id,
                    "start_time_sec": round(float(start_time), 6),
                    "end_time_sec": round(float(end_time), 6),
                    "duration_sec": round(max(0.0, float(end_time) - float(start_time)), 6),
                    "pitch_center_midi": _round_optional(pitch_center_midi),
                    "mean_confidence": _round_optional(mean_confidence),
                    "voiced_ratio": _round_optional(voiced_ratio),
                    "stability": _round_optional(stability),
                    "pitch_range_semitones": round(float(pitch_range), 6),
                    "pitch_stddev_semitones": round(float(pitch_stddev), 6),
                    "frame_count": frame_count,
                    "voiced_frame_count": voiced_count,
                    "reason_codes": reason_codes,
                    "has_glide": bool(raw_contour.get("has_glide")) or SUSPECTED_GLIDE in reason_codes,
                    "has_vibrato": bool(raw_contour.get("has_vibrato")) or SUSPECTED_VIBRATO in reason_codes,
                    "frame_samples": frame_samples,
                    "source_f0_frame_range": source_frame_range,
                }
            )
        return normalized

    def _normalize_raw_candidates(
        self,
        *,
        raw_candidates: Any,
        frames: list[dict[str, Any]],
        contours: list[dict[str, Any]],
        f0_track: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        items = self._extract_raw_note_items(raw_candidates)
        source_backend = self._source_backend(f0_track=f0_track, contour_payload=None)
        normalized: list[dict[str, Any]] = []
        for raw_note in items:
            if not isinstance(raw_note, dict):
                continue
            start_time = _safe_float(_first(raw_note, "start_time", "start_time_sec", "start"))
            end_time = _safe_float(_first(raw_note, "end_time", "end_time_sec", "end"))
            if start_time is None or end_time is None:
                continue
            pitch_center_midi = _extract_pitch_midi(raw_note)
            if pitch_center_midi is None:
                continue
            source_frame_range = self._resolve_source_frame_range(
                frames=frames,
                start_time=start_time,
                end_time=end_time,
                frame_samples=None,
            )
            range_frames = self._frames_in_range(frames=frames, frame_range=source_frame_range)
            contour_ids = _unique_str_list(raw_note.get("source_contour_ids"))
            if not contour_ids:
                contour_ids = self._matching_contour_ids(
                    start_time=start_time,
                    end_time=end_time,
                    contours=contours,
                )
            voiced_frame_count = sum(1 for frame in range_frames if bool(frame.get("voiced")) and _safe_float(frame.get("pitch_midi")) is not None)
            frame_count = len(range_frames)
            voiced_ratio = _safe_float(raw_note.get("voiced_ratio"))
            if voiced_ratio is None:
                voiced_ratio = voiced_frame_count / max(1, frame_count) if frame_count else 1.0
            stability = _safe_float(raw_note.get("stability"))
            if stability is None:
                matching_contours = [contour for contour in contours if contour["id"] in contour_ids]
                if matching_contours:
                    stability = max(_safe_float(contour.get("stability")) or 0.0 for contour in matching_contours)
            if stability is None:
                pitch_values = [
                    float(frame["pitch_midi"])
                    for frame in range_frames
                    if _safe_float(frame.get("pitch_midi")) is not None
                ]
                pitch_range = (max(pitch_values) - min(pitch_values)) if len(pitch_values) >= 2 else 0.0
                stability = _stability_from_pitch_range(pitch_range, self.config.max_pitch_range_semitones)
            confidence = _safe_float(raw_note.get("confidence"))
            if confidence is None:
                confidence_values = [
                    float(frame["confidence"])
                    for frame in range_frames
                    if _safe_float(frame.get("confidence")) is not None
                ]
                confidence = (sum(confidence_values) / len(confidence_values)) if confidence_values else 0.0
            candidate_origin = _as_optional_str(raw_note.get("candidate_origin")) or "raw_detector_candidate"
            candidate_id = self._stable_candidate_id(
                origin="raw",
                source_backend=source_backend,
                start_time=start_time,
                end_time=end_time,
                pitch_center_midi=pitch_center_midi,
                source_f0_frame_range=source_frame_range,
            )
            source_candidate_ids = _unique_str_list(raw_note.get("source_candidate_ids"))
            source_candidate_id = (
                _as_optional_str(raw_note.get("source_candidate_id"))
                or _as_optional_str(raw_note.get("candidate_id"))
                or candidate_id
            )
            source_candidate_ids = _unique_str_list(source_candidate_ids + [source_candidate_id, candidate_id])
            if not contour_ids:
                continue
            normalized.append(
                {
                    "candidate_id": candidate_id,
                    "stable_id": candidate_id,
                    "source_candidate_id": source_candidate_id,
                    "source_candidate_ids": source_candidate_ids,
                    "source_contour_ids": contour_ids,
                    "source_f0_frame_range": source_frame_range,
                    "candidate_origin": candidate_origin,
                    "pitch": _midi_to_note_name(pitch_center_midi),
                    "pitch_midi": _round_optional(pitch_center_midi),
                    "pitch_center_midi": _round_optional(pitch_center_midi),
                    "start_time": round(float(start_time), 6),
                    "end_time": round(float(end_time), 6),
                    "duration_sec": round(max(0.0, float(end_time) - float(start_time)), 6),
                    "confidence": _clamp01(confidence),
                    "voiced": bool(voiced_ratio >= self.config.min_voiced_ratio),
                    "voiced_ratio": _round_optional(voiced_ratio),
                    "stability": _round_optional(stability),
                    "reason_codes": _unique_str_list(raw_note.get("reason_codes")),
                    "segmentation_evidence": {
                        "builder_version": self.VERSION,
                        "strategy": "raw_candidate_passthrough",
                        "backend": source_backend,
                        "matched_contour_ids": contour_ids,
                        "frame_count": frame_count,
                        "voiced_frame_count": voiced_frame_count,
                    },
                }
            )
        return normalized

    def _extract_raw_note_items(self, raw_candidates: Any) -> list[dict[str, Any]]:
        if isinstance(raw_candidates, list):
            return [item for item in raw_candidates if isinstance(item, dict)]
        if not isinstance(raw_candidates, dict):
            return []
        melody_candidates = raw_candidates.get("melody_candidates")
        if isinstance(melody_candidates, dict) and isinstance(melody_candidates.get("notes"), list):
            return [item for item in melody_candidates.get("notes") if isinstance(item, dict)]
        notes = raw_candidates.get("notes")
        if isinstance(notes, list):
            return [item for item in notes if isinstance(item, dict)]
        return []

    def _build_candidate_from_contour(
        self,
        *,
        contour: dict[str, Any],
        frames: list[dict[str, Any]],
        source_backend: str,
    ) -> dict[str, Any] | None:
        pitch_center_midi = _safe_float(contour.get("pitch_center_midi"))
        start_time = _safe_float(contour.get("start_time_sec"))
        end_time = _safe_float(contour.get("end_time_sec"))
        if pitch_center_midi is None or start_time is None or end_time is None:
            return None
        source_frame_range = contour.get("source_f0_frame_range")
        if not isinstance(source_frame_range, dict):
            source_frame_range = self._resolve_source_frame_range(
                frames=frames,
                start_time=start_time,
                end_time=end_time,
                frame_samples=None,
            )
        frame_count = int(source_frame_range.get("frame_count") or contour.get("frame_count") or 0)
        voiced_frame_count = int(source_frame_range.get("voiced_frame_count") or contour.get("voiced_frame_count") or 0)
        candidate_id = self._stable_candidate_id(
            origin="contour",
            source_backend=source_backend,
            start_time=start_time,
            end_time=end_time,
            pitch_center_midi=pitch_center_midi,
            source_f0_frame_range=source_frame_range,
        )
        source_reason_codes = _unique_str_list(contour.get("reason_codes"))
        note_reason_codes = _unique_str_list(
            [BRIDGE_FROM_F0_CONTOUR]
            + [code for code in source_reason_codes if code not in {LOW_CONFIDENCE, LOW_VOICED_RATIO, TOO_SHORT, TOO_UNSTABLE, UNCERTAIN}]
        )
        return {
            "candidate_id": candidate_id,
            "stable_id": candidate_id,
            "source_candidate_id": candidate_id,
            "source_candidate_ids": [candidate_id],
            "source_contour_ids": [str(contour["id"])],
            "source_f0_frame_range": source_frame_range,
            "candidate_origin": "note_candidate_builder.contour_seed",
            "pitch": _midi_to_note_name(pitch_center_midi),
            "pitch_midi": _round_optional(pitch_center_midi),
            "pitch_center_midi": _round_optional(pitch_center_midi),
            "start_time": round(float(start_time), 6),
            "end_time": round(float(end_time), 6),
            "duration_sec": round(max(0.0, float(end_time) - float(start_time)), 6),
            "confidence": _clamp01(contour.get("mean_confidence")),
            "voiced": bool((_safe_float(contour.get("voiced_ratio")) or 0.0) >= self.config.min_voiced_ratio),
            "voiced_ratio": _round_optional(contour.get("voiced_ratio")),
            "stability": _round_optional(contour.get("stability")),
            "reason_codes": note_reason_codes,
            "segmentation_evidence": {
                "builder_version": self.VERSION,
                "strategy": "pitch_contour_seed",
                "backend": source_backend,
                "source_contour_id": str(contour["id"]),
                "frame_count": frame_count,
                "voiced_frame_count": voiced_frame_count,
                "pitch_range_semitones": _round_optional(contour.get("pitch_range_semitones")),
                "pitch_stddev_semitones": _round_optional(contour.get("pitch_stddev_semitones")),
                "source_reason_codes": source_reason_codes,
            },
        }

    def _contour_rejection_reasons(
        self,
        *,
        candidate: dict[str, Any],
        accepted_notes: list[dict[str, Any]],
    ) -> list[str]:
        rejection_reasons: list[str] = []
        confidence = _safe_float(candidate.get("confidence")) or 0.0
        voiced_ratio = _safe_float(candidate.get("voiced_ratio")) or 0.0
        duration = _safe_float(candidate.get("duration_sec")) or 0.0
        stability = _safe_float(candidate.get("stability")) or 0.0
        pitch_center = _safe_float(candidate.get("pitch_center_midi"))

        if confidence < self.config.min_confidence:
            rejection_reasons.append(LOW_CONFIDENCE)
        if voiced_ratio < self.config.min_voiced_ratio:
            rejection_reasons.append(LOW_VOICED_RATIO)
        if duration < self.config.min_duration_sec:
            rejection_reasons.append(TOO_SHORT)
        if stability < self.config.min_stability:
            rejection_reasons.append(TOO_UNSTABLE)
        segmentation_evidence = candidate.get("segmentation_evidence")
        if isinstance(segmentation_evidence, dict):
            pitch_range = _safe_float(segmentation_evidence.get("pitch_range_semitones")) or 0.0
            if pitch_range > self.config.max_pitch_range_semitones:
                rejection_reasons.append(TOO_UNSTABLE)
        if pitch_center is None or not (self.config.vocal_min_midi <= pitch_center <= self.config.vocal_max_midi):
            rejection_reasons.append(OUTSIDE_VOCAL_RANGE)
        if self._max_overlap_ratio(candidate=candidate, accepted_notes=accepted_notes) > self.config.max_raw_overlap_ratio:
            rejection_reasons.append(BRIDGE_OVERLAPS_RAW_CANDIDATE)
        if rejection_reasons:
            rejection_reasons.append(UNCERTAIN)
        return _unique_str_list(rejection_reasons)

    def _accepted_segment_candidates_from_contour(
        self,
        *,
        contour: dict[str, Any],
        frames: list[dict[str, Any]],
        source_backend: str,
        accepted_notes: list[dict[str, Any]],
        rejection_reasons: list[str],
        segmentation_counts: Counter[str],
    ) -> list[dict[str, Any]]:
        if not self.config.segmentation_enabled:
            return []
        if TOO_UNSTABLE not in rejection_reasons:
            return []
        source_duration = _safe_float(contour.get("duration_sec")) or 0.0
        if source_duration < float(self.config.segmentation_min_source_duration_sec):
            return []
        frame_samples = self._normalize_frame_samples(contour.get("frame_samples"))
        segment_frames = _stable_frame_segments(
            frame_samples,
            min_confidence=float(self.config.min_confidence),
            max_frame_gap_sec=float(self.config.segmentation_max_frame_gap_sec),
            max_pitch_range_semitones=float(self.config.segmentation_max_pitch_range_semitones),
        )
        if not segment_frames:
            segmentation_counts[CONTOUR_SEGMENTATION_NO_STABLE_SUBSEGMENT] += 1
            return []

        accepted_segment_items: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
        rejected_segment_reasons: Counter[str] = Counter()
        rejected_segment_count = 0
        for segment_index, segment in enumerate(segment_frames, start=1):
            candidate = self._build_candidate_from_segment(
                contour=contour,
                segment=segment,
                segment_index=segment_index,
                frames=frames,
                source_backend=source_backend,
            )
            if candidate is None:
                rejected_segment_count += 1
                rejected_segment_reasons[TOO_SHORT] += 1
                continue
            segment_rejections = self._contour_rejection_reasons(
                candidate=candidate,
                accepted_notes=accepted_notes + [item[1] for item in accepted_segment_items],
            )
            if segment_rejections:
                rejected_segment_count += 1
                for reason_code in segment_rejections:
                    rejected_segment_reasons[reason_code] += 1
                continue
            accepted_segment_items.append((segment, candidate))

        accepted_segments = self._extend_accepted_segment_candidates(
            contour=contour,
            accepted_segment_items=accepted_segment_items,
            frames=frames,
            source_backend=source_backend,
        )

        if accepted_segments:
            segmentation_counts[CONTOUR_SEGMENTATION_BRIDGE] += len(accepted_segments)
            if rejected_segment_count:
                segmentation_counts[CONTOUR_SEGMENTATION_ALL_SEGMENTS_REJECTED] += rejected_segment_count
                for reason_code, count in rejected_segment_reasons.items():
                    segmentation_counts[f"segment_rejected:{reason_code}"] += count
            return accepted_segments
        segmentation_counts[CONTOUR_SEGMENTATION_ALL_SEGMENTS_REJECTED] += max(1, rejected_segment_count)
        for reason_code, count in rejected_segment_reasons.items():
            segmentation_counts[f"segment_rejected:{reason_code}"] += count
        return []

    def _extend_accepted_segment_candidates(
        self,
        *,
        contour: dict[str, Any],
        accepted_segment_items: list[tuple[list[dict[str, Any]], dict[str, Any]]],
        frames: list[dict[str, Any]],
        source_backend: str,
    ) -> list[dict[str, Any]]:
        if not accepted_segment_items:
            return []
        accepted_segments = [segment for segment, _ in accepted_segment_items]
        extended_candidates: list[dict[str, Any]] = []
        for accepted_index, (segment, candidate) in enumerate(accepted_segment_items):
            extended_start_time, extended_end_time = _extended_segment_bounds(
                segment=segment,
                segment_index=accepted_index,
                segments=accepted_segments,
                contour=contour,
                max_extension_sec=float(self.config.segmentation_context_extension_sec),
            )
            stable_start_time = float(candidate["segmentation_evidence"].get("stable_start_time_sec") or candidate["start_time"])
            stable_end_time = float(candidate["segmentation_evidence"].get("stable_end_time_sec") or candidate["end_time"])
            if extended_end_time <= extended_start_time:
                extended_candidates.append(candidate)
                continue
            if abs(float(candidate["start_time"]) - extended_start_time) < 1e-9 and abs(float(candidate["end_time"]) - extended_end_time) < 1e-9:
                extended_candidates.append(candidate)
                continue
            source_frame_range = self._resolve_source_frame_range(
                frames=frames,
                start_time=extended_start_time,
                end_time=extended_end_time,
                frame_samples=segment,
            )
            candidate_id = self._stable_candidate_id(
                origin="contour_segment",
                source_backend=source_backend,
                start_time=extended_start_time,
                end_time=extended_end_time,
                pitch_center_midi=float(candidate["pitch_center_midi"]),
                source_f0_frame_range=source_frame_range,
            )
            extended = dict(candidate)
            extended["candidate_id"] = candidate_id
            extended["stable_id"] = candidate_id
            extended["source_candidate_id"] = candidate_id
            extended["source_candidate_ids"] = [candidate_id]
            extended["source_f0_frame_range"] = source_frame_range
            extended["start_time"] = round(float(extended_start_time), 6)
            extended["end_time"] = round(float(extended_end_time), 6)
            extended["duration_sec"] = round(max(0.0, float(extended_end_time) - float(extended_start_time)), 6)
            segmentation_evidence = dict(candidate.get("segmentation_evidence") or {})
            segmentation_evidence["frame_count"] = int(source_frame_range.get("frame_count") or segmentation_evidence.get("frame_count") or len(segment))
            segmentation_evidence["voiced_frame_count"] = int(
                source_frame_range.get("voiced_frame_count")
                or segmentation_evidence.get("voiced_frame_count")
                or len(segment)
            )
            segmentation_evidence["context_extension_sec"] = round(
                max(0.0, float(extended_end_time) - float(extended_start_time) - (stable_end_time - stable_start_time)),
                6,
            )
            extended["segmentation_evidence"] = segmentation_evidence
            extended_candidates.append(extended)
        return extended_candidates

    def _build_candidate_from_segment(
        self,
        *,
        contour: dict[str, Any],
        segment: list[dict[str, Any]],
        segment_index: int,
        frames: list[dict[str, Any]],
        source_backend: str,
        extended_start_time: float | None = None,
        extended_end_time: float | None = None,
    ) -> dict[str, Any] | None:
        if not segment:
            return None
        times = [float(item["time_sec"]) for item in segment if _safe_float(item.get("time_sec")) is not None]
        pitches = [float(item["pitch_midi"]) for item in segment if _safe_float(item.get("pitch_midi")) is not None]
        confidences = [float(item["confidence"]) for item in segment if _safe_float(item.get("confidence")) is not None]
        if not times or not pitches or not confidences:
            return None
        hop = _median_positive_delta(sorted(times))
        stable_start_time = min(times)
        stable_end_time = max(times) + hop
        stable_duration = max(0.0, stable_end_time - stable_start_time)
        if stable_duration < float(self.config.segmentation_min_subsegment_duration_sec):
            return None
        start_time = float(extended_start_time) if extended_start_time is not None else stable_start_time
        end_time = float(extended_end_time) if extended_end_time is not None else stable_end_time
        if end_time <= start_time:
            start_time = stable_start_time
            end_time = stable_end_time
        duration = max(0.0, end_time - start_time)
        if duration > float(self.config.segmentation_max_subsegment_duration_sec):
            return None
        pitch_range = max(pitches) - min(pitches) if len(pitches) >= 2 else 0.0
        pitch_stddev = float(pstdev(pitches)) if len(pitches) >= 2 else 0.0
        if pitch_stddev > float(self.config.segmentation_max_pitch_stddev_semitones):
            return None
        pitch_center_midi = float(median(pitches))
        source_frame_range = self._resolve_source_frame_range(
            frames=frames,
            start_time=start_time,
            end_time=end_time,
            frame_samples=segment,
        )
        candidate_id = self._stable_candidate_id(
            origin="contour_segment",
            source_backend=source_backend,
            start_time=start_time,
            end_time=end_time,
            pitch_center_midi=pitch_center_midi,
            source_f0_frame_range=source_frame_range,
        )
        source_contour_id = str(contour["id"])
        source_reason_codes = _unique_str_list(contour.get("reason_codes"))
        stability = _contour_stability_from_pitch_range(pitch_range)
        return {
            "candidate_id": candidate_id,
            "stable_id": candidate_id,
            "source_candidate_id": candidate_id,
            "source_candidate_ids": [candidate_id],
            "source_contour_ids": [source_contour_id],
            "source_f0_frame_range": source_frame_range,
            "candidate_origin": "note_candidate_builder.contour_segment",
            "pitch": _midi_to_note_name(pitch_center_midi),
            "pitch_midi": _round_optional(pitch_center_midi),
            "pitch_center_midi": _round_optional(pitch_center_midi),
            "start_time": round(float(start_time), 6),
            "end_time": round(float(end_time), 6),
            "duration_sec": round(float(duration), 6),
            "confidence": _clamp01(sum(confidences) / len(confidences)),
            "voiced": True,
            "voiced_ratio": 1.0,
            "stability": _round_optional(stability),
            "reason_codes": [BRIDGE_FROM_F0_CONTOUR, CONTOUR_SEGMENTATION_BRIDGE],
            "segmentation_evidence": {
                "builder_version": self.VERSION,
                "strategy": "pitch_contour_stable_subsegment",
                "backend": source_backend,
                "source_contour_id": source_contour_id,
                "source_contour_duration_sec": _round_optional(contour.get("duration_sec")),
                "segment_index": int(segment_index),
                "frame_count": int(source_frame_range.get("frame_count") or len(segment)),
                "voiced_frame_count": int(source_frame_range.get("voiced_frame_count") or len(segment)),
                "stable_start_time_sec": round(float(stable_start_time), 6),
                "stable_end_time_sec": round(float(stable_end_time), 6),
                "stable_duration_sec": round(float(stable_duration), 6),
                "context_extension_sec": round(float(duration - stable_duration), 6),
                "pitch_range_semitones": round(float(pitch_range), 6),
                "pitch_stddev_semitones": round(float(pitch_stddev), 6),
                "source_reason_codes": source_reason_codes,
            },
        }

    def _max_overlap_ratio(self, *, candidate: dict[str, Any], accepted_notes: list[dict[str, Any]]) -> float:
        start_time = float(candidate.get("start_time") or 0.0)
        end_time = float(candidate.get("end_time") or 0.0)
        duration = max(0.0, end_time - start_time)
        if duration <= 0.0:
            return 0.0
        overlaps = [
            _overlap_ratio(
                start_time=start_time,
                end_time=end_time,
                other_start=float(note.get("start_time") or 0.0),
                other_end=float(note.get("end_time") or 0.0),
            )
            for note in accepted_notes
        ]
        return max(overlaps, default=0.0)

    def _rejected_candidate_payload(
        self,
        *,
        candidate: dict[str, Any],
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("candidate_id"),
            "candidate_origin": candidate.get("candidate_origin"),
            "source_contour_ids": list(candidate.get("source_contour_ids") or []),
            "source_f0_frame_range": dict(candidate.get("source_f0_frame_range") or {}),
            "reason_codes": rejection_reasons,
            "confidence": candidate.get("confidence"),
            "voiced_ratio": candidate.get("voiced_ratio"),
            "stability": candidate.get("stability"),
            "segmentation_evidence": dict(candidate.get("segmentation_evidence") or {}),
        }

    def _matching_contour_ids(
        self,
        *,
        start_time: float,
        end_time: float,
        contours: list[dict[str, Any]],
    ) -> list[str]:
        matched: list[str] = []
        for contour in contours:
            overlap = _overlap_seconds(
                left_start=start_time,
                left_end=end_time,
                right_start=float(contour.get("start_time_sec") or 0.0),
                right_end=float(contour.get("end_time_sec") or 0.0),
            )
            if overlap > 0.0:
                matched.append(str(contour["id"]))
        return _unique_str_list(matched)

    def _resolve_source_frame_range(
        self,
        *,
        frames: list[dict[str, Any]],
        start_time: float,
        end_time: float,
        frame_samples: Any,
    ) -> dict[str, Any]:
        tolerance = max(0.0, float(self.config.frame_match_tolerance_sec))
        matched_times = [sample["time_sec"] for sample in self._normalize_frame_samples(frame_samples)]
        candidate_frames: list[dict[str, Any]] = []
        for frame in frames:
            time_sec = float(frame["time_sec"])
            in_time_window = (start_time - tolerance) <= time_sec <= (end_time + tolerance)
            if matched_times:
                in_time_window = in_time_window or any(abs(time_sec - matched) <= tolerance for matched in matched_times)
            if in_time_window:
                candidate_frames.append(frame)
        if not candidate_frames:
            return {
                "start_frame_index": None,
                "end_frame_index": None,
                "start_time_sec": round(float(start_time), 6),
                "end_time_sec": round(float(end_time), 6),
                "frame_count": 0,
                "voiced_frame_count": 0,
                "matched_by": "time_window",
            }
        start_frame_index = int(candidate_frames[0]["frame_index"])
        end_frame_index = int(candidate_frames[-1]["frame_index"])
        voiced_frame_count = sum(
            1
            for frame in candidate_frames
            if bool(frame.get("voiced")) and _safe_float(frame.get("pitch_midi")) is not None
        )
        return {
            "start_frame_index": start_frame_index,
            "end_frame_index": end_frame_index,
            "start_time_sec": round(float(candidate_frames[0]["time_sec"]), 6),
            "end_time_sec": round(float(candidate_frames[-1]["time_sec"]), 6),
            "frame_count": len(candidate_frames),
            "voiced_frame_count": voiced_frame_count,
            "matched_by": "frame_samples" if matched_times else "time_window",
        }

    @staticmethod
    def _frames_in_range(*, frames: list[dict[str, Any]], frame_range: dict[str, Any]) -> list[dict[str, Any]]:
        start_index = _safe_int(frame_range.get("start_frame_index"))
        end_index = _safe_int(frame_range.get("end_frame_index"))
        if start_index is None or end_index is None:
            return []
        return [
            frame
            for frame in frames
            if start_index <= int(frame["frame_index"]) <= end_index
        ]

    @staticmethod
    def _normalize_frame_samples(frame_samples: Any) -> list[dict[str, float]]:
        if not isinstance(frame_samples, list):
            return []
        normalized: list[dict[str, float]] = []
        for sample in frame_samples:
            if not isinstance(sample, dict):
                continue
            time_sec = _safe_float(_first(sample, "time_sec", "time"))
            pitch_midi = _safe_float(_first(sample, "pitch_midi", "midi_float", "midi"))
            confidence = _safe_float(sample.get("confidence"))
            if time_sec is None or pitch_midi is None:
                continue
            normalized.append(
                {
                    "time_sec": round(float(time_sec), 6),
                    "pitch_midi": round(float(pitch_midi), 6),
                    "confidence": 0.0 if confidence is None else round(float(confidence), 6),
                }
            )
        normalized.sort(key=lambda item: item["time_sec"])
        return normalized

    def _stable_candidate_id(
        self,
        *,
        origin: str,
        source_backend: str,
        start_time: float,
        end_time: float,
        pitch_center_midi: float,
        source_f0_frame_range: dict[str, Any],
    ) -> str:
        identity = {
            "builder_version": self.VERSION,
            "origin": origin,
            "source_backend": source_backend,
            "start_frame_index": source_f0_frame_range.get("start_frame_index"),
            "end_frame_index": source_f0_frame_range.get("end_frame_index"),
            "start_time_sec": round(float(start_time), 6),
            "end_time_sec": round(float(end_time), 6),
            "pitch_center_midi": round(float(pitch_center_midi), 6),
        }
        digest = hashlib.sha1(
            json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return f"nc_{origin}_{digest}"

    def _stable_contour_id(
        self,
        *,
        source_backend: str,
        start_time: float,
        end_time: float,
        pitch_center_midi: float | None,
    ) -> str:
        identity = {
            "builder_version": self.VERSION,
            "source_backend": source_backend,
            "start_time_sec": round(float(start_time), 6),
            "end_time_sec": round(float(end_time), 6),
            "pitch_center_midi": _round_optional(pitch_center_midi),
        }
        digest = hashlib.sha1(
            json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        return f"pc_{digest}"

    @staticmethod
    def _source_backend(
        *,
        f0_track: dict[str, Any] | None,
        contour_payload: dict[str, Any] | None,
    ) -> str:
        return (
            _as_optional_str((f0_track or {}).get("backend"))
            or _as_optional_str((contour_payload or {}).get("source_f0_track"))
            or _as_optional_str((f0_track or {}).get("source_stem"))
            or "unknown"
        )

    @staticmethod
    def _raw_candidate_input_count(raw_candidates: Any) -> int:
        if isinstance(raw_candidates, list):
            return len([item for item in raw_candidates if isinstance(item, dict)])
        if isinstance(raw_candidates, dict):
            melody_candidates = raw_candidates.get("melody_candidates")
            if isinstance(melody_candidates, dict) and isinstance(melody_candidates.get("notes"), list):
                return len([item for item in melody_candidates.get("notes") if isinstance(item, dict)])
            notes = raw_candidates.get("notes")
            if isinstance(notes, list):
                return len([item for item in notes if isinstance(item, dict)])
        return 0


def _extract_pitch_midi(payload: dict[str, Any]) -> float | None:
    value = _safe_float(_first(payload, "pitch_center_midi", "pitch_midi", "median_midi", "mean_midi", "midi_float", "midi"))
    if value is not None:
        return value
    frequency_hz = _safe_float(_first(payload, "frequency_hz", "f0_hz", "frequency", "f0"))
    if frequency_hz is not None and frequency_hz > 0.0:
        return 69.0 + 12.0 * math.log2(frequency_hz / 440.0)
    pitch_name = _as_optional_str(_first(payload, "pitch", "pitch_name"))
    if pitch_name:
        return _note_name_to_midi(pitch_name)
    return None


def _note_name_to_midi(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) < 2:
        return None
    note_part = text[0].upper()
    accidental = ""
    octave_part = text[1:]
    if len(text) >= 3 and text[1] in {"#", "b", "B"}:
        accidental = "#" if text[1] == "#" else "b"
        octave_part = text[2:]
    mapping = {
        "C": 0,
        "D": 2,
        "E": 4,
        "F": 5,
        "G": 7,
        "A": 9,
        "B": 11,
    }
    semitone = mapping.get(note_part)
    if semitone is None:
        return None
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1
    try:
        octave = int(octave_part)
    except (TypeError, ValueError):
        return None
    return float((octave + 1) * 12 + semitone)


def _midi_to_note_name(value: float) -> str:
    midi_value = int(round(float(value)))
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    octave = (midi_value // 12) - 1
    return f"{names[midi_value % 12]}{octave}"


def _stability_from_pitch_range(pitch_range_semitones: float, max_pitch_range_semitones: float) -> float:
    scale = max(0.001, float(max_pitch_range_semitones))
    stability = 1.0 - (max(0.0, float(pitch_range_semitones)) / scale)
    return max(0.0, min(1.0, stability))


def _contour_stability_from_pitch_range(pitch_range_semitones: float) -> float:
    stability = 1.0 - (max(0.0, float(pitch_range_semitones)) / 3.0)
    return max(0.0, min(1.0, stability))


def _stable_frame_segments(
    frames: list[dict[str, Any]],
    *,
    min_confidence: float,
    max_frame_gap_sec: float,
    max_pitch_range_semitones: float,
) -> list[list[dict[str, Any]]]:
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for frame in frames:
        confidence = _safe_float(frame.get("confidence"))
        if confidence is None or confidence < min_confidence:
            if current:
                segments.append(current)
                current = []
            continue
        if current:
            previous = current[-1]
            pitch_values = [float(item["pitch_midi"]) for item in current] + [float(frame["pitch_midi"])]
            if (
                float(frame["time_sec"]) - float(previous["time_sec"]) > max_frame_gap_sec
                or max(pitch_values) - min(pitch_values) > max_pitch_range_semitones
            ):
                segments.append(current)
                current = []
        current.append(frame)
    if current:
        segments.append(current)
    return segments


def _extended_segment_bounds(
    *,
    segment: list[dict[str, Any]],
    segment_index: int,
    segments: list[list[dict[str, Any]]],
    contour: dict[str, Any],
    max_extension_sec: float,
) -> tuple[float, float]:
    times = sorted(float(item["time_sec"]) for item in segment if _safe_float(item.get("time_sec")) is not None)
    if not times:
        return 0.0, 0.0
    hop = _median_positive_delta(times)
    stable_start = min(times)
    stable_end = max(times) + hop
    contour_start = _safe_float(contour.get("start_time_sec"))
    contour_end = _safe_float(contour.get("end_time_sec"))
    left_bound = stable_start if contour_start is None else float(contour_start)
    right_bound = stable_end if contour_end is None else float(contour_end)
    if segment_index > 0:
        previous_times = sorted(
            float(item["time_sec"])
            for item in segments[segment_index - 1]
            if _safe_float(item.get("time_sec")) is not None
        )
        if previous_times:
            previous_end = max(previous_times) + _median_positive_delta(previous_times)
            left_bound = max(left_bound, (previous_end + stable_start) / 2.0)
    if segment_index + 1 < len(segments):
        next_times = sorted(
            float(item["time_sec"])
            for item in segments[segment_index + 1]
            if _safe_float(item.get("time_sec")) is not None
        )
        if next_times:
            next_start = min(next_times)
            right_bound = min(right_bound, (stable_end + next_start) / 2.0)
    extension = max(0.0, float(max_extension_sec))
    return max(left_bound, stable_start - extension), min(right_bound, stable_end + extension)


def _median_positive_delta(values: list[float]) -> float:
    deltas = [float(right) - float(left) for left, right in zip(values, values[1:]) if float(right) > float(left)]
    if not deltas:
        return 0.01
    return float(median(deltas))


def _overlap_ratio(*, start_time: float, end_time: float, other_start: float, other_end: float) -> float:
    duration = max(0.0, float(end_time) - float(start_time))
    if duration <= 0.0:
        return 0.0
    return _overlap_seconds(
        left_start=float(start_time),
        left_end=float(end_time),
        right_start=float(other_start),
        right_end=float(other_end),
    ) / duration


def _overlap_seconds(*, left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    return max(0.0, min(float(left_end), float(right_end)) - max(float(left_start), float(right_start)))


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _round_optional(value: Any) -> float | None:
    parsed = _safe_float(value)
    return round(parsed, 6) if parsed is not None else None


def _clamp01(value: Any) -> float:
    parsed = _safe_float(value)
    if parsed is None:
        return 0.0
    return round(max(0.0, min(1.0, parsed)), 6)


def _unique_str_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
