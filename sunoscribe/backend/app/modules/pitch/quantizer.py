from __future__ import annotations

from typing import List, Tuple

from .config import PitchDetectionConfig
from .types import Note, NoteType, QuantizedNote


class NoteQuantizer:
    def __init__(self, config: PitchDetectionConfig):
        self.config = config

    def quantize(self, notes: List[Note], bpm: float, beat_times: List[float]) -> List[QuantizedNote]:
        if bpm <= 0:
            return []

        beat_duration = 60.0 / bpm
        precision = max(0.015625, float(self.config.quantize_precision))

        quantized: List[QuantizedNote] = []
        for note in notes:
            duration_sec = max(0.0, note.end_time - note.start_time)
            raw_duration_beats = duration_sec / beat_duration
            quantized_beats = max(precision, round(raw_duration_beats / precision) * precision)
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
                )
            )

        return quantized

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
        mapping = [
            (4.0, NoteType.WHOLE),
            (2.0, NoteType.HALF),
            (1.5, NoteType.DOTTED_QUARTER),
            (1.0, NoteType.QUARTER),
            (2.0 / 3.0, NoteType.TRIPLET),
            (0.75, NoteType.DOTTED_EIGHTH),
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
