from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..analysis_ir.types import AnalysisIR
from ..pitch.note_utils import note_to_midi
from ..pitch.types import Note
from ..pitch.types import PitchAnalysisResult
from .types import (
    AnalysisHints,
    IssueSpot,
    LyricsSegment,
    LyricsToken,
    ScoreIR,
    ScoreChord,
    ScoreMeasure,
    ScoreMeta,
    ScoreNote,
    ScoreSection,
)


class ScoreIRBuilder:
    _MIXED_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|[^\s]", re.UNICODE)
    _PUNCT_ONLY_PATTERN = re.compile(r"^[\W_]+$", re.UNICODE)
    _ZH_PATTERN = re.compile(r"[\u4e00-\u9fff]")
    _EN_PATTERN = re.compile(r"[A-Za-z]")

    def build(
        self,
        pitch_result: PitchAnalysisResult,
        lyrics_segments: list[dict] | None = None,
        analysis_ir: AnalysisIR | None = None,
        quantized_notes_artifact: dict[str, Any] | None = None,
    ) -> ScoreIR:
        normalized_lyrics = lyrics_segments or []

        notes, measure_note_ids = self._build_notes_from_quantized_artifact(quantized_notes_artifact)
        if not notes:
            notes, measure_note_ids = self._build_notes_from_measures(pitch_result)
        if not notes:
            notes = self._build_notes_from_analysis_lead(pitch_result, analysis_ir)
        if not notes:
            notes = self._build_notes_from_raw(pitch_result)
        if notes:
            measure_note_ids = self._build_measure_note_ids_from_notes(pitch_result, notes, measure_note_ids)

        measures = (
            self._build_measures_from_score_notes(notes, measure_note_ids)
            if quantized_notes_artifact is not None and notes
            else self._build_measures(pitch_result, measure_note_ids)
        )
        instrumental_melody_notes = self._build_instrumental_melody_notes(pitch_result, measures)
        bassline_notes = self._build_bassline_notes(analysis_ir, measures)
        chord_timeline = self._build_chord_timeline(analysis_ir)
        form_sections = self._build_form_sections(analysis_ir)
        lyric_segments = self._build_lyrics_segments(normalized_lyrics)
        analysis_hints = self._build_analysis_hints(pitch_result.analysis_info)
        meta = self._build_meta(pitch_result, analysis_ir)
        if quantized_notes_artifact is not None and notes:
            meta.analysis_info = dict(meta.analysis_info or {})
            meta.analysis_info["lead_note_source"] = "quantized_notes"
            meta.analysis_info["timing_origin"] = "performance_time_from_quantized_notes"
            meta.analysis_info["notation_timing_origin"] = "quantized_grid_from_quantized_notes"
            meta.analysis_info["quantizer_backend"] = quantized_notes_artifact.get("quantizer_backend")
            meta.analysis_info["quantized_note_count"] = len(quantized_notes_artifact.get("notes") or [])
            meta.analysis_info["score_ir_lead_note_count"] = len(notes)
            meta.total_measures = len(measures)
            if notes:
                meta.duration_sec = max(float(meta.duration_sec or 0.0), max(float(note.end_time) for note in notes))
            analysis_hints.quantize_mode = str(quantized_notes_artifact.get("quantizer_backend") or "") or None

        issue_spots = self._detect_issue_spots(
            meta=meta,
            notes=notes,
            measures=measures,
            lyrics_segments=lyric_segments,
            analysis_hints=analysis_hints,
        )
        analysis_hints.issue_count = len(issue_spots)
        self._validate_production_lineage(pitch_result=pitch_result, notes=notes)

        return ScoreIR(
            meta=meta,
            notes=notes,
            instrumental_melody_notes=instrumental_melody_notes,
            bassline_notes=bassline_notes,
            measures=measures,
            chord_timeline=chord_timeline,
            form_sections=form_sections,
            lyrics_segments=lyric_segments,
            analysis_hints=analysis_hints,
            issue_spots=issue_spots,
            warnings=self._merge_unique_strings(
                list(pitch_result.warnings or []),
                list(getattr(analysis_ir, "warnings", []) or []),
            ),
        )

    def _validate_production_lineage(
        self,
        *,
        pitch_result: PitchAnalysisResult,
        notes: List[ScoreNote],
    ) -> None:
        analysis_info = dict(getattr(pitch_result, "analysis_info", {}) or {})
        lead_note_source = str(analysis_info.get("lead_note_source") or "")
        authoritative_selection = bool(analysis_info.get("lead_selection_authoritative"))
        has_quantized_notes = any(note.source == "quantized_notes" for note in notes)
        violations: List[str] = []
        if lead_note_source == "quantized_notes" or authoritative_selection or has_quantized_notes:
            missing_source_ids = [note.id for note in notes if not self._safe_optional_str(note.source_candidate_id)]
            missing_quantized_ids = [
                note.id
                for note in notes
                if note.source == "quantized_notes" and not self._safe_optional_str(note.quantized_note_id)
            ]
            missing_source_id_sets = [
                note.id for note in notes if note.source == "quantized_notes" and not list(note.source_candidate_ids or [])
            ]
            missing_contour_ids = [
                note.id for note in notes if note.source == "quantized_notes" and not list(note.source_contour_ids or [])
            ]
            missing_f0_ranges = [
                note.id for note in notes if note.source == "quantized_notes" and not dict(note.source_f0_frame_range or {})
            ]
            if missing_source_ids:
                violations.append("missing_source_candidate_id:" + ",".join(missing_source_ids[:20]))
            if missing_quantized_ids:
                violations.append("missing_quantized_note_id:" + ",".join(missing_quantized_ids[:20]))
            if missing_source_id_sets:
                violations.append("missing_source_candidate_ids:" + ",".join(missing_source_id_sets[:20]))
            if missing_contour_ids:
                violations.append("missing_source_contour_ids:" + ",".join(missing_contour_ids[:20]))
            if missing_f0_ranges:
                violations.append("missing_source_f0_frame_range:" + ",".join(missing_f0_ranges[:20]))
        if not notes and authoritative_selection:
            violations.append("authoritative_selection_empty")
        if violations:
            raise RuntimeError("score_ir_lineage_contract_failed:" + ";".join(violations))

    def _build_notes_from_quantized_artifact(
        self,
        quantized_notes_artifact: dict[str, Any] | None,
    ) -> Tuple[List[ScoreNote], List[List[str]]]:
        if not isinstance(quantized_notes_artifact, dict):
            return [], []
        raw_notes = quantized_notes_artifact.get("notes")
        if not isinstance(raw_notes, list) or not raw_notes:
            return [], []

        notes: List[ScoreNote] = []
        measure_note_ids: List[List[str]] = []
        for idx, raw_note in enumerate(raw_notes, start=1):
            if not isinstance(raw_note, dict):
                continue
            score_note = self._score_note_from_quantized_artifact(raw_note, idx)
            if score_note is None:
                continue
            notes.append(score_note)
            measure_num = score_note.measure_num or 1
            while len(measure_note_ids) < measure_num:
                measure_note_ids.append([])
            measure_note_ids[measure_num - 1].append(score_note.id)
        return notes, measure_note_ids

    def _score_note_from_quantized_artifact(self, raw_note: dict[str, Any], index: int) -> ScoreNote | None:
        start_time = self._safe_float(
            raw_note.get("start_time_sec"),
            self._safe_float(raw_note.get("quantized_start_time_sec"), 0.0),
        )
        end_time = self._safe_float(
            raw_note.get("end_time_sec"),
            self._safe_float(raw_note.get("quantized_end_time_sec"), start_time),
        )
        if end_time <= start_time:
            return None
        pitch_midi = self._safe_optional_int(raw_note.get("pitch_midi"))
        pitch = self._safe_optional_str(raw_note.get("pitch"))
        if not pitch and pitch_midi is not None:
            pitch = self._midi_to_note(pitch_midi)
        if not pitch:
            return None
        measure_num = self._safe_optional_int(raw_note.get("measure_num"))
        if measure_num is None:
            measure_index = self._safe_optional_int(raw_note.get("measure_index"))
            measure_num = measure_index + 1 if measure_index is not None else 1
        source_candidate_id = self._safe_optional_str(raw_note.get("source_candidate_id"))
        source_candidate_ids = self._unique_strings(
            [source_candidate_id] + list(raw_note.get("source_candidate_ids") or [])
        )
        reason_codes = list(raw_note.get("reason_codes") or [])
        quantized_start_time = self._safe_optional_float(raw_note.get("quantized_start_time_sec"))
        quantized_end_time = self._safe_optional_float(raw_note.get("quantized_end_time_sec"))
        quantized_duration = self._safe_optional_float(raw_note.get("quantized_duration_sec"))
        if quantized_duration is None and quantized_start_time is not None and quantized_end_time is not None:
            quantized_duration = max(0.0, quantized_end_time - quantized_start_time)
        return ScoreNote(
            id=f"n{index:06d}",
            pitch=pitch,
            pitch_midi=pitch_midi,
            start_time=start_time,
            end_time=end_time,
            duration_sec=max(0.0, end_time - start_time),
            duration_beats=self._safe_optional_float(raw_note.get("duration_beats")),
            note_type=self._note_type_from_duration_beats(raw_note.get("duration_beats")),
            measure_num=measure_num,
            beat_position=self._safe_optional_float(raw_note.get("beat_in_measure")),
            confidence=self._safe_float(raw_note.get("confidence"), 0.0),
            lyric=None,
            is_raw=False,
            is_candidate_ornament=False,
            tie_candidate=False,
            source="quantized_notes",
            source_candidate_id=source_candidate_id,
            source_candidate_ids=source_candidate_ids,
            source_contour_ids=self._unique_strings(raw_note.get("source_contour_ids") or []),
            source_f0_frame_range=dict(raw_note.get("source_f0_frame_range") or {}),
            quantized_note_id=self._safe_optional_str(raw_note.get("id")),
            timing_origin="performance_time_from_quantized_notes",
            performance_start_time_sec=start_time,
            performance_end_time_sec=end_time,
            quantized_start_time_sec=quantized_start_time,
            quantized_end_time_sec=quantized_end_time,
            quantized_duration_sec=quantized_duration,
            uncertain=bool(raw_note.get("uncertain")) or bool(reason_codes),
            reason_codes=reason_codes,
        )

    def _build_notes_from_measures(
        self,
        pitch_result: PitchAnalysisResult,
    ) -> Tuple[List[ScoreNote], List[List[str]]]:
        notes: List[ScoreNote] = []
        measure_note_ids: List[List[str]] = []

        beats_per_measure = self._parse_beats_per_measure(getattr(pitch_result.meta, "time_signature", None))
        note_index = 1

        for measure in pitch_result.measures or []:
            current_measure_ids: List[str] = []
            measure_num = self._safe_int(measure.get("measure_num"))
            raw_notes = measure.get("notes", [])

            if not isinstance(raw_notes, list):
                raw_notes = []

            for raw_note in raw_notes:
                if not isinstance(raw_note, dict):
                    continue

                start_time = self._safe_float(raw_note.get("start_time"), 0.0)
                end_time = self._safe_float(raw_note.get("end_time"), start_time)
                if end_time < start_time:
                    end_time = start_time

                duration_beats = self._safe_optional_float(raw_note.get("duration_beats"))
                confidence = self._safe_float(raw_note.get("confidence"), 0.0)

                note_id = f"n{note_index:06d}"
                note_index += 1

                score_note = ScoreNote(
                    id=note_id,
                    pitch=str(raw_note.get("pitch", "")),
                    pitch_midi=self._to_midi(raw_note.get("pitch")),
                    start_time=start_time,
                    end_time=end_time,
                    duration_sec=max(0.0, end_time - start_time),
                    duration_beats=duration_beats,
                    note_type=self._safe_optional_str(raw_note.get("note_type")),
                    measure_num=measure_num,
                    beat_position=self._safe_optional_float(raw_note.get("beat_position")),
                    confidence=confidence,
                    lyric=self._safe_optional_str(raw_note.get("lyric")),
                    is_raw=False,
                    is_candidate_ornament=self._is_candidate_ornament(duration_beats, confidence),
                    tie_candidate=self._is_tie_candidate(duration_beats, beats_per_measure),
                    source="measure_note",
                    source_candidate_id=self._safe_optional_str(raw_note.get("source_candidate_id"))
                    or self._safe_optional_str(raw_note.get("candidate_id")),
                    source_candidate_ids=self._unique_strings(
                        [raw_note.get("source_candidate_id"), raw_note.get("candidate_id")]
                        + list(raw_note.get("source_candidate_ids") or [])
                    ),
                    source_contour_ids=self._unique_strings(raw_note.get("source_contour_ids") or []),
                    source_f0_frame_range=dict(raw_note.get("source_f0_frame_range") or {}),
                    quantized_note_id=self._safe_optional_str(raw_note.get("quantized_note_id")),
                    reason_codes=list(raw_note.get("reason_codes") or []),
                    uncertain=bool(raw_note.get("reason_codes")),
                )
                notes.append(score_note)
                current_measure_ids.append(note_id)

            measure_note_ids.append(current_measure_ids)

        return notes, measure_note_ids

    def _build_notes_from_raw(self, pitch_result: PitchAnalysisResult) -> List[ScoreNote]:
        notes: List[ScoreNote] = []
        note_index = 1

        lead_like_notes = list(getattr(pitch_result, "lead_notes", None) or [])
        fallback_source = "lead_note"
        is_raw_note = False
        if not lead_like_notes:
            analysis_info = dict(getattr(pitch_result, "analysis_info", {}) or {})
            if bool(analysis_info.get("lead_selection_authoritative")):
                return []
            lead_like_notes = list(pitch_result.raw_notes or [])
            fallback_source = "raw_note"
            is_raw_note = True

        for raw_note in lead_like_notes:
            start_time = self._safe_float(getattr(raw_note, "start_time", 0.0), 0.0)
            end_time = self._safe_float(getattr(raw_note, "end_time", start_time), start_time)
            if end_time < start_time:
                end_time = start_time

            note_id = f"n{note_index:06d}"
            note_index += 1
            confidence = self._safe_float(getattr(raw_note, "confidence", 0.0), 0.0)

            notes.append(
                ScoreNote(
                    id=note_id,
                    pitch=str(getattr(raw_note, "pitch", "")),
                    pitch_midi=self._to_midi(getattr(raw_note, "pitch", None)),
                    start_time=start_time,
                    end_time=end_time,
                    duration_sec=max(0.0, end_time - start_time),
                    duration_beats=None,
                    note_type=None,
                    measure_num=self._find_measure_num_for_time(start_time, list(getattr(pitch_result, "measures", None) or [])),
                    beat_position=None,
                    confidence=confidence,
                    lyric=None,
                    is_raw=is_raw_note,
                    is_candidate_ornament=self._is_candidate_ornament(None, confidence),
                    tie_candidate=False,
                    source=fallback_source,
                    source_candidate_id=self._safe_optional_str(getattr(raw_note, "source_candidate_id", None))
                    or self._safe_optional_str(getattr(raw_note, "candidate_id", None)),
                    source_candidate_ids=self._unique_strings(
                        [getattr(raw_note, "source_candidate_id", None), getattr(raw_note, "candidate_id", None)]
                        + list(getattr(raw_note, "source_candidate_ids", []) or [])
                    ),
                    source_contour_ids=self._unique_strings(getattr(raw_note, "source_contour_ids", []) or []),
                    source_f0_frame_range=dict(getattr(raw_note, "source_f0_frame_range", {}) or {}),
                    quantized_note_id=self._safe_optional_str(getattr(raw_note, "quantized_note_id", None)),
                    uncertain=bool(getattr(raw_note, "uncertain", False)),
                    reason_codes=list(getattr(raw_note, "reason_codes", []) or []),
                )
            )

        return notes

    def _build_measure_note_ids_from_notes(
        self,
        pitch_result: PitchAnalysisResult,
        notes: List[ScoreNote],
        existing: List[List[str]],
    ) -> List[List[str]]:
        measure_count = len(getattr(pitch_result, "measures", None) or [])
        if measure_count <= 0:
            return existing
        if existing and any(note_ids for note_ids in existing):
            return existing

        indexed: List[List[str]] = [[] for _ in range(measure_count)]
        for note in notes:
            measure_num = note.measure_num
            if measure_num is None:
                measure_num = self._find_measure_num_for_time(
                    note.start_time,
                    list(getattr(pitch_result, "measures", None) or []),
                )
            if measure_num is None:
                continue
            idx = int(measure_num) - 1
            if 0 <= idx < measure_count:
                indexed[idx].append(note.id)
        return indexed

    def _build_notes_from_analysis_lead(
        self,
        pitch_result: PitchAnalysisResult,
        analysis_ir: AnalysisIR | None,
    ) -> List[ScoreNote]:
        selected_lead = list(getattr(analysis_ir, "selected_lead_melody", None) or [])
        if not selected_lead:
            return []
        return self._build_score_notes_from_note_list(
            notes=selected_lead,
            source="analysis_ir_lead",
            id_prefix="n",
            is_raw=False,
            measures_hint=list(getattr(pitch_result, "measures", None) or []),
        )

    def _build_bassline_notes(
        self,
        analysis_ir: AnalysisIR | None,
        measures: List[ScoreMeasure],
    ) -> List[ScoreNote]:
        selected_bassline = list(getattr(analysis_ir, "selected_bassline", None) or [])
        if not selected_bassline:
            return []
        return self._build_score_notes_from_note_list(
            notes=selected_bassline,
            source="analysis_ir_bass",
            id_prefix="b",
            is_raw=False,
            measures_hint=measures,
        )

    def _build_instrumental_melody_notes(
        self,
        pitch_result: PitchAnalysisResult,
        measures: List[ScoreMeasure],
    ) -> List[ScoreNote]:
        hook_notes = list(getattr(pitch_result, "instrumental_melody_notes", None) or [])
        if not hook_notes:
            return []
        return self._build_score_notes_from_note_list(
            notes=hook_notes,
            source="instrumental_hook",
            id_prefix="ih",
            is_raw=False,
            measures_hint=measures,
        )

    def _build_score_notes_from_note_list(
        self,
        *,
        notes: List[Note],
        source: str,
        id_prefix: str,
        is_raw: bool,
        measures_hint: List[Any] | None = None,
    ) -> List[ScoreNote]:
        built: List[ScoreNote] = []
        for idx, note in enumerate(notes, start=1):
            start_time = self._safe_float(getattr(note, "start_time", 0.0), 0.0)
            end_time = self._safe_float(getattr(note, "end_time", start_time), start_time)
            if end_time < start_time:
                end_time = start_time
            measure_num = self._find_measure_num_for_time(start_time, measures_hint or [])
            raw_measure_num = getattr(note, "measure_num", None)
            if raw_measure_num is not None:
                measure_num = self._safe_optional_int(raw_measure_num)
            confidence = self._safe_float(getattr(note, "confidence", 0.0), 0.0)
            note_id = f"{id_prefix}{idx:06d}"

            built.append(
                ScoreNote(
                    id=note_id,
                    pitch=str(getattr(note, "pitch", "")),
                    pitch_midi=self._to_midi(getattr(note, "pitch", None)),
                    start_time=start_time,
                    end_time=end_time,
                    duration_sec=max(0.0, end_time - start_time),
                    duration_beats=self._safe_optional_float(getattr(note, "duration_beats", None)),
                    note_type=self._safe_optional_str(getattr(note, "note_type", None)),
                    measure_num=measure_num,
                    beat_position=self._safe_optional_float(getattr(note, "beat_position", None)),
                    confidence=confidence,
                    lyric=None,
                    is_raw=is_raw,
                    is_candidate_ornament=self._is_candidate_ornament(None, confidence),
                    tie_candidate=False,
                    source=source,
                    source_candidate_id=self._safe_optional_str(getattr(note, "source_candidate_id", None))
                    or self._safe_optional_str(getattr(note, "candidate_id", None))
                    or self._safe_optional_str(getattr(note, "id", None)),
                    source_candidate_ids=self._unique_strings(
                        [
                            getattr(note, "source_candidate_id", None),
                            getattr(note, "candidate_id", None),
                            getattr(note, "id", None),
                        ]
                        + list(getattr(note, "source_candidate_ids", []) or [])
                    ),
                    source_contour_ids=self._unique_strings(getattr(note, "source_contour_ids", []) or []),
                    source_f0_frame_range=dict(getattr(note, "source_f0_frame_range", {}) or {}),
                    quantized_note_id=self._safe_optional_str(getattr(note, "quantized_note_id", None)),
                    uncertain=bool(getattr(note, "uncertain", False)),
                    reason_codes=list(getattr(note, "reason_codes", []) or []),
                )
            )
        return built

    def _build_measures_from_score_notes(
        self,
        notes: List[ScoreNote],
        measure_note_ids: List[List[str]],
    ) -> List[ScoreMeasure]:
        if not notes:
            return []
        measure_ids_by_num: Dict[int, List[str]] = {}
        for idx, note_ids in enumerate(measure_note_ids or [], start=1):
            if note_ids:
                measure_ids_by_num.setdefault(idx, []).extend(list(note_ids))
        for note in notes:
            measure_num = int(note.measure_num or 1)
            measure_ids_by_num.setdefault(measure_num, [])
            if note.id not in measure_ids_by_num[measure_num]:
                measure_ids_by_num[measure_num].append(note.id)

        measures: List[ScoreMeasure] = []
        for measure_num in sorted(measure_ids_by_num):
            measure_notes = [note for note in notes if note.id in set(measure_ids_by_num.get(measure_num) or [])]
            if not measure_notes:
                continue
            start_time = min(float(note.start_time) for note in measure_notes)
            end_time = max(float(note.end_time) for note in measure_notes)
            measures.append(
                ScoreMeasure(
                    measure_num=measure_num,
                    start_time=start_time,
                    end_time=end_time,
                    duration_sec=max(0.0, end_time - start_time),
                    is_anacrusis=False,
                    note_ids=list(measure_ids_by_num.get(measure_num) or []),
                )
            )
        return measures

    def _build_measures(
        self,
        pitch_result: PitchAnalysisResult,
        measure_note_ids: List[List[str]],
    ) -> List[ScoreMeasure]:
        measures: List[ScoreMeasure] = []

        for idx, measure in enumerate(pitch_result.measures or []):
            if not isinstance(measure, dict):
                continue

            start_time = self._safe_float(measure.get("start_time"), 0.0)
            end_time = self._safe_float(measure.get("end_time"), start_time)
            if end_time < start_time:
                end_time = start_time

            note_ids = measure_note_ids[idx] if idx < len(measure_note_ids) else []

            measures.append(
                ScoreMeasure(
                    measure_num=self._safe_int(measure.get("measure_num"), idx + 1),
                    start_time=start_time,
                    end_time=end_time,
                    duration_sec=max(0.0, end_time - start_time),
                    is_anacrusis=bool(measure.get("is_anacrusis", False)),
                    note_ids=note_ids,
                )
            )

        return measures

    def _build_chord_timeline(self, analysis_ir: AnalysisIR | None) -> List[ScoreChord]:
        chords: List[ScoreChord] = []
        for idx, chord in enumerate(getattr(analysis_ir, "chord_timeline", None) or [], start=1):
            chords.append(
                ScoreChord(
                    id=f"ch{idx:05d}",
                    start_time=self._safe_float(getattr(chord, "start_time", 0.0), 0.0),
                    end_time=self._safe_float(getattr(chord, "end_time", 0.0), 0.0),
                    measure_num=self._safe_optional_int(getattr(chord, "measure_num", None)),
                    symbol=str(getattr(chord, "symbol", "")),
                    root=str(getattr(chord, "root", "")),
                    quality=str(getattr(chord, "quality", "")),
                    bass=self._safe_optional_str(getattr(chord, "bass", None)),
                    confidence=self._safe_float(getattr(chord, "confidence", 0.0), 0.0),
                    evidence=dict(getattr(chord, "evidence", {}) or {}),
                )
            )
        return chords

    def _build_form_sections(self, analysis_ir: AnalysisIR | None) -> List[ScoreSection]:
        sections: List[ScoreSection] = []
        for idx, section in enumerate(getattr(analysis_ir, "form_sections", None) or [], start=1):
            section_id = self._safe_optional_str(getattr(section, "id", None)) or f"section_{idx:03d}"
            sections.append(
                ScoreSection(
                    id=section_id,
                    label=str(getattr(section, "label", section_id)),
                    start_time=self._safe_float(getattr(section, "start_time", 0.0), 0.0),
                    end_time=self._safe_float(getattr(section, "end_time", 0.0), 0.0),
                    measure_start=self._safe_optional_int(getattr(section, "measure_start", None)),
                    measure_end=self._safe_optional_int(getattr(section, "measure_end", None)),
                    confidence=self._safe_float(getattr(section, "confidence", 0.0), 0.0),
                    evidence=dict(getattr(section, "evidence", {}) or {}),
                )
            )
        return sections

    def _build_lyrics_segments(self, lyrics_segments: list[dict]) -> List[LyricsSegment]:
        segments: List[LyricsSegment] = []
        token_index = 1

        for idx, seg in enumerate(lyrics_segments):
            if not isinstance(seg, dict):
                continue

            segment_id = f"seg{idx + 1:04d}"
            text = str(seg.get("text", "")).strip()
            start = self._safe_float(seg.get("start"), 0.0)
            end = self._safe_float(seg.get("end"), start)
            if end < start:
                end = start

            token_texts = self._tokenize_text(text)
            tokens: List[LyricsToken] = []
            for i, token_text in enumerate(token_texts):
                token_id = f"tok{token_index:06d}"
                token_index += 1
                tokens.append(
                    LyricsToken(
                        id=token_id,
                        text=token_text,
                        segment_id=segment_id,
                        lang=self._infer_token_lang(token_text),
                        index_in_segment=i,
                    )
                )

            segments.append(
                LyricsSegment(
                    id=segment_id,
                    start=start,
                    end=end,
                    text=text,
                    raw_text=text,
                    tokens=tokens,
                )
            )

        return segments

    def _tokenize_text(self, text: str) -> List[str]:
        normalized = " ".join((text or "").strip().split())
        if not normalized:
            return []

        tokens = self._MIXED_TOKEN_PATTERN.findall(normalized)
        cleaned: List[str] = []

        for tok in tokens:
            stripped = tok.strip()
            if not stripped:
                continue
            if self._PUNCT_ONLY_PATTERN.match(stripped):
                continue
            cleaned.append(stripped)

        return cleaned

    def _infer_token_lang(self, token: str) -> Optional[str]:
        if self._ZH_PATTERN.search(token):
            return "zh"
        if self._EN_PATTERN.search(token):
            return "en"
        return None

    def _build_analysis_hints(self, analysis_info: Dict[str, Any]) -> AnalysisHints:
        info = analysis_info or {}
        return AnalysisHints(
            downbeat_confidence=self._safe_optional_float(info.get("downbeat_confidence")),
            rhythm_stability=self._safe_optional_float(info.get("rhythm_stability")),
            has_accompaniment=self._safe_optional_bool(info.get("has_accompaniment")),
            detector=self._safe_optional_str(info.get("detector")),
            beat_backend=self._safe_optional_str(info.get("beat_backend")),
            key_backend=self._safe_optional_str(info.get("key_backend")),
            quantize_mode=self._safe_optional_str(info.get("quantize_mode")),
        )

    def _detect_issue_spots(
        self,
        meta: ScoreMeta,
        notes: List[ScoreNote],
        measures: List[ScoreMeasure],
        lyrics_segments: List[LyricsSegment],
        analysis_hints: AnalysisHints,
    ) -> List[IssueSpot]:
        issues: List[IssueSpot] = []
        note_by_id = {note.id: note for note in notes}

        for measure in measures:
            if not measure.note_ids:
                issues.append(
                    IssueSpot(
                        type="empty_measure",
                        severity="medium",
                        measure_num=measure.measure_num,
                        note_ids=[],
                        segment_ids=[],
                        message="Measure has no notes.",
                    )
                )
                continue

            measure_notes = [note_by_id[nid] for nid in measure.note_ids if nid in note_by_id]
            short_or_ornament = 0
            for note in measure_notes:
                if note.is_candidate_ornament:
                    short_or_ornament += 1
                    continue
                if note.duration_beats is not None and note.duration_beats <= 0.25:
                    short_or_ornament += 1

            if len(measure_notes) >= 3 and (short_or_ornament / len(measure_notes)) >= 0.5:
                issues.append(
                    IssueSpot(
                        type="dense_short_notes",
                        severity="medium",
                        measure_num=measure.measure_num,
                        note_ids=[n.id for n in measure_notes],
                        segment_ids=[],
                        message="High ratio of short/ornamental notes in measure.",
                    )
                )

        total_tokens = sum(len(seg.tokens) for seg in lyrics_segments)
        total_notes = len(notes)
        if self._is_count_mismatch(total_notes=total_notes, total_tokens=total_tokens):
            issues.append(
                IssueSpot(
                    type="lyrics_note_count_mismatch",
                    severity="low",
                    measure_num=None,
                    note_ids=[n.id for n in notes],
                    segment_ids=[seg.id for seg in lyrics_segments],
                    message=f"Global count mismatch: notes={total_notes}, lyric_tokens={total_tokens}.",
                )
            )

        if meta.key_confidence < 0.2:
            issues.append(
                IssueSpot(
                    type="low_key_confidence",
                    severity="high",
                    measure_num=None,
                    note_ids=[],
                    segment_ids=[],
                    message=f"Low key confidence ({meta.key_confidence:.3f}).",
                )
            )

        if (
            analysis_hints.downbeat_confidence is not None
            and analysis_hints.downbeat_confidence < 0.35
        ):
            issues.append(
                IssueSpot(
                    type="low_downbeat_confidence",
                    severity="medium",
                    measure_num=None,
                    note_ids=[],
                    segment_ids=[],
                    message=(
                        f"Low downbeat confidence "
                        f"({analysis_hints.downbeat_confidence:.3f})."
                    ),
                )
            )

        return issues

    def _build_meta(self, pitch_result: PitchAnalysisResult, analysis_ir: AnalysisIR | None = None) -> ScoreMeta:
        meta = pitch_result.meta
        has_anacrusis = any(
            bool(measure.get("is_anacrusis", False))
            for measure in (pitch_result.measures or [])
            if isinstance(measure, dict)
        )
        analysis_info = dict(pitch_result.analysis_info or {})
        if analysis_ir is not None:
            analysis_info["analysis_ir_version"] = self._safe_optional_str(getattr(analysis_ir, "version", None))
            analysis_info["analysis_ir_confidence"] = self._safe_float(getattr(analysis_ir, "confidence", 0.0), 0.0)
            analysis_info["analysis_ir_chord_count"] = len(getattr(analysis_ir, "chord_timeline", None) or [])
            analysis_info["analysis_ir_form_section_count"] = len(getattr(analysis_ir, "form_sections", None) or [])
            analysis_info["analysis_ir_bassline_count"] = len(getattr(analysis_ir, "selected_bassline", None) or [])

        return ScoreMeta(
            source_version=str(getattr(pitch_result, "version", "")),
            bpm=self._safe_float(getattr(meta, "bpm", 0.0), 0.0),
            bpm_confidence=self._safe_float(getattr(meta, "bpm_confidence", 0.0), 0.0),
            key=str(getattr(meta, "key", "")),
            key_confidence=self._safe_float(getattr(meta, "key_confidence", 0.0), 0.0),
            duration_sec=self._safe_float(getattr(meta, "duration_sec", 0.0), 0.0),
            time_signature=str(getattr(meta, "time_signature", "4/4")),
            rhythm_type=str(getattr(meta, "rhythm_type", "stable")),
            total_measures=self._safe_optional_int(getattr(meta, "total_measures", None)),
            has_anacrusis=has_anacrusis,
            analysis_info=analysis_info,
        )

    def _is_candidate_ornament(
        self,
        duration_beats: Optional[float],
        confidence: float,
    ) -> bool:
        if duration_beats is not None and duration_beats <= 0.25:
            return True
        return confidence < 0.55

    def _is_tie_candidate(
        self,
        duration_beats: Optional[float],
        beats_per_measure: Optional[float],
    ) -> bool:
        if duration_beats is None or beats_per_measure is None:
            return False
        return duration_beats >= beats_per_measure

    def _parse_beats_per_measure(self, time_signature: Optional[str]) -> Optional[float]:
        if not time_signature:
            return None

        parts = str(time_signature).split("/", 1)
        if not parts:
            return None

        try:
            beats = float(parts[0])
            return beats if beats > 0 else None
        except (TypeError, ValueError):
            return None

    def _to_midi(self, pitch: Any) -> Optional[int]:
        if not pitch:
            return None
        try:
            return int(note_to_midi(str(pitch)))
        except Exception:
            return None

    def _midi_to_note(self, midi_value: int) -> str:
        names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        midi_int = int(midi_value)
        return f"{names[midi_int % 12]}{(midi_int // 12) - 1}"

    def _note_type_from_duration_beats(self, value: Any) -> Optional[str]:
        duration = self._safe_optional_float(value)
        if duration is None:
            return None
        if duration >= 3.75:
            return "whole"
        if duration >= 1.75:
            return "half"
        if duration >= 1.375:
            return "dotted_quarter"
        if duration >= 0.875:
            return "quarter"
        if duration >= 0.625:
            return "dotted_eighth"
        if duration >= 0.375:
            return "eighth"
        if duration >= 0.1875:
            return "sixteenth"
        return "thirty_second"

    def _is_count_mismatch(self, total_notes: int, total_tokens: int) -> bool:
        if total_notes == total_tokens:
            return False
        if total_notes == 0 and total_tokens > 0:
            return True
        if total_tokens == 0 and total_notes > 0:
            return True

        small = min(total_notes, total_tokens)
        large = max(total_notes, total_tokens)
        if small <= 0:
            return large > 0

        return (large / small) >= 1.8 and (large - small) >= 5

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_optional_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_optional_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _safe_optional_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _safe_optional_bool(self, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
            return None
        return bool(value)

    def _find_measure_num_for_time(self, start_time: float, measures_hint: List[Any]) -> Optional[int]:
        for idx, measure in enumerate(measures_hint):
            if isinstance(measure, ScoreMeasure):
                measure_num = measure.measure_num
                measure_start = measure.start_time
                measure_end = measure.end_time
            elif isinstance(measure, dict):
                measure_num = self._safe_int(measure.get("measure_num"), idx + 1)
                measure_start = self._safe_float(measure.get("start_time"), 0.0)
                measure_end = self._safe_float(measure.get("end_time"), measure_start)
            else:
                continue

            if measure_end < measure_start:
                measure_end = measure_start
            if measure_start <= start_time < measure_end:
                return measure_num

        if measures_hint:
            last = measures_hint[-1]
            if isinstance(last, ScoreMeasure):
                if start_time >= last.end_time:
                    return last.measure_num
            elif isinstance(last, dict):
                measure_num = self._safe_int(last.get("measure_num"), len(measures_hint))
                measure_end = self._safe_float(last.get("end_time"), 0.0)
                if start_time >= measure_end:
                    return measure_num
        return None

    def _merge_unique_strings(self, *chunks: List[str]) -> List[str]:
        merged: List[str] = []
        for chunk in chunks:
            for item in chunk or []:
                text = str(item).strip()
                if text and text not in merged:
                    merged.append(text)
        return merged

    def _unique_strings(self, values: Any) -> List[str]:
        if values is None:
            return []
        if isinstance(values, (str, int, float)):
            iterable = [values]
        else:
            try:
                iterable = list(values)
            except TypeError:
                iterable = [values]
        unique: List[str] = []
        for value in iterable:
            if value is None:
                continue
            text = str(value).strip()
            if text and text not in unique:
                unique.append(text)
        return unique
