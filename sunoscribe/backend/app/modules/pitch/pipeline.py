from __future__ import annotations

import librosa
import numpy as np

from .audio_utils import get_audio_duration
from .beat_tracker import BeatTracker
from .config import PitchDetectionConfig
from .detector import PitchDetector
from .downbeat_tracker import DownbeatTracker
from .exceptions import DownbeatTrackingError
from .key_analyzer import KeyAnalysisResult, KeyAnalyzer
from .melody_selector import MelodySelector
from .midi_exporter import MidiExporter
from .quantizer import NoteQuantizer
from .rhythm_analyzer import RhythmAnalyzer
from .types import (
    MetaInfo,
    Note,
    NoteCandidateSet,
    PitchAnalysisResult,
    PitchPipelineRequest,
    QuantizedNote,
    RhythmGrid,
    SemanticAudioResult,
)


class PitchPipeline:
    """Pitch pipeline with lead selection plus semantic candidate outputs."""

    VERSION = "1.4"

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.detector = PitchDetector(self.config)
        self.beat_tracker = BeatTracker(self.config)
        self.downbeat_tracker = DownbeatTracker(self.config)
        self.key_analyzer = KeyAnalyzer(self.config)
        self.melody_selector = MelodySelector(self.config)
        self.quantizer = NoteQuantizer(self.config)
        self.rhythm_analyzer = RhythmAnalyzer()
        self.midi_exporter = MidiExporter()

    def _build_measure_boundaries(self, downbeat_times: list[float], duration_sec: float) -> list[float]:
        boundaries = sorted(set(float(t) for t in downbeat_times if 0.0 <= t <= duration_sec))
        if not boundaries:
            return []
        if boundaries[0] > 0.2:
            boundaries = [0.0] + boundaries
        if boundaries[-1] < duration_sec:
            boundaries.append(duration_sec)
        return boundaries

    def _recompute_quantized_positions(
        self,
        notes: list[QuantizedNote],
        boundaries: list[float],
        beats_per_bar: int,
    ) -> None:
        if not notes or len(boundaries) < 2:
            return

        beats_per_bar = max(2, int(beats_per_bar))
        intervals = list(zip(boundaries[:-1], boundaries[1:]))

        for note in notes:
            timestamp = float(note.start_time)

            target_idx: int | None = None
            for idx, (measure_start, measure_end) in enumerate(intervals):
                if measure_start <= timestamp < measure_end:
                    target_idx = idx
                    break

            if target_idx is None:
                if timestamp >= boundaries[-1]:
                    target_idx = len(intervals) - 1
                else:
                    continue

            measure_start, measure_end = intervals[target_idx]
            bar_duration = max(1e-6, measure_end - measure_start)
            beat_duration = bar_duration / beats_per_bar

            note.measure_num = target_idx + 1
            note.beat_position = round(1.0 + (timestamp - measure_start) / beat_duration, 3)

    def _build_measures(
        self,
        notes: list[QuantizedNote],
        boundaries: list[float],
        beats_per_bar: int,
        beat_duration_sec: float,
    ) -> list[dict]:
        if len(boundaries) < 2:
            return []
        beats_per_bar = max(2, int(beats_per_bar))

        has_leading_zero_boundary = boundaries[0] == 0.0
        first_downbeat = boundaries[1] if has_leading_zero_boundary and len(boundaries) > 1 else boundaries[0]
        anacrusis_threshold = max(0.15, beat_duration_sec * 0.5)
        has_anacrusis = has_leading_zero_boundary and first_downbeat > anacrusis_threshold

        measures: list[dict] = []

        for idx in range(len(boundaries) - 1):
            measure_start, measure_end = boundaries[idx], boundaries[idx + 1]
            measure_num = idx + 1
            measure_notes = sorted(
                (note for note in notes if measure_start <= note.start_time < measure_end),
                key=lambda note: note.start_time,
            )

            bar_duration = max(1e-6, measure_end - measure_start)
            beat_duration = bar_duration / beats_per_bar

            packed_notes = []
            for note in measure_notes:
                beat_position = (
                    note.beat_position
                    if note.beat_position is not None
                    else 1.0 + (note.start_time - measure_start) / beat_duration
                )
                packed_notes.append(
                    {
                        "pitch": note.pitch,
                        "start_time": note.start_time,
                        "end_time": note.end_time,
                        "duration_beats": note.duration_beats,
                        "note_type": note.note_type.value,
                        "beat_position": round(float(beat_position), 3),
                        "lyric": note.lyric,
                        "confidence": note.confidence,
                    }
                )

            measures.append(
                {
                    "measure_num": measure_num,
                    "start_time": measure_start,
                    "end_time": measure_end,
                    "is_anacrusis": idx == 0 and has_anacrusis,
                    "notes": packed_notes,
                }
            )

        return measures

    def _normalize_request(self, audio_input: str | PitchPipelineRequest) -> PitchPipelineRequest:
        if isinstance(audio_input, PitchPipelineRequest):
            source_audio_path = audio_input.source_audio_path or audio_input.rhythm_audio_path or audio_input.lead_audio_path
            rhythm_audio_path = audio_input.rhythm_audio_path or source_audio_path or audio_input.lead_audio_path
            key_audio_path = (
                audio_input.key_audio_path
                or audio_input.harmony_audio_path
                or source_audio_path
                or rhythm_audio_path
                or audio_input.lead_audio_path
            )
            return PitchPipelineRequest(
                lead_audio_path=str(audio_input.lead_audio_path),
                source_audio_path=str(source_audio_path) if source_audio_path else None,
                rhythm_audio_path=str(rhythm_audio_path) if rhythm_audio_path else None,
                key_audio_path=str(key_audio_path) if key_audio_path else None,
                harmony_audio_path=str(audio_input.harmony_audio_path) if audio_input.harmony_audio_path else None,
                bass_audio_path=str(audio_input.bass_audio_path) if audio_input.bass_audio_path else None,
                source_stems={str(k): str(v) for k, v in (audio_input.source_stems or {}).items() if str(v).strip()},
            )

        lead_audio_path = str(audio_input)
        return PitchPipelineRequest(
            lead_audio_path=lead_audio_path,
            source_audio_path=lead_audio_path,
            rhythm_audio_path=lead_audio_path,
            key_audio_path=lead_audio_path,
        )

    def _build_path_stem_index(self, source_stems: dict[str, str]) -> dict[str, str]:
        index: dict[str, str] = {}
        for stem_name, path in (source_stems or {}).items():
            normalized_path = str(path or "").strip()
            if not normalized_path:
                continue
            index[normalized_path] = str(stem_name)
        return index

    def _infer_source_stem(
        self,
        audio_path: str | None,
        path_stem_index: dict[str, str],
        fallback: str | None = None,
    ) -> str | None:
        normalized_path = str(audio_path or "").strip()
        if normalized_path and normalized_path in path_stem_index:
            return path_stem_index[normalized_path]
        return fallback

    def _safe_detect_candidates(
        self,
        *,
        audio_path: str | None,
        cache: dict[str, list[Note]],
        warnings: list[str],
        role: str,
    ) -> list[Note]:
        normalized_path = str(audio_path or "").strip()
        if not normalized_path:
            return []
        if normalized_path in cache:
            return [
                Note(
                    pitch=str(note.pitch),
                    start_time=float(note.start_time),
                    end_time=float(note.end_time),
                    confidence=float(note.confidence),
                )
                for note in cache[normalized_path]
            ]

        try:
            detected = self.detector.detect(normalized_path)
        except Exception as exc:
            warnings.append(f"{role}_detection_failed:{str(exc)[:200]}")
            cache[normalized_path] = []
            return []

        cache[normalized_path] = list(detected)
        return [
            Note(
                pitch=str(note.pitch),
                start_time=float(note.start_time),
                end_time=float(note.end_time),
                confidence=float(note.confidence),
            )
            for note in detected
        ]

    def _build_candidate_set(
        self,
        *,
        role: str,
        audio_path: str | None,
        source_stem: str | None,
        notes: list[Note],
        selected_notes: list[Note] | None = None,
    ) -> NoteCandidateSet:
        return NoteCandidateSet(
            role=role,
            source_stem=source_stem,
            input_audio_path=str(audio_path) if audio_path else None,
            notes=list(notes or []),
            selected_notes=list(selected_notes or []),
            analysis_info={
                "candidate_count": len(notes or []),
                "selected_count": len(selected_notes or []),
            },
        )

    def run(self, audio_input: str | PitchPipelineRequest) -> PitchAnalysisResult:
        warnings: list[str] = []

        request = self._normalize_request(audio_input)
        path_stem_index = self._build_path_stem_index(request.source_stems)
        detector_cache: dict[str, list[Note]] = {}

        lead_audio_path = request.lead_audio_path
        rhythm_audio_path = request.rhythm_audio_path or request.source_audio_path or lead_audio_path
        key_audio_path = request.key_audio_path or request.harmony_audio_path or request.source_audio_path or rhythm_audio_path
        duration_audio_path = request.source_audio_path or rhythm_audio_path or lead_audio_path
        harmony_audio_path = request.harmony_audio_path
        bass_audio_path = request.bass_audio_path

        detected_notes = self._safe_detect_candidates(
            audio_path=lead_audio_path,
            cache=detector_cache,
            warnings=warnings,
            role="melody",
        )
        if not detected_notes:
            warnings.append("No melody candidates detected from lead audio.")

        melody_selection = self.melody_selector.select(detected_notes)
        lead_notes = melody_selection.notes
        if melody_selection.detected_count > 0 and melody_selection.kept_count == 0:
            warnings.append("Melody selector removed all detected notes.")
        elif melody_selection.detected_count > 0 and melody_selection.kept_count <= max(
            2, int(round(melody_selection.detected_count * 0.25))
        ):
            warnings.append("Melody selector removed most detected notes; melody may be unstable.")

        harmony_candidates = self._safe_detect_candidates(
            audio_path=harmony_audio_path,
            cache=detector_cache,
            warnings=warnings,
            role="harmony",
        )
        bass_candidates = self._safe_detect_candidates(
            audio_path=bass_audio_path,
            cache=detector_cache,
            warnings=warnings,
            role="bass_root",
        )

        beat_result = self.beat_tracker.track(rhythm_audio_path)
        try:
            key_result = self.key_analyzer.analyze(key_audio_path)
        except Exception as exc:
            warnings.append(f"Key analysis failed: {str(exc)[:200]}")
            key_result = KeyAnalysisResult(
                key="Unknown",
                confidence=0.0,
                method="key_failed_fallback",
            )
        key_method = str(getattr(key_result, "method", "librosa"))
        if "fallback" in key_method:
            warnings.append(f"Key backend downgraded to {key_method}.")

        quantized_notes = self.quantizer.quantize(lead_notes, beat_result.bpm, beat_result.beat_times)
        rhythm_result = self.rhythm_analyzer.analyze(beat_result.beat_times)
        beat_duration_sec = 60.0 / max(1e-6, beat_result.bpm)
        duration_sec = float(get_audio_duration(duration_audio_path))

        try:
            downbeat_result = self.downbeat_tracker.track(rhythm_audio_path, beat_result.beat_times)
        except DownbeatTrackingError as exc:
            warnings.append(str(exc))
            fallback_downbeats = beat_result.beat_times[:: max(2, int(self.config.beats_per_bar))]
            if not fallback_downbeats:
                fallback_downbeats = [0.0]
            from .downbeat_tracker import DownbeatTrackingResult

            downbeat_result = DownbeatTrackingResult(
                downbeat_times=[float(timestamp) for timestamp in fallback_downbeats],
                method="fallback_from_beats",
                confidence=0.2,
                beats_per_bar=max(2, int(self.config.beats_per_bar)),
            )

        effective_beats_per_bar = max(2, int(downbeat_result.beats_per_bar or self.config.beats_per_bar))
        boundaries = self._build_measure_boundaries(downbeat_result.downbeat_times, duration_sec)
        self._recompute_quantized_positions(quantized_notes, boundaries, effective_beats_per_bar)
        measures = self._build_measures(
            quantized_notes,
            boundaries,
            effective_beats_per_bar,
            beat_duration_sec,
        )

        meta = MetaInfo(
            bpm=beat_result.bpm,
            bpm_confidence=beat_result.confidence,
            time_signature=f"{effective_beats_per_bar}/{max(1, int(self.config.beat_unit))}",
            key=key_result.key,
            key_confidence=key_result.confidence,
            rhythm_type=rhythm_result.rhythm_type,
            duration_sec=duration_sec,
            total_measures=len(measures) if measures else None,
        )

        note_density = len(lead_notes) / max(duration_sec, 1.0)
        has_separated_accompaniment = any(
            name in request.source_stems for name in ("accompaniment", "bass", "drums", "other")
        )
        has_accompaniment = bool(has_separated_accompaniment or (note_density >= 1.8 and len(measures) >= 4))

        rhythm_grid = RhythmGrid(
            source_stem=self._infer_source_stem(rhythm_audio_path, path_stem_index, fallback="mix"),
            input_audio_path=rhythm_audio_path,
            beat_times=[float(timestamp) for timestamp in getattr(beat_result, "beat_times", [])],
            downbeat_times=[float(timestamp) for timestamp in getattr(downbeat_result, "downbeat_times", [])],
            bpm=float(beat_result.bpm),
            bpm_confidence=float(beat_result.confidence),
            beats_per_bar=effective_beats_per_bar,
            beat_unit=max(1, int(self.config.beat_unit)),
            beat_duration_sec=float(beat_duration_sec),
            rhythm_type=rhythm_result.rhythm_type,
            stability_score=float(rhythm_result.stability_score),
            analysis_info={
                "downbeat_method": downbeat_result.method,
                "downbeat_confidence": round(downbeat_result.confidence, 4),
                "downbeat_count": len(downbeat_result.downbeat_times),
                "beat_backend": "librosa",
            },
        )
        semantic_audio = SemanticAudioResult(
            source_stems=dict(request.source_stems),
            melody_candidates=self._build_candidate_set(
                role="melody_candidates",
                audio_path=lead_audio_path,
                source_stem=self._infer_source_stem(lead_audio_path, path_stem_index, fallback="lead"),
                notes=detected_notes,
                selected_notes=lead_notes,
            ),
            harmony_candidates=self._build_candidate_set(
                role="harmony_candidates",
                audio_path=harmony_audio_path,
                source_stem=self._infer_source_stem(harmony_audio_path, path_stem_index),
                notes=harmony_candidates,
            ),
            bass_root_candidates=self._build_candidate_set(
                role="bass_root_candidates",
                audio_path=bass_audio_path,
                source_stem=self._infer_source_stem(bass_audio_path, path_stem_index),
                notes=bass_candidates,
            ),
            rhythm_grid=rhythm_grid,
        )

        return PitchAnalysisResult(
            version=self.VERSION,
            meta=meta,
            analysis_info={
                "stage": "p1_downbeat",
                "has_accompaniment": has_accompaniment,
                "detected_note_count": len(detected_notes),
                "melody_note_count": len(lead_notes),
                "melody_notes_removed": max(0, melody_selection.detected_count - melody_selection.kept_count),
                "melody_selector_removed_pitch_range": melody_selection.removed_pitch_range,
                "melody_selector_removed_low_confidence": melody_selection.removed_low_confidence,
                "melody_selector_removed_short": melody_selection.removed_short,
                "melody_selector_removed_conflict": melody_selection.removed_conflict,
                "melody_selector_removed_big_leap": melody_selection.removed_big_leap,
                "melody_selector_merged": melody_selection.merged_count,
                "raw_notes_semantics": "detected_candidates",
                "lead_notes_semantics": "selected_lead_melody",
                "semantic_representation": "semantic_audio_v1",
                "lead_audio_source": semantic_audio.melody_candidates.source_stem,
                "rhythm_audio_source": rhythm_grid.source_stem,
                "key_audio_source": self._infer_source_stem(key_audio_path, path_stem_index, fallback="mix"),
                "harmony_candidate_count": len(harmony_candidates),
                "bass_root_candidate_count": len(bass_candidates),
                "source_stems_available": sorted(request.source_stems.keys()),
                "bpm_raw": float(getattr(beat_result, "raw_bpm"))
                if getattr(beat_result, "raw_bpm", None) is not None
                else None,
                "bpm_ioi": float(getattr(beat_result, "ioi_bpm"))
                if getattr(beat_result, "ioi_bpm", None) is not None
                else None,
                "bpm_final": float(beat_result.bpm),
                "bpm_refine_used": bool(getattr(beat_result, "used_refine", False)),
                "bpm_candidates": [round(float(value), 4) for value in getattr(beat_result, "candidate_bpms", [])],
                "bpm_confidence": round(float(beat_result.confidence), 4),
                "bpm_ioi_stability": round(float(getattr(beat_result, "ioi_stability")), 4)
                if getattr(beat_result, "ioi_stability", None) is not None
                else None,
                "bpm_local_window_count": len(getattr(beat_result, "local_bpms", [])),
                "bpm_local_window_std": round(float(np.std(getattr(beat_result, "local_bpms", []))), 4)
                if len(getattr(beat_result, "local_bpms", [])) >= 2
                else 0.0,
                "downbeat_method": downbeat_result.method,
                "downbeat_confidence": round(downbeat_result.confidence, 4),
                "downbeat_count": len(downbeat_result.downbeat_times),
                "beats_per_bar": effective_beats_per_bar,
                "beat_unit": max(1, int(self.config.beat_unit)),
                "quantize_mode": self.config.quantize_mode,
                "measure_segmentation": "enabled",
                "measure_boundary_source": "downbeat_sequence",
                "quantized_measure_alignment": "downbeat_reindexed",
                "measure_count": len(measures),
                "rhythm_stability": round(rhythm_result.stability_score, 4),
                "detector": self.detector.backend_name,
                "beat_backend": "librosa",
                "key_backend": key_method,
            },
            measures=measures,
            lead_notes=lead_notes,
            raw_notes=detected_notes,
            semantic_audio=semantic_audio,
            warnings=warnings,
        )

    def export_midi(
        self,
        result: PitchAnalysisResult,
        output_path: str | None = None,
    ) -> bytes:
        return self.midi_exporter.export_from_measures(
            measures=result.measures,
            bpm=result.meta.bpm,
            output_path=output_path,
        )
