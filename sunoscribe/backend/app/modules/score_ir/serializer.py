from __future__ import annotations

from typing import Any, Dict

from .types import ScoreIR


class ScoreIRSerializer:
    """Flatten ScoreIR into score_data-compatible payloads."""

    @staticmethod
    def to_score_data_dict(score_ir: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(score_ir, dict):
            raise TypeError("score_ir must be a dictionary")

        meta = score_ir.get("meta") if isinstance(score_ir.get("meta"), dict) else {}
        note_by_id = {
            str(note.get("id")): note
            for note in (score_ir.get("notes") or [])
            if isinstance(note, dict) and note.get("id") is not None
        }

        measures = []
        for idx, measure in enumerate(score_ir.get("measures") or [], start=1):
            if not isinstance(measure, dict):
                continue
            packed_notes = []
            for note in _measure_notes_from_dict(measure, note_by_id):
                packed_notes.append(_pack_score_note_dict(note))
            measures.append(
                {
                    "measure_num": measure.get("measure_num") or idx,
                    "start_time": measure.get("start_time"),
                    "end_time": measure.get("end_time"),
                    "is_anacrusis": bool(measure.get("is_anacrusis", False)),
                    "notes": packed_notes,
                }
            )

        return {
            "meta": dict(meta),
            "bpm": meta.get("bpm"),
            "key": meta.get("key"),
            "time_signature": meta.get("time_signature"),
            "measures": measures,
            "instrumental_melody_notes": [
                _pack_score_note_dict(note)
                for note in (score_ir.get("instrumental_melody_notes") or [])
                if isinstance(note, dict)
            ],
            "bassline_notes": [
                _pack_score_note_dict(note)
                for note in (score_ir.get("bassline_notes") or [])
                if isinstance(note, dict)
            ],
            "chord_timeline": list(score_ir.get("chord_timeline") or []),
            "form_sections": list(score_ir.get("form_sections") or []),
            "lyrics_segments": list(score_ir.get("lyrics_segments") or []),
            "analysis_hints": dict(score_ir.get("analysis_hints") or {}),
            "warnings": list(score_ir.get("warnings") or []),
        }

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
                        "id": note.id,
                        "pitch": note.pitch,
                        "pitch_midi": note.pitch_midi,
                        "start_time": note.start_time,
                        "end_time": note.end_time,
                        "duration_beats": note.duration_beats,
                        "note_type": note.note_type,
                        "beat_position": note.beat_position,
                        "lyric": note.lyric,
                        "confidence": note.confidence,
                        "source": note.source,
                        "source_candidate_id": note.source_candidate_id,
                        "quantized_note_id": note.quantized_note_id,
                        "timing_origin": note.timing_origin,
                        "performance_start_time_sec": note.performance_start_time_sec,
                        "performance_end_time_sec": note.performance_end_time_sec,
                        "quantized_start_time_sec": note.quantized_start_time_sec,
                        "quantized_end_time_sec": note.quantized_end_time_sec,
                        "quantized_duration_sec": note.quantized_duration_sec,
                        "uncertain": note.uncertain,
                        "reason_codes": list(note.reason_codes or []),
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
                    "source_candidate_id": note.source_candidate_id,
                    "quantized_note_id": note.quantized_note_id,
                    "timing_origin": note.timing_origin,
                    "performance_start_time_sec": note.performance_start_time_sec,
                    "performance_end_time_sec": note.performance_end_time_sec,
                    "quantized_start_time_sec": note.quantized_start_time_sec,
                    "quantized_end_time_sec": note.quantized_end_time_sec,
                    "quantized_duration_sec": note.quantized_duration_sec,
                    "uncertain": note.uncertain,
                    "reason_codes": list(note.reason_codes or []),
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
                    "source_candidate_id": note.source_candidate_id,
                    "quantized_note_id": note.quantized_note_id,
                    "timing_origin": note.timing_origin,
                    "performance_start_time_sec": note.performance_start_time_sec,
                    "performance_end_time_sec": note.performance_end_time_sec,
                    "quantized_start_time_sec": note.quantized_start_time_sec,
                    "quantized_end_time_sec": note.quantized_end_time_sec,
                    "quantized_duration_sec": note.quantized_duration_sec,
                    "uncertain": note.uncertain,
                    "reason_codes": list(note.reason_codes or []),
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


def _measure_notes_from_dict(measure: Dict[str, Any], note_by_id: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
    inline_notes = measure.get("notes")
    if isinstance(inline_notes, list):
        return [note for note in inline_notes if isinstance(note, dict)]

    notes: list[Dict[str, Any]] = []
    for note_id in measure.get("note_ids") or []:
        note = note_by_id.get(str(note_id))
        if note is not None:
            notes.append(note)
    return notes


def _pack_score_note_dict(note: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": note.get("id"),
        "pitch": note.get("pitch"),
        "pitch_midi": note.get("pitch_midi"),
        "start_time": note.get("start_time"),
        "end_time": note.get("end_time"),
        "duration_beats": note.get("duration_beats"),
        "note_type": note.get("note_type"),
        "measure_num": note.get("measure_num"),
        "beat_position": note.get("beat_position"),
        "lyric": note.get("lyric"),
        "confidence": note.get("confidence"),
        "source": note.get("source"),
        "source_candidate_id": note.get("source_candidate_id"),
        "quantized_note_id": note.get("quantized_note_id"),
        "timing_origin": note.get("timing_origin"),
        "performance_start_time_sec": note.get("performance_start_time_sec"),
        "performance_end_time_sec": note.get("performance_end_time_sec"),
        "quantized_start_time_sec": note.get("quantized_start_time_sec"),
        "quantized_end_time_sec": note.get("quantized_end_time_sec"),
        "quantized_duration_sec": note.get("quantized_duration_sec"),
        "uncertain": bool(note.get("uncertain", False)),
        "reason_codes": list(note.get("reason_codes") or []),
    }
