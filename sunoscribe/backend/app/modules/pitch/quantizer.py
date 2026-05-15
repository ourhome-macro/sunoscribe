from __future__ import annotations

from typing import List, Tuple

from .config import PitchDetectionConfig
from .note_utils import note_to_midi
from .types import Note, NoteType, QuantizedNote


class NoteQuantizer:
    def __init__(self, config: PitchDetectionConfig):
        self.config = config

    def quantize(self, notes: List[Note], bpm: float, beat_times: List[float]) -> List[QuantizedNote]:
        if bpm <= 0:
            return []

        processed_notes = self._preprocess_notes(notes)
        if not processed_notes:
            return []

        beat_duration = 60.0 / bpm
        precision = max(0.015625, float(self.config.quantize_precision))
        min_duration_beats = max(0.015625, float(self.config.quantize_min_duration_beats))
        jitter_tolerance = max(0.0, float(self.config.quantize_jitter_tolerance_beats))

        quantized: List[QuantizedNote] = []
        for note in processed_notes:
            duration_sec = max(0.0, note.end_time - note.start_time)
            raw_duration_beats = duration_sec / beat_duration
            if raw_duration_beats < min_duration_beats:
                continue

            quantized_beats = max(precision, round(raw_duration_beats / precision) * precision)
            if raw_duration_beats <= (min_duration_beats + jitter_tolerance):
                quantized_beats = min_duration_beats

            note_type = self._classify_note_type(quantized_beats)
            measure_num, beat_position = self._locate_measure(note.start_time, beat_duration, beat_times)

            quantized.append(
                QuantizedNote(
                    pitch=note.pitch,
                    start_time=note.start_time,
                    end_time=note.end_time,
                    confidence=note.confidence,
                    duration_beats=round(quantized_beats, 3),
                    note_type=note_type,
                    measure_num=measure_num,
                    beat_position=beat_position,
                    lyric=None,
                    source=getattr(note, "source", None),
                    reason_codes=list(getattr(note, "reason_codes", []) or []),
                    **self._lineage_kwargs(note),
                )
            )

        return quantized

    def _preprocess_notes(self, notes: List[Note]) -> List[Note]:
        if not notes:
            return []

        noise_floor = max(0.0, min(1.0, float(self.config.quantize_noise_confidence_floor)))
        filtered = [n for n in notes if float(n.confidence) >= noise_floor]
        if not filtered:
            return []

        filtered.sort(key=lambda n: (n.start_time, n.end_time))

        if not bool(self.config.quantize_merge_same_pitch_enabled):
            merged = filtered
        else:
            merge_gap = max(0.0, float(self.config.quantize_merge_same_pitch_gap_sec))
            merge_min_conf = max(0.0, min(1.0, float(self.config.quantize_merge_min_confidence)))
            near_pitch_enabled = bool(self.config.quantize_merge_near_pitch_enabled)
            max_semitone = max(0, int(self.config.quantize_merge_near_pitch_max_semitone))

            merged = []
            for note in filtered:
                if not merged:
                    merged.append(note)
                    continue

                prev = merged[-1]
                gap = float(note.start_time) - float(prev.end_time)
                can_merge = (
                    gap >= 0.0
                    and gap <= merge_gap
                    and prev.confidence >= merge_min_conf
                    and note.confidence >= merge_min_conf
                    and self._is_mergeable_pitch(prev.pitch, note.pitch, near_pitch_enabled, max_semitone)
                )

                if can_merge:
                    merged[-1] = self._merge_notes(prev, note)
                    continue

                merged.append(note)

        if bool(self.config.quantize_overlap_resolution_enabled):
            merged = self._resolve_overlaps(merged)

        return merged

    def _merge_notes(self, prev: Note, note: Note) -> Note:
        lineage = self._merged_lineage_kwargs(prev, note)
        return Note(
            pitch=prev.pitch,
            start_time=float(prev.start_time),
            end_time=max(float(prev.end_time), float(note.end_time)),
            confidence=max(float(prev.confidence), float(note.confidence)),
            reason_codes=_unique_reason_codes(
                list(getattr(prev, "reason_codes", []) or [])
                + list(getattr(note, "reason_codes", []) or [])
            ),
            candidate_origin="quantizer.merge_same_pitch",
            **lineage,
        )

    def _trim_note_end(self, note: Note, end_time: float) -> Note:
        return Note(
            pitch=note.pitch,
            start_time=float(note.start_time),
            end_time=float(end_time),
            confidence=float(note.confidence),
            reason_codes=list(getattr(note, "reason_codes", []) or []),
            candidate_origin=getattr(note, "candidate_origin", None),
            **self._lineage_kwargs(note),
        )

    def _trim_note_start(self, note: Note, start_time: float) -> Note:
        return Note(
            pitch=note.pitch,
            start_time=float(start_time),
            end_time=float(note.end_time),
            confidence=float(note.confidence),
            reason_codes=list(getattr(note, "reason_codes", []) or []),
            candidate_origin=getattr(note, "candidate_origin", None),
            **self._lineage_kwargs(note),
        )

    @classmethod
    def _lineage_kwargs(cls, note: Note) -> dict:
        source_candidate_id = getattr(note, "source_candidate_id", None) or getattr(note, "candidate_id", None)
        source_candidate_ids = cls._source_candidate_ids(note)
        if source_candidate_id and str(source_candidate_id) not in source_candidate_ids:
            source_candidate_ids = [str(source_candidate_id)] + source_candidate_ids
        return {
            "candidate_id": getattr(note, "candidate_id", None),
            "source_candidate_id": str(source_candidate_id) if source_candidate_id else None,
            "source_candidate_ids": source_candidate_ids,
            "source_contour_ids": cls._unique_strings(getattr(note, "source_contour_ids", []) or []),
            "contour_bridge_evidence": dict(getattr(note, "contour_bridge_evidence", {}) or {}),
            "contour_bridge_guard_reason_codes": cls._unique_strings(
                getattr(note, "contour_bridge_guard_reason_codes", []) or []
            ),
            "segmentation_evidence": dict(getattr(note, "segmentation_evidence", {}) or {}),
        }

    @classmethod
    def _merged_lineage_kwargs(cls, prev: Note, note: Note) -> dict:
        prev_lineage = cls._lineage_kwargs(prev)
        note_lineage = cls._lineage_kwargs(note)
        source_candidate_ids = cls._unique_strings(
            list(prev_lineage.get("source_candidate_ids") or [])
            + list(note_lineage.get("source_candidate_ids") or [])
        )
        source_contour_ids = cls._unique_strings(
            list(prev_lineage.get("source_contour_ids") or [])
            + list(note_lineage.get("source_contour_ids") or [])
        )
        segmentation_evidence = dict(prev_lineage.get("segmentation_evidence") or {})
        note_segmentation = dict(note_lineage.get("segmentation_evidence") or {})
        prev_frame_range = segmentation_evidence.get("source_f0_frame_range")
        note_frame_range = note_segmentation.get("source_f0_frame_range")
        merged_frame_range = cls._merge_frame_ranges(prev_frame_range, note_frame_range)
        original_frame_ranges = [
            dict(frame_range)
            for frame_range in (prev_frame_range, note_frame_range)
            if isinstance(frame_range, dict)
        ]
        if merged_frame_range:
            segmentation_evidence["source_f0_frame_range"] = merged_frame_range
            segmentation_evidence["merged_source_f0_frame_ranges"] = original_frame_ranges
        contour_bridge_evidence = dict(prev_lineage.get("contour_bridge_evidence") or {})
        note_bridge_evidence = dict(note_lineage.get("contour_bridge_evidence") or {})
        if note_bridge_evidence:
            contour_bridge_evidence["merged_sources"] = [contour_bridge_evidence, note_bridge_evidence]
        return {
            "candidate_id": getattr(prev, "candidate_id", None) or getattr(note, "candidate_id", None),
            "source_candidate_id": (source_candidate_ids[0] if source_candidate_ids else None),
            "source_candidate_ids": source_candidate_ids,
            "source_contour_ids": source_contour_ids,
            "contour_bridge_evidence": contour_bridge_evidence,
            "contour_bridge_guard_reason_codes": cls._unique_strings(
                list(prev_lineage.get("contour_bridge_guard_reason_codes") or [])
                + list(note_lineage.get("contour_bridge_guard_reason_codes") or [])
            ),
            "segmentation_evidence": segmentation_evidence,
        }

    @classmethod
    def _source_candidate_ids(cls, note: Note) -> list[str]:
        values = []
        for attr in ("source_candidate_id", "candidate_id"):
            value = getattr(note, attr, None)
            if value:
                values.append(value)
        values.extend(getattr(note, "source_candidate_ids", []) or [])
        return cls._unique_strings(values)

    @staticmethod
    def _merge_frame_ranges(left: object, right: object) -> dict:
        if not isinstance(left, dict):
            return dict(right) if isinstance(right, dict) else {}
        if not isinstance(right, dict):
            return dict(left)
        start_values = [value for value in (left.get("start_frame_index"), right.get("start_frame_index")) if value is not None]
        end_values = [value for value in (left.get("end_frame_index"), right.get("end_frame_index")) if value is not None]
        if not start_values or not end_values:
            return dict(left)
        start = int(min(start_values))
        end = int(max(end_values))
        result = dict(left)
        result["start_frame_index"] = start
        result["end_frame_index"] = end
        result["frame_count"] = max(1, end - start + 1)
        return result

    @staticmethod
    def _unique_strings(values: object) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values or []:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result
    @staticmethod
    def _is_mergeable_pitch(
        left: str,
        right: str,
        near_pitch_enabled: bool,
        max_semitone: int,
    ) -> bool:
        if left == right:
            return True
        if not near_pitch_enabled:
            return False

        try:
            left_midi = int(round(float(note_to_midi(left))))
            right_midi = int(round(float(note_to_midi(right))))
        except Exception:
            return False
        return abs(left_midi - right_midi) <= max_semitone

    def _resolve_overlaps(self, notes: List[Note]) -> List[Note]:
        if len(notes) < 2:
            return notes

        min_gap = max(0.0, float(self.config.quantize_overlap_min_gap_sec))
        resolved: List[Note] = [notes[0]]
        for note in notes[1:]:
            prev = resolved[-1]
            if float(note.start_time) < float(prev.end_time):
                # 优先保留高置信度音符的完整时长，截断另一条以消除重叠。
                if note.confidence > prev.confidence:
                    new_prev_end = max(float(prev.start_time), float(note.start_time) - min_gap)
                    resolved[-1] = self._trim_note_end(prev, new_prev_end)
                else:
                    adjusted_start = min(float(note.end_time), float(prev.end_time) + min_gap)
                    note = self._trim_note_start(note, adjusted_start)

            if note.end_time > note.start_time:
                resolved.append(note)

        return resolved

    def _classify_note_type(self, beats: float) -> NoteType:
        if self.config.quantize_mode == "strict":
            return self._strict_quantize(beats)
        return self._adaptive_quantize(beats)

    def _strict_quantize(self, beats: float) -> NoteType:
        mapping = [
            (4.0, NoteType.WHOLE),
            (2.0, NoteType.HALF),
            (1.0, NoteType.QUARTER),
            (0.5, NoteType.EIGHTH),
            (0.25, NoteType.SIXTEENTH),
            (0.125, NoteType.THIRTY_SECOND),
        ]
        return min(mapping, key=lambda x: abs(x[0] - beats))[1]

    def _adaptive_quantize(self, beats: float) -> NoteType:
        dotted_tol = max(0.0, float(self.config.adaptive_dotted_tolerance_beats))
        triplet_tol = max(0.0, float(self.config.adaptive_triplet_tolerance_beats))

        if abs(beats - (2.0 / 3.0)) <= triplet_tol:
            return NoteType.TRIPLET
        if abs(beats - 1.5) <= dotted_tol:
            return NoteType.DOTTED_QUARTER
        if abs(beats - 0.75) <= dotted_tol:
            return NoteType.DOTTED_EIGHTH

        mapping = [
            (4.0, NoteType.WHOLE),
            (2.0, NoteType.HALF),
            (1.0, NoteType.QUARTER),
            (0.5, NoteType.EIGHTH),
            (0.25, NoteType.SIXTEENTH),
            (0.125, NoteType.THIRTY_SECOND),
        ]
        return min(mapping, key=lambda x: abs(x[0] - beats))[1]

    def _locate_measure(self, start_time: float, beat_duration: float, beat_times: List[float]) -> Tuple[int, float]:
        measure_length_beats = float(max(2, int(self.config.beats_per_bar)))
        anchor = beat_times[0] if beat_times else 0.0
        elapsed_beats = max(0.0, (start_time - anchor) / beat_duration)

        measure_num = int(elapsed_beats // measure_length_beats) + 1
        beat_position = (elapsed_beats % measure_length_beats) + 1.0
        return measure_num, round(beat_position, 3)


def _unique_reason_codes(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result

