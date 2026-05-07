from __future__ import annotations

from typing import Any, Dict

from .types import ScoreIR


class ScoreIRSerializer:
    """Flatten ScoreIR into score_data-compatible payloads."""

    @staticmethod
    def to_score_data(score_ir: ScoreIR) -> Dict[str, Any]:
        note_by_id = {note.id: note for note in (score_ir.notes or [])}

        measures = []
        for measure in score_ir.measures or []:
            packed_notes = []
            for note_id in measure.note_ids or []:
                note = note_by_id.get(note_id)
                if note is None:
                    continue
                packed_notes.append(
                    {
                        "pitch": note.pitch,
                        "start_time": note.start_time,
                        "end_time": note.end_time,
                        "duration_beats": note.duration_beats,
                        "note_type": note.note_type,
                        "beat_position": note.beat_position,
                        "lyric": note.lyric,
                        "confidence": note.confidence,
                    }
                )

            measures.append(
                {
                    "measure_num": measure.measure_num,
                    "start_time": measure.start_time,
                    "end_time": measure.end_time,
                    "is_anacrusis": measure.is_anacrusis,
                    "notes": packed_notes,
                }
            )

        return {
            "meta": {
                "source_version": score_ir.meta.source_version,
                "bpm": score_ir.meta.bpm,
                "bpm_confidence": score_ir.meta.bpm_confidence,
                "key": score_ir.meta.key,
                "key_confidence": score_ir.meta.key_confidence,
                "duration_sec": score_ir.meta.duration_sec,
                "time_signature": score_ir.meta.time_signature,
                "rhythm_type": score_ir.meta.rhythm_type,
                "total_measures": score_ir.meta.total_measures,
                "has_anacrusis": score_ir.meta.has_anacrusis,
                "analysis_info": dict(score_ir.meta.analysis_info or {}),
            },
            "bpm": score_ir.meta.bpm,
            "key": score_ir.meta.key,
            "time_signature": score_ir.meta.time_signature,
            "measures": measures,
            "instrumental_melody_notes": [
                {
                    "id": note.id,
                    "pitch": note.pitch,
                    "pitch_midi": note.pitch_midi,
                    "start_time": note.start_time,
                    "end_time": note.end_time,
                    "confidence": note.confidence,
                    "duration_beats": note.duration_beats,
                    "measure_num": note.measure_num,
                    "beat_position": note.beat_position,
                    "source": note.source,
                }
                for note in (score_ir.instrumental_melody_notes or [])
            ],
            "bassline_notes": [
                {
                    "id": note.id,
                    "pitch": note.pitch,
                    "start_time": note.start_time,
                    "end_time": note.end_time,
                    "measure_num": note.measure_num,
                    "confidence": note.confidence,
                    "source": note.source,
                }
                for note in (score_ir.bassline_notes or [])
            ],
            "chord_timeline": [
                {
                    "id": chord.id,
                    "start_time": chord.start_time,
                    "end_time": chord.end_time,
                    "measure_num": chord.measure_num,
                    "symbol": chord.symbol,
                    "root": chord.root,
                    "quality": chord.quality,
                    "bass": chord.bass,
                    "confidence": chord.confidence,
                    "evidence": dict(chord.evidence or {}),
                }
                for chord in (score_ir.chord_timeline or [])
            ],
            "form_sections": [
                {
                    "id": section.id,
                    "label": section.label,
                    "start_time": section.start_time,
                    "end_time": section.end_time,
                    "measure_start": section.measure_start,
                    "measure_end": section.measure_end,
                    "confidence": section.confidence,
                    "evidence": dict(section.evidence or {}),
                }
                for section in (score_ir.form_sections or [])
            ],
            "lyrics_segments": [segment for segment in score_ir.to_dict().get("lyrics_segments", [])],
            "analysis_hints": score_ir.to_dict().get("analysis_hints", {}),
            "warnings": list(score_ir.warnings or []),
        }
