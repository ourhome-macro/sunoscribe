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
                    merged[-1] = Note(
                        pitch=prev.pitch,
                        start_time=float(prev.start_time),
                        end_time=max(float(prev.end_time), float(note.end_time)),
                        confidence=max(float(prev.confidence), float(note.confidence)),
                        reason_codes=_unique_reason_codes(
                            list(getattr(prev, "reason_codes", []) or [])
                            + list(getattr(note, "reason_codes", []) or [])
                        ),
                    )
                    continue

                merged.append(note)

        if bool(self.config.quantize_overlap_resolution_enabled):
            merged = self._resolve_overlaps(merged)

        return merged

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
                    resolved[-1] = Note(
                        pitch=prev.pitch,
                        start_time=float(prev.start_time),
                        end_time=new_prev_end,
                        confidence=float(prev.confidence),
                        reason_codes=list(getattr(prev, "reason_codes", []) or []),
                    )
                else:
                    adjusted_start = min(float(note.end_time), float(prev.end_time) + min_gap)
                    note = Note(
                        pitch=note.pitch,
                        start_time=adjusted_start,
                        end_time=float(note.end_time),
                        confidence=float(note.confidence),
                        reason_codes=list(getattr(note, "reason_codes", []) or []),
                    )

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
