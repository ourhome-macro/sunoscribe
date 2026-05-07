from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Iterable, Sequence

from .exceptions import MidiExportError
from .types import QuantizedNote


class MidiExporter:
    """将量化音符导出为 MIDI（文件或字节流）。"""

    def __init__(self, default_velocity: int = 90, instrument_program: int = 0) -> None:
        self.default_velocity = max(1, min(127, int(default_velocity)))
        self.instrument_program = max(0, min(127, int(instrument_program)))

    def export_quantized_notes(
        self,
        notes: Sequence[QuantizedNote],
        bpm: float,
        output_path: str | Path | None = None,
    ) -> bytes:
        if not notes:
            raise MidiExportError("无可导出的量化音符。")

        pm = self._build_pretty_midi(notes, bpm)
        data = self._to_bytes(pm)

        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        return data

    def export_from_measures(
        self,
        measures: Sequence[dict],
        bpm: float,
        output_path: str | Path | None = None,
    ) -> bytes:
        notes = self._quantized_notes_from_measures(measures)
        return self.export_quantized_notes(notes=notes, bpm=bpm, output_path=output_path)

    def export_from_score_data(
        self,
        score_data: dict[str, Any],
        bpm: float,
        output_path: str | Path | None = None,
    ) -> bytes:
        measures = score_data.get("measures")
        if not isinstance(measures, list) or not measures:
            raise MidiExportError("score data has no measures to export.")
        lead_notes = self._quantized_notes_from_measures(measures)
        hook_notes = self._quantized_notes_from_items(score_data.get("instrumental_melody_notes") or [])
        pm = self._build_pretty_midi_tracks(
            tracks=[
                ("Lead Vocal", self.instrument_program, lead_notes, 1.0),
                ("Instrumental Hook", self.instrument_program, hook_notes, 0.85),
            ],
            bpm=bpm,
        )
        data = self._to_bytes(pm)
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return data

    def _build_pretty_midi(self, notes: Sequence[QuantizedNote], bpm: float):
        try:
            import pretty_midi
        except Exception as exc:  # pragma: no cover - 环境依赖异常
            raise MidiExportError("缺少 pretty_midi 依赖，无法导出 MIDI。") from exc

        pm = pretty_midi.PrettyMIDI(initial_tempo=max(1.0, float(bpm)))
        instrument = pretty_midi.Instrument(program=self.instrument_program)

        invalid_count = 0
        for n in notes:
            if n.end_time <= n.start_time:
                continue
            try:
                pitch_num = int(pretty_midi.note_name_to_number(n.pitch))
            except Exception:
                invalid_count += 1
                continue

            velocity = max(1, min(127, int(round(self.default_velocity * max(0.2, min(1.0, n.confidence))))))
            instrument.notes.append(
                pretty_midi.Note(
                    velocity=velocity,
                    pitch=pitch_num,
                    start=float(n.start_time),
                    end=float(n.end_time),
                )
            )

        if not instrument.notes:
            raise MidiExportError("未能生成有效 MIDI 音符（可能音高名非法或时长无效）。")

        instrument.notes.sort(key=lambda x: x.start)
        pm.instruments.append(instrument)
        pm.remove_invalid_notes()

        if invalid_count > 0 and len(instrument.notes) == 0:
            raise MidiExportError("所有音符均为非法音高名，导出失败。")

        return pm

    def _build_pretty_midi_tracks(
        self,
        *,
        tracks: Sequence[tuple[str, int, Sequence[QuantizedNote], float]],
        bpm: float,
    ):
        try:
            import pretty_midi
        except Exception as exc:  # pragma: no cover - environment dependency error
            raise MidiExportError("missing pretty_midi dependency; cannot export MIDI.") from exc

        pm = pretty_midi.PrettyMIDI(initial_tempo=max(1.0, float(bpm)))
        for name, program, notes, velocity_scale in tracks:
            if not notes:
                continue
            instrument = pretty_midi.Instrument(program=max(0, min(127, int(program))), name=name)
            for note in notes:
                if note.end_time <= note.start_time:
                    continue
                try:
                    pitch_num = int(pretty_midi.note_name_to_number(note.pitch))
                except Exception:
                    continue
                velocity = max(
                    1,
                    min(
                        127,
                        int(
                            round(
                                self.default_velocity
                                * max(0.2, min(1.0, note.confidence))
                                * max(0.1, float(velocity_scale))
                            )
                        ),
                    ),
                )
                instrument.notes.append(
                    pretty_midi.Note(
                        velocity=velocity,
                        pitch=pitch_num,
                        start=float(note.start_time),
                        end=float(note.end_time),
                    )
                )
            if instrument.notes:
                instrument.notes.sort(key=lambda item: item.start)
                pm.instruments.append(instrument)

        pm.remove_invalid_notes()
        if not pm.instruments or not any(instrument.notes for instrument in pm.instruments):
            raise MidiExportError("score data contains no exportable MIDI notes.")
        return pm

    @staticmethod
    def _to_bytes(pm) -> bytes:
        with io.BytesIO() as buf:
            pm.write(buf)
            return buf.getvalue()

    @staticmethod
    def _quantized_notes_from_measures(measures: Sequence[dict]) -> list[QuantizedNote]:
        normalized: list[QuantizedNote] = []
        for measure in measures:
            for item in measure.get("notes", []):
                note = MidiExporter._quantized_note_from_item(item, measure_num=measure.get("measure_num"))
                if note is not None:
                    normalized.append(note)

        if not normalized:
            raise MidiExportError("小节数据中无可导出的音符。")

        return normalized

    @staticmethod
    def _quantized_notes_from_items(items: Sequence[dict]) -> list[QuantizedNote]:
        normalized: list[QuantizedNote] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            note = MidiExporter._quantized_note_from_item(item, measure_num=item.get("measure_num"))
            if note is not None:
                normalized.append(note)
        return sorted(normalized, key=lambda note: (note.start_time, note.pitch, note.end_time))

    @staticmethod
    def _quantized_note_from_item(item: dict, *, measure_num: object = None) -> QuantizedNote | None:
        pitch = item.get("pitch")
        start = item.get("start_time")
        end = item.get("end_time")
        if pitch is None or start is None or end is None:
            return None

        from .types import NoteType

        try:
            note_type_enum = NoteType(item.get("note_type", "quarter") or "quarter")
        except Exception:
            note_type_enum = NoteType.QUARTER

        try:
            confidence = float(item.get("confidence", 0.8))
            duration_beats = float(item.get("duration_beats", 1.0) or 1.0)
            start_time = float(start)
            end_time = float(end)
        except (TypeError, ValueError):
            return None

        return QuantizedNote(
            pitch=str(pitch),
            start_time=start_time,
            end_time=end_time,
            confidence=confidence,
            duration_beats=duration_beats,
            note_type=note_type_enum,
            measure_num=measure_num,
            beat_position=item.get("beat_position"),
            lyric=item.get("lyric"),
            source=item.get("source"),
        )
