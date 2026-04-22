from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.modules.pitch.note_utils import note_to_midi
from app.modules.pitch.types import Note, PitchAnalysisResult, SemanticAudioResult

from .types import AnalysisIR, AnalysisIRMeta, ChordSpan, FormSection

_PITCH_CLASS_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


@dataclass(frozen=True)
class _MeasureWindow:
    measure_num: int
    start_time: float
    end_time: float


class BaselineAnalysisInferencer:
    """Deterministic baseline inferencer over semantic audio observations."""

    VERSION = "analysis_ir_v1"

    def infer(
        self,
        pitch_result: PitchAnalysisResult,
        lyrics_segments: list[dict] | None = None,
    ) -> AnalysisIR:
        semantic_audio = getattr(pitch_result, "semantic_audio", None) or SemanticAudioResult()
        warnings: list[str] = []

        selected_lead = self._select_lead_melody(pitch_result, semantic_audio)
        selected_bass = self._select_bassline(semantic_audio.bass_root_candidates.notes)
        measure_windows = self._build_measure_windows(pitch_result)
        chord_timeline = self._infer_chord_timeline(
            measure_windows=measure_windows,
            harmony_notes=semantic_audio.harmony_candidates.notes,
            bass_notes=selected_bass,
            key=str(getattr(getattr(pitch_result, "meta", None), "key", "") or ""),
            warnings=warnings,
        )
        form_sections = self._infer_form_sections(
            measure_windows=measure_windows,
            duration_sec=float(getattr(getattr(pitch_result, "meta", None), "duration_sec", 0.0) or 0.0),
            lyrics_segments=lyrics_segments or [],
        )

        confidence = self._estimate_confidence(
            lead_count=len(selected_lead),
            chord_count=len(chord_timeline),
            bass_count=len(selected_bass),
        )
        evidence = {
            "melody_candidate_count": len(semantic_audio.melody_candidates.notes),
            "lead_selected_count": len(selected_lead),
            "harmony_candidate_count": len(semantic_audio.harmony_candidates.notes),
            "bass_candidate_count": len(semantic_audio.bass_root_candidates.notes),
            "measure_window_count": len(measure_windows),
            "form_section_count": len(form_sections),
        }

        meta = AnalysisIRMeta(
            source_version=str(getattr(pitch_result, "version", "")),
            bpm=float(getattr(getattr(pitch_result, "meta", None), "bpm", 0.0) or 0.0),
            key=str(getattr(getattr(pitch_result, "meta", None), "key", "") or ""),
            time_signature=str(getattr(getattr(pitch_result, "meta", None), "time_signature", "4/4") or "4/4"),
            duration_sec=float(getattr(getattr(pitch_result, "meta", None), "duration_sec", 0.0) or 0.0),
            total_measures=len(measure_windows) if measure_windows else None,
        )

        return AnalysisIR(
            version=self.VERSION,
            meta=meta,
            source_stems=dict(semantic_audio.source_stems or {}),
            lead_source_stem=semantic_audio.melody_candidates.source_stem,
            bass_source_stem=semantic_audio.bass_root_candidates.source_stem,
            selected_lead_melody=selected_lead,
            chord_timeline=chord_timeline,
            selected_bassline=selected_bass,
            form_sections=form_sections,
            confidence=confidence,
            evidence=evidence,
            warnings=warnings,
        )

    def _select_lead_melody(
        self,
        pitch_result: PitchAnalysisResult,
        semantic_audio: SemanticAudioResult,
    ) -> list[Note]:
        for candidate_collection in (
            getattr(pitch_result, "lead_notes", None),
            getattr(semantic_audio.melody_candidates, "selected_notes", None),
            getattr(semantic_audio.melody_candidates, "notes", None),
            getattr(pitch_result, "raw_notes", None),
        ):
            if candidate_collection:
                return self._clone_notes(candidate_collection)
        return []

    def _select_bassline(self, notes: Iterable[Note] | None) -> list[Note]:
        if not notes:
            return []

        sorted_notes = sorted(notes, key=lambda note: (float(note.start_time), float(note.end_time), -float(note.confidence)))
        selected: list[Note] = []
        for note in sorted_notes:
            if self._to_midi(note.pitch) is None:
                continue
            if not selected:
                selected.append(self._clone_note(note))
                continue

            prev = selected[-1]
            if float(note.start_time) < float(prev.end_time):
                prev_duration = max(0.0, float(prev.end_time) - float(prev.start_time))
                current_duration = max(0.0, float(note.end_time) - float(note.start_time))
                if current_duration > prev_duration or float(note.confidence) > float(prev.confidence):
                    selected[-1] = self._clone_note(note)
                continue

            selected.append(self._clone_note(note))
        return selected

    def _build_measure_windows(self, pitch_result: PitchAnalysisResult) -> list[_MeasureWindow]:
        windows: list[_MeasureWindow] = []
        for idx, measure in enumerate(getattr(pitch_result, "measures", None) or []):
            if not isinstance(measure, dict):
                continue
            start_time = self._safe_float(measure.get("start_time"), 0.0)
            end_time = self._safe_float(measure.get("end_time"), start_time)
            if end_time < start_time:
                end_time = start_time
            windows.append(
                _MeasureWindow(
                    measure_num=int(measure.get("measure_num") or (idx + 1)),
                    start_time=start_time,
                    end_time=end_time,
                )
            )

        if windows:
            return windows

        duration_sec = self._safe_float(getattr(getattr(pitch_result, "meta", None), "duration_sec", 0.0), 0.0)
        return [_MeasureWindow(measure_num=1, start_time=0.0, end_time=max(0.0, duration_sec))]

    def _infer_chord_timeline(
        self,
        *,
        measure_windows: list[_MeasureWindow],
        harmony_notes: list[Note],
        bass_notes: list[Note],
        key: str,
        warnings: list[str],
    ) -> list[ChordSpan]:
        chord_timeline: list[ChordSpan] = []
        tonic_pc = self._key_tonic_pitch_class(key)

        for window in measure_windows:
            harmony_window = self._notes_overlapping(harmony_notes, window.start_time, window.end_time)
            bass_window = self._notes_overlapping(bass_notes, window.start_time, window.end_time)
            if not harmony_window and not bass_window and tonic_pc is None:
                warnings.append(f"analysis_ir_no_harmonic_support_measure_{window.measure_num}")
                continue

            bass_pc = self._primary_pitch_class(bass_window)
            pitch_class_weights = self._weighted_pitch_classes(harmony_window)
            root_pc = bass_pc
            if root_pc is None and pitch_class_weights:
                root_pc = max(pitch_class_weights.items(), key=lambda item: item[1])[0]
            if root_pc is None:
                root_pc = tonic_pc
            if root_pc is None:
                warnings.append(f"analysis_ir_unknown_root_measure_{window.measure_num}")
                continue

            quality = self._infer_quality(root_pc, pitch_class_weights)
            root_name = _PITCH_CLASS_NAMES[root_pc]
            bass_name = _PITCH_CLASS_NAMES[bass_pc] if bass_pc is not None else None
            symbol = root_name + quality
            if bass_name is not None and bass_name != root_name:
                symbol = f"{symbol}/{bass_name}"

            avg_harmony_conf = self._average_confidence(harmony_window)
            avg_bass_conf = self._average_confidence(bass_window)
            confidence = max(
                0.2,
                min(
                    0.92,
                    0.35
                    + (0.25 * avg_harmony_conf)
                    + (0.2 * avg_bass_conf)
                    + (0.1 if bass_pc is not None else 0.0)
                    + (0.1 if len(pitch_class_weights) >= 2 else 0.0),
                ),
            )
            chord_timeline.append(
                ChordSpan(
                    start_time=window.start_time,
                    end_time=window.end_time,
                    measure_num=window.measure_num,
                    symbol=symbol,
                    root=root_name,
                    quality=quality or "major",
                    bass=bass_name,
                    confidence=round(confidence, 4),
                    evidence={
                        "harmony_note_count": len(harmony_window),
                        "bass_note_count": len(bass_window),
                        "pitch_classes": sorted(pitch_class_weights.keys()),
                        "method": "baseline_measure_harmonic_summary",
                    },
                )
            )

        return chord_timeline

    def _infer_form_sections(
        self,
        *,
        measure_windows: list[_MeasureWindow],
        duration_sec: float,
        lyrics_segments: list[dict],
    ) -> list[FormSection]:
        if measure_windows:
            start_time = measure_windows[0].start_time
            end_time = measure_windows[-1].end_time
            measure_start = measure_windows[0].measure_num
            measure_end = measure_windows[-1].measure_num
        else:
            start_time = 0.0
            end_time = max(0.0, duration_sec)
            measure_start = None
            measure_end = None

        return [
            FormSection(
                id="section_a",
                label="section_a",
                start_time=start_time,
                end_time=end_time,
                measure_start=measure_start,
                measure_end=measure_end,
                confidence=0.35 if lyrics_segments else 0.25,
                evidence={
                    "method": "baseline_single_section",
                    "lyrics_segment_count": len(lyrics_segments),
                    "measure_count": len(measure_windows),
                },
            )
        ]

    def _estimate_confidence(self, *, lead_count: int, chord_count: int, bass_count: int) -> float:
        raw = 0.2
        raw += min(0.3, 0.05 * lead_count)
        raw += min(0.3, 0.08 * chord_count)
        raw += min(0.2, 0.05 * bass_count)
        return round(max(0.0, min(0.95, raw)), 4)

    def _notes_overlapping(self, notes: Iterable[Note], start_time: float, end_time: float) -> list[Note]:
        return [
            self._clone_note(note)
            for note in notes
            if float(note.end_time) > float(start_time) and float(note.start_time) < float(end_time)
        ]

    def _weighted_pitch_classes(self, notes: list[Note]) -> dict[int, float]:
        weights: dict[int, float] = {}
        for note in notes:
            midi_value = self._to_midi(note.pitch)
            if midi_value is None:
                continue
            pitch_class = midi_value % 12
            duration = max(0.0, float(note.end_time) - float(note.start_time))
            weight = max(0.05, duration) * max(0.05, float(note.confidence))
            weights[pitch_class] = weights.get(pitch_class, 0.0) + weight
        return weights

    def _primary_pitch_class(self, notes: list[Note]) -> int | None:
        if not notes:
            return None
        ranked = sorted(
            notes,
            key=lambda note: (
                -max(0.0, float(note.end_time) - float(note.start_time)),
                -float(note.confidence),
                float(note.start_time),
            ),
        )
        for note in ranked:
            midi_value = self._to_midi(note.pitch)
            if midi_value is not None:
                return midi_value % 12
        return None

    def _infer_quality(self, root_pc: int, pitch_class_weights: dict[int, float]) -> str:
        if not pitch_class_weights:
            return ""

        intervals = {(pitch_class - root_pc) % 12 for pitch_class in pitch_class_weights.keys()}
        if {4, 7}.issubset(intervals):
            return ""
        if {3, 7}.issubset(intervals):
            return "m"
        if {3, 6}.issubset(intervals):
            return "dim"
        if {4, 8}.issubset(intervals):
            return "aug"
        if 7 in intervals:
            return "5"
        return ""

    def _key_tonic_pitch_class(self, key: str) -> int | None:
        tonic = str(key or "").strip().split(" ", 1)[0]
        if not tonic:
            return None
        try:
            return int(note_to_midi(f"{tonic}4")) % 12
        except Exception:
            return None

    def _average_confidence(self, notes: list[Note]) -> float:
        if not notes:
            return 0.0
        return max(0.0, min(1.0, sum(float(note.confidence) for note in notes) / len(notes)))

    def _to_midi(self, pitch: str) -> int | None:
        try:
            return int(note_to_midi(str(pitch)))
        except Exception:
            return None

    def _clone_notes(self, notes: Iterable[Note]) -> list[Note]:
        return [self._clone_note(note) for note in notes]

    def _clone_note(self, note: Note) -> Note:
        return Note(
            pitch=str(note.pitch),
            start_time=float(note.start_time),
            end_time=float(note.end_time),
            confidence=float(note.confidence),
        )

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
