from __future__ import annotations

from dataclasses import replace

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
from .melody_source_arbitrator import MelodySourceArbitrator
from .midi_exporter import MidiExporter
from .quantizer import NoteQuantizer
from .rhythm_analyzer import RhythmAnalyzer
from .types import (
    ArrangementDecision,
    F0Frame,
    F0Track,
    MelodySourceCandidate,
    MetaInfo,
    Note,
    NoteCandidateSet,
    PitchAnalysisResult,
    PitchPipelineRequest,
    QuantizedNote,
    RhythmGrid,
    SemanticAudioResult,
    VocalActivitySegment,
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
        self.melody_arbitrator = MelodySourceArbitrator(self.config)
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
        artifact_cache: dict[str, dict[str, object] | None],
        warnings: list[str],
        role: str,
        backend: str | None = None,
        optional: bool = False,
    ) -> list[Note]:
        normalized_path = str(audio_path or "").strip()
        if not normalized_path:
            return []
        backend_key = str(backend or self.detector.backend_name)
        cache_key = f"{backend_key}:{normalized_path}"
        if cache_key in cache:
            if cache_key not in artifact_cache:
                artifact_cache[cache_key] = None
            return [
                Note(
                    pitch=str(note.pitch),
                    start_time=float(note.start_time),
                    end_time=float(note.end_time),
                    confidence=float(note.confidence),
                )
                for note in cache[cache_key]
            ]

        try:
            detected = self._detect_with_backend(normalized_path, backend=backend)
        except Exception as exc:
            prefix = f"{role}_optional_detection_failed" if optional else f"{role}_detection_failed"
            warnings.append(f"{prefix}:{str(exc)[:200]}")
            cache[cache_key] = []
            artifact_cache[cache_key] = None
            return []

        for backend_warning in getattr(self.detector, "backend_warnings", []) or []:
            warning_text = f"{role}_{backend_warning}"
            if warning_text not in warnings:
                warnings.append(warning_text)

        cache[cache_key] = list(detected)
        artifact_cache[cache_key] = self._clone_detection_artifacts(
            getattr(self.detector, "last_detection_artifacts", None)
        )
        return [
            Note(
                pitch=str(note.pitch),
                start_time=float(note.start_time),
                end_time=float(note.end_time),
                confidence=float(note.confidence),
            )
            for note in detected
        ]

    def _detect_with_backend(self, audio_path: str, *, backend: str | None = None) -> list[Note]:
        if not backend:
            return self.detector.detect(audio_path)

        original_config = self.detector.config
        original_backend_name = self.detector.backend_name
        normalized_backend = PitchDetector._normalize_backend(str(backend))
        try:
            self.detector.config = replace(
                self.config,
                pitch_backend=normalized_backend,
                pitch_backend_fallbacks=(),
            )
            self.detector.backend_name = normalized_backend
            return self.detector.detect(audio_path)
        finally:
            self.detector.config = original_config
            self.detector.backend_name = original_backend_name

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

    def _build_f0_track(
        self,
        *,
        raw_artifacts: dict[str, object] | None,
        source_stem: str | None,
    ) -> F0Track | None:
        if not isinstance(raw_artifacts, dict):
            return None
        raw_track = raw_artifacts.get("f0_track")
        if not isinstance(raw_track, dict):
            return None

        frames: list[F0Frame] = []
        for raw_frame in raw_track.get("frames") or []:
            if not isinstance(raw_frame, dict):
                continue
            frames.append(
                F0Frame(
                    time_sec=float(raw_frame.get("time_sec", 0.0)),
                    frequency_hz=float(raw_frame.get("frequency_hz", 0.0)),
                    confidence=float(raw_frame.get("confidence", 0.0)),
                    voiced=bool(raw_frame.get("voiced", False)),
                    pitch_midi=(
                        float(raw_frame["pitch_midi"])
                        if raw_frame.get("pitch_midi") is not None
                        else None
                    ),
                )
            )

        vocal_activity: list[VocalActivitySegment] = []
        for raw_segment in raw_track.get("vocal_activity") or []:
            if not isinstance(raw_segment, dict):
                continue
            vocal_activity.append(
                VocalActivitySegment(
                    start_time=float(raw_segment.get("start_time", 0.0)),
                    end_time=float(raw_segment.get("end_time", 0.0)),
                    state=str(raw_segment.get("state", "inactive")),
                    voiced_ratio=float(raw_segment.get("voiced_ratio", 0.0)),
                    mean_confidence=float(raw_segment.get("mean_confidence", 0.0)),
                    source_stem=source_stem,
                    analysis_info=dict(raw_segment.get("analysis_info") or {}),
                )
            )

        return F0Track(
            source_stem=source_stem,
            input_audio_path=str(raw_track.get("input_audio_path") or ""),
            backend=str(raw_track.get("backend") or raw_artifacts.get("backend") or ""),
            frames=frames,
            vocal_activity=vocal_activity,
            analysis_info=dict(raw_track.get("analysis_info") or {}),
        )

    def _source_id(self, *, backend: str, source_stem: str | None) -> str:
        source = str(source_stem or "unknown").strip() or "unknown"
        return f"{backend}:{source}"

    def _support_audio_path(self, request: PitchPipelineRequest, lead_audio_path: str) -> str | None:
        if request.harmony_audio_path:
            return str(request.harmony_audio_path)
        source_path = str(request.source_audio_path or "").strip()
        if source_path and source_path != str(lead_audio_path):
            return source_path
        accompaniment_path = str(request.source_stems.get("accompaniment", "")).strip()
        if accompaniment_path:
            return accompaniment_path
        return None

    def _build_arrangement_summary(
        self,
        *,
        decision: ArrangementDecision,
        lead_source_stem: str | None,
        support_source_stem: str | None,
    ) -> dict[str, object]:
        info = dict(decision.analysis_info or {})
        return {
            "policy": "deterministic_melody_source_arbitration",
            "enabled": bool(info.get("enabled", True)),
            "lead_source": self._backend_from_source_id(decision.lead_source_id),
            "lead_source_id": decision.lead_source_id,
            "lead_source_stem": lead_source_stem,
            "support_source": self._backend_from_source_id(decision.support_source_id),
            "support_source_id": decision.support_source_id,
            "support_source_stem": support_source_stem,
            "lead_note_count": len(decision.selected_lead_notes),
            "support_note_count": len(decision.selected_support_notes),
            "suppressed_count": len(decision.suppressed_candidates),
            "confidence": float(decision.confidence),
            "transition_window_sec": info.get("transition_window_sec", 0.0),
            "max_polyphony": {
                "lead": info.get("lead_max_polyphony", 1),
                "vocal_support": info.get("vocal_support_max_polyphony", 0),
                "climax_support": info.get("climax_support_max_polyphony", 0),
                "instrumental": info.get("instrumental_max_polyphony", 0),
            },
            "segment_state_counts": dict(info.get("segment_state_counts") or {}),
            "segment_decisions": list(info.get("segment_decisions") or []),
        }

    @staticmethod
    def _backend_from_source_id(source_id: str | None) -> str | None:
        if not source_id:
            return None
        return str(source_id).split(":", 1)[0]

    def _clone_detection_artifacts(self, raw_artifacts: object) -> dict[str, object] | None:
        if not isinstance(raw_artifacts, dict):
            return None

        cloned: dict[str, object] = {}
        for key, value in raw_artifacts.items():
            if isinstance(value, dict):
                cloned[str(key)] = json_safe_clone_dict(value)
            elif isinstance(value, list):
                cloned[str(key)] = [json_safe_clone_dict(item) if isinstance(item, dict) else item for item in value]
            else:
                cloned[str(key)] = value
        return cloned

    def run(self, audio_input: str | PitchPipelineRequest) -> PitchAnalysisResult:
        warnings: list[str] = []

        request = self._normalize_request(audio_input)
        path_stem_index = self._build_path_stem_index(request.source_stems)
        detector_cache: dict[str, list[Note]] = {}
        detector_artifact_cache: dict[str, dict[str, object] | None] = {}

        lead_audio_path = request.lead_audio_path
        rhythm_audio_path = request.rhythm_audio_path or request.source_audio_path or lead_audio_path
        key_audio_path = request.key_audio_path or request.harmony_audio_path or request.source_audio_path or rhythm_audio_path
        duration_audio_path = request.source_audio_path or rhythm_audio_path or lead_audio_path
        harmony_audio_path = request.harmony_audio_path
        bass_audio_path = request.bass_audio_path

        detected_notes = self._safe_detect_candidates(
            audio_path=lead_audio_path,
            cache=detector_cache,
            artifact_cache=detector_artifact_cache,
            warnings=warnings,
            role="melody",
        )
        if not detected_notes:
            warnings.append("No melody candidates detected from lead audio.")
        melody_detector_backend = str(getattr(self.detector, "active_backend_name", self.detector.backend_name))

        support_audio_path = self._support_audio_path(request, lead_audio_path)
        basic_pitch_support_candidates: list[Note] = []
        if bool(self.config.basic_pitch_support_enabled):
            basic_pitch_support_candidates = self._safe_detect_candidates(
                audio_path=support_audio_path,
                cache=detector_cache,
                artifact_cache=detector_artifact_cache,
                warnings=warnings,
                role="basic_pitch_support",
                backend="basic-pitch",
                optional=True,
            )

        if harmony_audio_path and str(harmony_audio_path) == str(support_audio_path):
            harmony_candidates = list(basic_pitch_support_candidates)
        else:
            harmony_candidates = self._safe_detect_candidates(
                audio_path=harmony_audio_path,
                cache=detector_cache,
                artifact_cache=detector_artifact_cache,
                warnings=warnings,
                role="harmony",
                backend="basic-pitch",
                optional=True,
            )
        if not harmony_candidates:
            harmony_candidates = list(basic_pitch_support_candidates)

        bass_candidates = self._safe_detect_candidates(
            audio_path=bass_audio_path,
            cache=detector_cache,
            artifact_cache=detector_artifact_cache,
            warnings=warnings,
            role="bass_root",
            backend="basic-pitch",
            optional=True,
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

        lead_f0_track = self._build_f0_track(
            raw_artifacts=detector_artifact_cache.get(f"{self.detector.backend_name}:{str(lead_audio_path)}"),
            source_stem=self._infer_source_stem(lead_audio_path, path_stem_index, fallback="lead"),
        )
        lead_source_stem = self._infer_source_stem(lead_audio_path, path_stem_index, fallback="lead")
        support_source_stem = self._infer_source_stem(support_audio_path, path_stem_index, fallback="mix")
        arrangement_decision = self.melody_arbitrator.decide(
            rmvpe_candidate=MelodySourceCandidate(
                source_id=self._source_id(backend=melody_detector_backend, source_stem=lead_source_stem),
                backend=melody_detector_backend,
                source_stem=lead_source_stem,
                input_audio_path=str(lead_audio_path),
                notes=detected_notes,
                f0_track=lead_f0_track,
                analysis_info={"role": "lead_vocal"},
            ),
            basic_pitch_candidate=MelodySourceCandidate(
                source_id=self._source_id(backend="basic-pitch", source_stem=support_source_stem),
                backend="basic-pitch",
                source_stem=support_source_stem,
                input_audio_path=str(support_audio_path) if support_audio_path else None,
                notes=basic_pitch_support_candidates,
                analysis_info={"role": "support_candidates"},
            ),
            rhythm_grid=rhythm_grid,
        )
        for warning in arrangement_decision.warnings:
            if warning not in warnings:
                warnings.append(warning)

        melody_selection = self.melody_selector.select(arrangement_decision.selected_lead_notes)
        lead_notes = melody_selection.notes
        if melody_selection.detected_count > 0 and melody_selection.kept_count == 0:
            warnings.append("Melody selector removed all detected notes.")
        elif melody_selection.detected_count > 0 and melody_selection.kept_count <= max(
            2, int(round(melody_selection.detected_count * 0.25))
        ):
            warnings.append("Melody selector removed most detected notes; melody may be unstable.")

        quantized_notes = self.quantizer.quantize(lead_notes, beat_result.bpm, beat_result.beat_times)
        self._recompute_quantized_positions(quantized_notes, boundaries, effective_beats_per_bar)
        measures = self._build_measures(
            quantized_notes,
            boundaries,
            effective_beats_per_bar,
            beat_duration_sec,
        )
        arrangement_summary = self._build_arrangement_summary(
            decision=arrangement_decision,
            lead_source_stem=lead_source_stem,
            support_source_stem=support_source_stem,
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

        semantic_audio = SemanticAudioResult(
            source_stems=dict(request.source_stems),
            f0_track=lead_f0_track,
            melody_candidates=self._build_candidate_set(
                role="melody_candidates",
                audio_path=lead_audio_path,
                source_stem=lead_source_stem,
                notes=detected_notes,
                selected_notes=lead_notes,
            ),
            harmony_candidates=self._build_candidate_set(
                role="harmony_candidates",
                audio_path=support_audio_path or harmony_audio_path,
                source_stem=support_source_stem,
                notes=harmony_candidates,
                selected_notes=arrangement_decision.selected_support_notes,
            ),
            bass_root_candidates=self._build_candidate_set(
                role="bass_root_candidates",
                audio_path=bass_audio_path,
                source_stem=self._infer_source_stem(bass_audio_path, path_stem_index),
                notes=bass_candidates,
            ),
            rhythm_grid=rhythm_grid,
        )
        semantic_audio.melody_candidates.analysis_info["arrangement_decision"] = arrangement_summary
        semantic_audio.harmony_candidates.analysis_info["arrangement_decision"] = arrangement_summary
        semantic_audio.harmony_candidates.analysis_info["selected_support_count"] = len(
            arrangement_decision.selected_support_notes
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
                "lead_selection_authoritative": True,
                "semantic_representation": "semantic_audio_v1",
                "arrangement_decision": arrangement_summary,
                "f0_track_available": lead_f0_track is not None,
                "vocal_activity_segment_count": len(lead_f0_track.vocal_activity) if lead_f0_track is not None else 0,
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
                "detector": melody_detector_backend,
                "configured_detector": self.detector.backend_name,
                "pitch_backend_fallback_used": melody_detector_backend != self.detector.backend_name,
                "fallback": melody_detector_backend != self.detector.backend_name,
                "beat_backend": "librosa",
                "key_backend": key_method,
            },
            measures=measures,
            lead_notes=lead_notes,
            raw_notes=detected_notes,
            f0_track=lead_f0_track,
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


def json_safe_clone_dict(raw: dict[str, object]) -> dict[str, object]:
    cloned: dict[str, object] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            cloned[str(key)] = json_safe_clone_dict(value)
        elif isinstance(value, list):
            cloned[str(key)] = [
                json_safe_clone_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cloned[str(key)] = value
    return cloned
