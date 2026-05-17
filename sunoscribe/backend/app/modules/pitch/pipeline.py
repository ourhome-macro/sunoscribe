from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import librosa
import numpy as np

from .audio_utils import get_audio_duration
from .beat_tracker import BeatTracker
from .config import PitchDetectionConfig
from .contour_candidate_bridge import ContourToCandidateBridge, ContourToCandidateBridgeConfig
from .detector import PitchDetector
from .downbeat_tracker import DownbeatTracker
from .exceptions import DownbeatTrackingError
from .f0_extractor import RMVPEF0Extractor
from .key_analyzer import KeyAnalysisResult, KeyAnalyzer
from .melody_selection_artifact import MelodySelectionConfig, RuleBasedMelodySelector
from .melody_selector import MelodySelectionResult, MelodySelector
from .melody_source_arbitrator import MelodySourceArbitrator
from .note_candidate_builder import NoteCandidateBuilder, NoteCandidateBuilderConfig
from .pitch_contours import PitchContourBuilder
from .midi_exporter import MidiExporter
from .quantizer import NoteQuantizer
from .reason_codes import CONTOUR_TO_CANDIDATE_BRIDGE
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


@dataclass(frozen=True)
class _ScoredHookNote:
    note: Note
    score: float
    pitch_midi: int
    duration_sec: float


class PitchPipeline:
    """Pitch pipeline with lead selection plus semantic candidate outputs."""

    VERSION = "1.4"

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.detector = PitchDetector(self.config)
        self.f0_extractor = RMVPEF0Extractor(config=self.config, detector=self.detector)
        self.beat_tracker = BeatTracker(self.config)
        self.downbeat_tracker = DownbeatTracker(self.config)
        self.key_analyzer = KeyAnalyzer(self.config)
        self.melody_selector = MelodySelector(self.config)
        self.typed_melody_selector = RuleBasedMelodySelector(self._melody_selection_config())
        self.note_candidate_builder = NoteCandidateBuilder(self._note_candidate_builder_config())
        self.melody_arbitrator = MelodySourceArbitrator(self.config)
        self.pitch_contour_builder = PitchContourBuilder()
        self.contour_candidate_bridge = ContourToCandidateBridge(self._contour_bridge_config())
        self.quantizer = NoteQuantizer(self.config)
        self.rhythm_analyzer = RhythmAnalyzer()
        self.midi_exporter = MidiExporter()


    @staticmethod
    def _restore_quantized_lineage(quantized_notes: list[QuantizedNote], source_notes: list[Note]) -> None:
        for quantized in quantized_notes:
            source = PitchPipeline._best_lineage_source(quantized, source_notes)
            if source is None:
                continue
            quantized.candidate_id = getattr(source, "candidate_id", None)
            quantized.source_candidate_id = getattr(source, "source_candidate_id", None) or getattr(source, "candidate_id", None)
            quantized.source_candidate_ids = list(getattr(source, "source_candidate_ids", []) or [])
            if quantized.source_candidate_id and quantized.source_candidate_id not in quantized.source_candidate_ids:
                quantized.source_candidate_ids = [quantized.source_candidate_id] + quantized.source_candidate_ids
            quantized.source_contour_ids = list(getattr(source, "source_contour_ids", []) or [])
            quantized.candidate_origin = getattr(source, "candidate_origin", None)
            quantized.segmentation_evidence = dict(getattr(source, "segmentation_evidence", {}) or {})
            quantized.contour_bridge_evidence = dict(getattr(source, "contour_bridge_evidence", {}) or {})
            quantized.contour_bridge_guard_reason_codes = list(
                getattr(source, "contour_bridge_guard_reason_codes", []) or []
            )
            quantized.source = "quantized_notes"

    @staticmethod
    def _best_lineage_source(note: Note, source_notes: list[Note]) -> Note | None:
        best_note = None
        best_overlap = 0.0
        for source in source_notes:
            overlap = max(
                0.0,
                min(float(note.end_time), float(source.end_time))
                - max(float(note.start_time), float(source.start_time)),
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_note = source
        if best_note is not None and best_overlap > 0.0:
            return best_note
        for source in source_notes:
            if getattr(source, "candidate_id", None) and getattr(source, "candidate_id", None) == getattr(note, "candidate_id", None):
                return source
        return None

    def _build_measure_boundaries(self, downbeat_times: list[float], duration_sec: float) -> list[float]:
        boundaries = sorted(set(float(t) for t in downbeat_times if 0.0 <= t <= duration_sec))
        if not boundaries:
            return []
        if boundaries[0] > 0.2:
            boundaries = [0.0] + boundaries
        if boundaries[-1] < duration_sec:
            boundaries.append(duration_sec)
        return boundaries

    def _note_candidate_builder_config(self) -> NoteCandidateBuilderConfig:
        return NoteCandidateBuilderConfig(
            min_confidence=float(self.config.note_candidate_min_confidence),
            min_voiced_ratio=float(self.config.note_candidate_min_voiced_ratio),
            min_duration_sec=float(self.config.rmvpe_min_note_duration_sec),
            min_stability=float(self.config.note_candidate_min_stability),
            vocal_min_midi=float(self.config.melody_pitch_min_midi),
            vocal_max_midi=float(self.config.melody_pitch_max_midi),
            segmentation_min_source_duration_sec=float(
                self.config.note_candidate_segmentation_min_source_duration_sec
            ),
            segmentation_min_subsegment_duration_sec=float(
                self.config.note_candidate_segmentation_min_subsegment_duration_sec
            ),
            segmentation_max_subsegment_duration_sec=float(
                self.config.note_candidate_segmentation_max_subsegment_duration_sec
            ),
            segmentation_max_pitch_range_semitones=float(
                self.config.note_candidate_segmentation_max_pitch_range_semitones
            ),
            segmentation_max_pitch_stddev_semitones=float(
                self.config.note_candidate_segmentation_max_pitch_stddev_semitones
            ),
            segmentation_max_frame_gap_sec=float(self.config.note_candidate_segmentation_max_frame_gap_sec),
            segmentation_context_extension_sec=float(self.config.note_candidate_segmentation_context_extension_sec),
        )

    def _melody_selection_config(self) -> MelodySelectionConfig:
        return MelodySelectionConfig(
            min_confidence=float(self.config.melody_min_confidence),
            min_duration_sec=float(self.config.melody_min_duration_sec),
            min_voiced_ratio=float(self.config.melody_selection_min_voiced_ratio),
            min_stability=float(self.config.melody_selection_min_stability),
            vocal_min_midi=float(self.config.melody_pitch_min_midi),
            vocal_max_midi=float(self.config.melody_pitch_max_midi),
            phrase_short_note_sec=float(self.config.melody_short_note_sec),
            bridge_min_confidence=float(self.config.contour_bridge_min_confidence),
            bridge_min_duration_sec=float(self.config.contour_bridge_min_duration_sec),
            bridge_max_duration_sec=float(self.config.contour_bridge_max_duration_sec),
            bridge_min_selected_gap_sec=float(self.config.contour_bridge_min_gap_sec),
        )

    def _confidence_policy_metadata(self) -> dict[str, object]:
        return {
            "policy_version": "lead_vocal_confidence_policy_v1",
            "profile": str(self.config.pitch_profile),
            "detector_confidence_threshold": float(self.config.confidence_threshold),
            "note_candidate_min_confidence": float(self.config.note_candidate_min_confidence),
            "note_candidate_min_voiced_ratio": float(self.config.note_candidate_min_voiced_ratio),
            "note_candidate_min_stability": float(self.config.note_candidate_min_stability),
            "note_candidate_segmentation_min_source_duration_sec": float(
                self.config.note_candidate_segmentation_min_source_duration_sec
            ),
            "note_candidate_segmentation_min_subsegment_duration_sec": float(
                self.config.note_candidate_segmentation_min_subsegment_duration_sec
            ),
            "note_candidate_segmentation_max_subsegment_duration_sec": float(
                self.config.note_candidate_segmentation_max_subsegment_duration_sec
            ),
            "note_candidate_segmentation_max_pitch_range_semitones": float(
                self.config.note_candidate_segmentation_max_pitch_range_semitones
            ),
            "note_candidate_segmentation_max_pitch_stddev_semitones": float(
                self.config.note_candidate_segmentation_max_pitch_stddev_semitones
            ),
            "note_candidate_segmentation_max_frame_gap_sec": float(
                self.config.note_candidate_segmentation_max_frame_gap_sec
            ),
            "note_candidate_segmentation_context_extension_sec": float(
                self.config.note_candidate_segmentation_context_extension_sec
            ),
            "melody_selection_min_confidence": float(self.config.melody_min_confidence),
            "melody_selection_min_duration_sec": float(self.config.melody_min_duration_sec),
            "melody_selection_min_voiced_ratio": float(self.config.melody_selection_min_voiced_ratio),
            "melody_selection_min_stability": float(self.config.melody_selection_min_stability),
            "quantize_noise_confidence_floor": float(self.config.quantize_noise_confidence_floor),
            "quantize_merge_min_confidence": float(self.config.quantize_merge_min_confidence),
            "contour_bridge_min_confidence": float(self.config.contour_bridge_min_confidence),
            "threshold_change_reason": "mvp_recall_bias_lower_confidence_gates",
        }

    def _contour_bridge_config(self) -> ContourToCandidateBridgeConfig:
        return ContourToCandidateBridgeConfig(
            min_confidence=float(self.config.contour_bridge_min_confidence),
            min_voiced_ratio=float(self.config.contour_bridge_min_voiced_ratio),
            min_duration_sec=float(self.config.contour_bridge_min_duration_sec),
            max_duration_sec=float(self.config.contour_bridge_max_duration_sec),
            min_stability=float(self.config.contour_bridge_min_stability),
            vocal_min_midi=float(self.config.melody_pitch_min_midi),
            vocal_max_midi=float(self.config.melody_pitch_max_midi),
            min_raw_gap_sec=float(self.config.contour_bridge_min_gap_sec),
            context_gap_sec=float(self.config.melody_low_octave_rescue_context_gap_sec),
            big_gap_sec=float(self.config.melody_low_octave_rescue_big_gap_sec),
            low_octave_context_tolerance_semitones=int(self.config.melody_low_octave_rescue_context_tolerance_semitones),
        )

    def _build_quantized_note_set_payload(
        self,
        *,
        measures: list[dict],
        rhythm_grid: RhythmGrid,
        quantizer_backend: str = "pitch_pipeline_quantizer",
    ) -> dict[str, object]:
        notes: list[dict[str, object]] = []
        for measure in measures or []:
            if not isinstance(measure, dict):
                continue
            measure_num = measure.get("measure_num")
            for raw_note in measure.get("notes") or []:
                if not isinstance(raw_note, dict):
                    continue
                note = dict(raw_note)
                quantized_id = str(note.get("quantized_note_id") or note.get("id") or f"qn_{len(notes) + 1:05d}")
                note["id"] = quantized_id
                note["quantized_note_id"] = quantized_id
                note["measure_num"] = measure_num
                note["measure_index"] = int(measure_num) - 1 if isinstance(measure_num, int) else None
                note["start_time_sec"] = note.get("start_time")
                note["end_time_sec"] = note.get("end_time")
                note["quantized_start_time_sec"] = note.get("quantized_start_time_sec", note.get("start_time"))
                note["quantized_end_time_sec"] = note.get("quantized_end_time_sec", note.get("end_time"))
                note["quantized_duration_sec"] = note.get("quantized_duration_sec")
                if note.get("quantized_duration_sec") is None:
                    try:
                        note["quantized_duration_sec"] = max(0.0, float(note.get("end_time") or 0.0) - float(note.get("start_time") or 0.0))
                    except (TypeError, ValueError):
                        note["quantized_duration_sec"] = None
                note["beat_in_measure"] = note.get("beat_position")
                note["source_candidate_ids"] = self._unique_strings(note.get("source_candidate_ids") or [])
                source_candidate_id = str(note.get("source_candidate_id") or "").strip()
                if source_candidate_id and source_candidate_id not in note["source_candidate_ids"]:
                    note["source_candidate_ids"] = [source_candidate_id] + note["source_candidate_ids"]
                note["source_contour_ids"] = self._unique_strings(note.get("source_contour_ids") or [])
                note["source_f0_frame_range"] = dict(note.get("source_f0_frame_range") or {})
                notes.append(note)

        payload: dict[str, object] = {
            "version": "pitch_pipeline_quantized_notes_v1",
            "schema_version": "quantized_note_set_v2",
            "lineage_contract": {
                "stage": "QuantizedNoteSet",
                "input_stage": "MelodySelection",
                "required_note_fields": [
                    "source_candidate_id",
                    "source_candidate_ids",
                    "source_contour_ids",
                    "source_f0_frame_range",
                ],
            },
            "quantizer_backend": quantizer_backend,
            "requested_quantizer_backend": quantizer_backend,
            "fallback_used": False,
            "fallback_reason": None,
            "tempo_bpm": rhythm_grid.bpm if rhythm_grid else None,
            "meter": f"{rhythm_grid.beats_per_bar}/{rhythm_grid.beat_unit}" if rhythm_grid else None,
            "source_rhythm_grid": "rhythm_grid",
            "confidence_policy": self._confidence_policy_metadata(),
            "notes": notes,
            "summary": {"note_count": len(notes)},
        }
        self._validate_quantized_note_set_payload(payload)
        return payload

    @staticmethod
    def _validate_quantized_note_set_payload(payload: dict[str, object]) -> None:
        notes = payload.get("notes")
        if payload.get("schema_version") != "quantized_note_set_v2" or not isinstance(notes, list) or not notes:
            raise RuntimeError("quantized_note_authority_failed:empty_quantized_note_set_v2")
        failures: list[str] = []
        for index, note in enumerate(notes, start=1):
            if not isinstance(note, dict):
                failures.append(f"note_{index}:not_dict")
                continue
            missing: list[str] = []
            if not str(note.get("id") or note.get("quantized_note_id") or "").strip():
                missing.append("id")
            if not str(note.get("source_candidate_id") or "").strip():
                missing.append("source_candidate_id")
            if not [value for value in note.get("source_candidate_ids") or [] if str(value).strip()]:
                missing.append("source_candidate_ids")
            if not [value for value in note.get("source_contour_ids") or [] if str(value).strip()]:
                missing.append("source_contour_ids")
            frame_range = note.get("source_f0_frame_range")
            if (
                not isinstance(frame_range, dict)
                or frame_range.get("start_frame_index") is None
                or frame_range.get("end_frame_index") is None
                or int(frame_range.get("frame_count") or 0) <= 0
            ):
                missing.append("source_f0_frame_range")
            if missing:
                failures.append(f"note_{index}:{','.join(missing)}")
        if failures:
            raise RuntimeError("quantized_notes_lineage_contract_failed:" + ";".join(failures[:20]))

    @staticmethod
    def _unique_strings(values: object) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

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
                        "candidate_id": getattr(note, "candidate_id", None),
                        "source_candidate_id": getattr(note, "source_candidate_id", None)
                        or getattr(note, "candidate_id", None),
                        "source_candidate_ids": list(getattr(note, "source_candidate_ids", []) or []),
                        "source_contour_ids": list(getattr(note, "source_contour_ids", []) or []),
                        "source_f0_frame_range": dict(
                            getattr(note, "source_f0_frame_range", {}) or {}
                        )
                        or dict(
                            (getattr(note, "segmentation_evidence", {}) or {}).get("source_f0_frame_range") or {}
                        ),
                        "reason_codes": list(getattr(note, "reason_codes", []) or []),
                        "id": f"qn_{idx + 1:03d}_{len(packed_notes) + 1:04d}",
                        "quantized_note_id": f"qn_{idx + 1:03d}_{len(packed_notes) + 1:04d}",
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
            return [self._clone_note(note) for note in cache[cache_key]]

        try:
            detected = self._detect_with_backend(normalized_path, backend=backend)
        except Exception as exc:
            reason = str(exc).strip() or exc.__class__.__name__
            context = f"role={role};backend={backend_key};path={normalized_path};reason={reason[:200]}"
            if optional:
                warnings.append(f"{role}_optional_detection_failed:{context}")
                cache[cache_key] = []
                artifact_cache[cache_key] = None
                return []
            raise RuntimeError(f"{role}_detection_failed:{context}") from exc

        for backend_warning in getattr(self.detector, "backend_warnings", []) or []:
            warning_text = f"{role}_{backend_warning}"
            if warning_text not in warnings:
                warnings.append(warning_text)

        cache[cache_key] = list(detected)
        artifact_cache[cache_key] = self._clone_detection_artifacts(
            getattr(self.detector, "last_detection_artifacts", None)
        )
        return [self._clone_note(note) for note in detected]

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
            analysis_info=self._candidate_set_analysis_info(notes=list(notes or []), selected_notes=list(selected_notes or [])),
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

    def _extract_lead_f0_track(
        self,
        *,
        lead_audio_path: str,
        source_stem: str | None,
        fallback_raw_artifacts: dict[str, object] | None,
        warnings: list[str],
    ) -> F0Track | None:
        _ = fallback_raw_artifacts
        _ = warnings
        if self.f0_extractor is None:
            raise RuntimeError("required_f0_extraction_failed:rmvpe_f0_extractor_unavailable")
        try:
            return self.f0_extractor.extract(str(lead_audio_path), source_stem=source_stem)
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise RuntimeError(f"required_f0_extraction_failed:{str(exc)[:200]}") from exc

    def _candidate_set_analysis_info(self, *, notes: list[Note], selected_notes: list[Note] | None) -> dict[str, object]:
        return {
            "candidate_count": len(notes or []),
            "selected_count": len(selected_notes or []),
            "contour_bridge_candidate_count": sum(
                1
                for note in notes or []
                if getattr(note, "candidate_origin", None) == CONTOUR_TO_CANDIDATE_BRIDGE
            ),
        }

    def _build_note_candidate_payload(
        self,
        *,
        f0_track: F0Track,
        pitch_contours_payload: dict[str, object] | None,
        raw_notes: list[Note],
    ) -> dict[str, object]:
        payload = self.note_candidate_builder.build(
            f0_track=self._f0_track_payload(f0_track),
            pitch_contours=pitch_contours_payload,
            raw_candidates={
                "melody_candidates": {
                    "role": "melody_candidates",
                    "notes": [self._note_payload(note) for note in raw_notes],
                    "selected_notes": [],
                }
            },
        )
        if not isinstance(payload, dict):
            raise RuntimeError("note_candidate_builder returned non-dict payload")
        if payload.get("schema_version") != "note_candidate_set_v2":
            raise RuntimeError("note_candidate_builder returned non-v2 payload")
        return payload

    def _select_authoritative_melody(
        self,
        *,
        note_candidate_payload: dict[str, object],
        pitch_contours_payload: dict[str, object] | None,
        lead_f0_track: F0Track,
    ) -> tuple[MelodySelectionResult, dict[str, object]]:
        selected_melody = self.typed_melody_selector.select(
            note_candidates=note_candidate_payload,
            pitch_contours=pitch_contours_payload,
            vocal_activity={"segments": [self._vocal_activity_payload(segment) for segment in lead_f0_track.vocal_activity]},
        )
        if not isinstance(selected_melody, dict):
            return MelodySelectionResult(
                notes=[],
                detected_count=self._candidate_payload_note_count(note_candidate_payload),
                kept_count=0,
            ), {}

        lead_notes = [
            self._note_from_selected_melody_item(item)
            for item in selected_melody.get("selected_notes") or []
            if isinstance(item, dict)
        ]
        summary = selected_melody.get("summary") if isinstance(selected_melody.get("summary"), dict) else {}
        rejection_counts = summary.get("rejection_reason_counts") if isinstance(summary.get("rejection_reason_counts"), dict) else {}
        postprocess = selected_melody.get("postprocess") if isinstance(selected_melody.get("postprocess"), dict) else {}
        return (
            MelodySelectionResult(
                notes=lead_notes,
                detected_count=int(summary.get("input_candidate_count") or self._candidate_payload_note_count(note_candidate_payload)),
                kept_count=len(lead_notes),
                removed_pitch_range=int(rejection_counts.get("outside_vocal_range") or 0),
                removed_low_confidence=int(rejection_counts.get("low_confidence") or 0),
                removed_short=int(rejection_counts.get("too_short") or 0),
                removed_conflict=int(rejection_counts.get("overlaps_stronger_candidate") or 0),
                merged_count=0,
                postprocess_action_counts=dict(postprocess.get("action_counts") or {}),
                postprocess_reason_code_counts=dict(postprocess.get("reason_code_counts") or {}),
                postprocess_actions=list(postprocess.get("actions") or []),
            ),
            selected_melody,
        )

    @staticmethod
    def _candidate_payload_note_count(note_candidate_payload: dict[str, object]) -> int:
        melody = note_candidate_payload.get("melody_candidates")
        notes = melody.get("notes") if isinstance(melody, dict) else None
        return len(notes) if isinstance(notes, list) else 0

    def _note_candidate_set_from_payload(
        self,
        payload: dict[str, object],
        *,
        selected_notes: list[Note],
        fallback_audio_path: str | None,
        fallback_source_stem: str | None,
    ) -> NoteCandidateSet:
        melody = payload.get("melody_candidates") if isinstance(payload, dict) else None
        notes = [
            self._note_from_candidate_payload(item)
            for item in (melody.get("notes") if isinstance(melody, dict) else [])
            if isinstance(item, dict)
        ]
        analysis_info = dict(payload.get("analysis_info") if isinstance(payload.get("analysis_info"), dict) else {})
        if isinstance(melody, dict) and isinstance(melody.get("analysis_info"), dict):
            analysis_info.update(dict(melody.get("analysis_info") or {}))
        analysis_info["candidate_count"] = len(notes)
        analysis_info["selected_count"] = len(selected_notes or [])
        analysis_info["contour_bridge_candidate_count"] = sum(
            1
            for note in notes
            if getattr(note, "candidate_origin", None) == CONTOUR_TO_CANDIDATE_BRIDGE
            or CONTOUR_TO_CANDIDATE_BRIDGE in list(getattr(note, "reason_codes", []) or [])
        )
        analysis_info["candidate_authority"] = "note_candidate_set_v2"
        return NoteCandidateSet(
            role="melody_candidates",
            source_stem=str(melody.get("source_stem")) if isinstance(melody, dict) and melody.get("source_stem") is not None else fallback_source_stem,
            input_audio_path=str(melody.get("input_audio_path")) if isinstance(melody, dict) and melody.get("input_audio_path") is not None else (str(fallback_audio_path) if fallback_audio_path else None),
            notes=notes,
            selected_notes=list(selected_notes or []),
            analysis_info=analysis_info,
        )

    @staticmethod
    def _note_from_candidate_payload(item: dict[str, object]) -> Note:
        return PitchPipeline._note_from_selected_melody_item(item)

    @staticmethod
    def _note_payload(note: Note) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate_id": note.candidate_id,
            "source_candidate_id": note.source_candidate_id,
            "source_candidate_ids": list(note.source_candidate_ids or []),
            "source_contour_ids": list(note.source_contour_ids or []),
            "source_f0_frame_range": dict(note.source_f0_frame_range or {}),
            "candidate_origin": note.candidate_origin,
            "pitch": note.pitch,
            "start_time": float(note.start_time),
            "end_time": float(note.end_time),
            "confidence": float(note.confidence),
            "reason_codes": list(note.reason_codes or []),
            "contour_bridge_evidence": dict(note.contour_bridge_evidence or {}),
            "contour_bridge_guard_reason_codes": list(note.contour_bridge_guard_reason_codes or []),
            "segmentation_evidence": dict(note.segmentation_evidence or {}),
        }
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _note_from_selected_melody_item(item: dict[str, object]) -> Note:
        from .note_utils import midi_to_note

        pitch = item.get("pitch")
        if not pitch:
            pitch_midi = item.get("pitch_center_midi") or item.get("pitch_midi")
            pitch = midi_to_note(int(round(float(pitch_midi)))) if pitch_midi is not None else "C4"
        return Note(
            pitch=str(pitch),
            start_time=float(item.get("start_time_sec") or item.get("start_time") or 0.0),
            end_time=float(item.get("end_time_sec") or item.get("end_time") or 0.0),
            confidence=float(item.get("confidence") or 0.0),
            reason_codes=[str(value) for value in item.get("reason_codes") or []],
            candidate_id=str(item.get("candidate_id")) if item.get("candidate_id") is not None else None,
            source_candidate_id=str(item.get("source_candidate_id")) if item.get("source_candidate_id") is not None else None,
            source_candidate_ids=[str(value) for value in item.get("source_candidate_ids") or []],
            source_contour_ids=[str(value) for value in item.get("source_contour_ids") or []],
            source_f0_frame_range=dict(item.get("source_f0_frame_range") or {}),
            candidate_origin=str(item.get("candidate_origin")) if item.get("candidate_origin") is not None else None,
            contour_bridge_evidence=dict(item.get("contour_bridge_evidence") or item.get("bridge_evidence") or {}),
            contour_bridge_guard_reason_codes=[
                str(value)
                for value in item.get("contour_bridge_guard_reason_codes")
                or item.get("bridge_guard_reason_codes")
                or []
            ],
            segmentation_evidence=dict(item.get("segmentation_evidence") or {}),
        )

    @staticmethod
    def _vocal_activity_payload(segment: VocalActivitySegment) -> dict[str, object]:
        return {
            "start_time": float(segment.start_time),
            "end_time": float(segment.end_time),
            "state": str(segment.state),
            "voiced_ratio": float(segment.voiced_ratio),
            "mean_confidence": float(segment.mean_confidence),
            "source_stem": segment.source_stem,
            "analysis_info": dict(segment.analysis_info or {}),
        }

    def _build_pitch_contours_payload(self, f0_track: F0Track | None) -> dict[str, object] | None:
        if f0_track is None:
            return None
        return self.pitch_contour_builder.build(json_safe_clone_dict(self._f0_track_payload(f0_track)))

    @staticmethod
    def _f0_track_payload(f0_track: F0Track) -> dict[str, object]:
        return {
            "input_audio_path": f0_track.input_audio_path,
            "backend": f0_track.backend,
            "frames": [
                {
                    "time_sec": float(frame.time_sec),
                    "frequency_hz": float(frame.frequency_hz),
                    "confidence": float(frame.confidence),
                    "voiced": bool(frame.voiced),
                    "pitch_midi": frame.pitch_midi,
                }
                for frame in f0_track.frames
            ],
            "vocal_activity": [
                {
                    "start_time": float(segment.start_time),
                    "end_time": float(segment.end_time),
                    "state": str(segment.state),
                    "voiced_ratio": float(segment.voiced_ratio),
                    "mean_confidence": float(segment.mean_confidence),
                    "source_stem": segment.source_stem,
                    "analysis_info": dict(segment.analysis_info or {}),
                }
                for segment in f0_track.vocal_activity
            ],
            "analysis_info": dict(f0_track.analysis_info or {}),
        }


    def _build_note_candidate_payload(
        self,
        *,
        f0_track: F0Track,
        pitch_contours_payload: dict[str, object] | None,
        raw_detector_notes: list[Note],
    ) -> dict[str, object]:
        raw_detector_evidence = [self._note_payload(note) for note in raw_detector_notes]
        payload = self.note_candidate_builder.build(
            f0_track=json_safe_clone_dict(self._f0_track_payload(f0_track)),
            pitch_contours=json_safe_clone_dict(pitch_contours_payload or {}),
            raw_candidates={"notes": []},
        )
        if payload.get("schema_version") != "note_candidate_set_v2":
            raise RuntimeError("note_candidate_authority_failed:expected_note_candidate_set_v2")

        melody_candidates = payload.get("melody_candidates")
        if not isinstance(melody_candidates, dict):
            raise RuntimeError("note_candidate_authority_failed:missing_melody_candidates")

        authoritative_notes = []
        rejected_untraceable = 0
        for item in melody_candidates.get("notes") or []:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id") or "").strip()
            source_candidate_ids = [str(value) for value in item.get("source_candidate_ids") or [] if str(value).strip()]
            if candidate_id and candidate_id not in source_candidate_ids:
                source_candidate_ids = [candidate_id] + source_candidate_ids
                item["source_candidate_ids"] = source_candidate_ids
            if not item.get("source_candidate_id"):
                item["source_candidate_id"] = candidate_id or None
            if self._candidate_has_required_lineage(item):
                authoritative_notes.append(item)
            else:
                rejected_untraceable += 1

        melody_candidates["notes"] = authoritative_notes
        melody_candidates["selected_notes"] = []
        melody_candidates["raw_detector_evidence"] = {
            "role": "optional_evidence",
            "notes": raw_detector_evidence,
        }
        melody_candidates["schema_version"] = "note_candidate_set_v2"
        analysis_info = dict(melody_candidates.get("analysis_info") or {})
        analysis_info["candidate_authority"] = "note_candidate_set_v2"
        analysis_info["production_input_source"] = "f0_track.pitch_contours"
        analysis_info["raw_detector_role"] = "optional_evidence"
        analysis_info["raw_detector_evidence_count"] = len(raw_detector_notes or [])
        analysis_info["rejected_untraceable_candidate_count"] = rejected_untraceable
        analysis_info["confidence_policy"] = self._confidence_policy_metadata()
        analysis_info["candidate_count"] = len(authoritative_notes)
        analysis_info["selected_count"] = 0
        melody_candidates["analysis_info"] = analysis_info

        payload["melody_candidates"] = melody_candidates
        payload_analysis = dict(payload.get("analysis_info") or {})
        payload_analysis["candidate_authority"] = "note_candidate_set_v2"
        payload_analysis["production_input_source"] = "f0_track.pitch_contours"
        payload_analysis["raw_detector_role"] = "optional_evidence"
        payload_analysis["raw_detector_evidence_count"] = len(raw_detector_notes or [])
        payload_analysis["rejected_untraceable_candidate_count"] = rejected_untraceable
        payload_analysis["confidence_policy"] = self._confidence_policy_metadata()
        payload["analysis_info"] = payload_analysis
        return payload

    @staticmethod
    def _candidate_has_required_lineage(item: dict[str, object]) -> bool:
        source_candidate_ids = [str(value) for value in item.get("source_candidate_ids") or [] if str(value).strip()]
        source_contour_ids = [str(value) for value in item.get("source_contour_ids") or [] if str(value).strip()]
        frame_range = item.get("source_f0_frame_range")
        return bool(
            str(item.get("candidate_id") or "").strip()
            and source_candidate_ids
            and source_contour_ids
            and isinstance(frame_range, dict)
            and frame_range.get("start_frame_index") is not None
            and frame_range.get("end_frame_index") is not None
            and int(frame_range.get("frame_count") or 0) > 0
        )

    def _select_authoritative_melody(
        self,
        *,
        note_candidate_payload: dict[str, object],
    ) -> tuple[MelodySelectionResult, dict[str, object]]:
        selected_payload = self.typed_melody_selector.select(
            note_candidates=note_candidate_payload,
            pitch_contours=None,
            vocal_activity=None,
        )
        selected_items = []
        if isinstance(selected_payload, dict):
            selected_items = [item for item in selected_payload.get("selected_notes") or [] if isinstance(item, dict)]
        lead_notes = [self._note_from_selected_melody_item(item) for item in selected_items]
        rejected_count = 0
        if isinstance(selected_payload, dict):
            rejected_count = len([item for item in selected_payload.get("rejected_candidates") or [] if isinstance(item, dict)])
        candidate_count = len(
            [
                item
                for item in ((note_candidate_payload.get("melody_candidates") or {}).get("notes") or [])
                if isinstance(item, dict)
            ]
        )
        result = MelodySelectionResult(
            notes=lead_notes,
            detected_count=candidate_count,
            kept_count=len(lead_notes),
            removed_low_confidence=rejected_count,
        )
        return result, selected_payload or {
            "schema_version": "selected_melody_v2",
            "selected_notes": [],
            "rejected_candidates": [],
            "analysis_info": {"input_source": "note_candidate_set_v2.notes", "candidate_count": candidate_count},
        }

    def _note_candidate_set_from_payload(
        self,
        *,
        role: str,
        audio_path: str | None,
        source_stem: str | None,
        note_candidate_payload: dict[str, object],
        selected_notes: list[Note],
    ) -> NoteCandidateSet:
        melody_candidates = note_candidate_payload.get("melody_candidates")
        candidate_notes = []
        if isinstance(melody_candidates, dict):
            candidate_notes = [
                self._note_from_candidate_item(item)
                for item in melody_candidates.get("notes") or []
                if isinstance(item, dict)
            ]
        analysis_info = dict((melody_candidates or {}).get("analysis_info") or {}) if isinstance(melody_candidates, dict) else {}
        analysis_info["candidate_count"] = len(candidate_notes)
        analysis_info["selected_count"] = len(selected_notes or [])
        analysis_info["candidate_authority"] = "note_candidate_set_v2"
        analysis_info["selection_input_source"] = "note_candidate_set_v2.notes"
        return NoteCandidateSet(
            role=role,
            source_stem=source_stem,
            input_audio_path=str(audio_path) if audio_path else None,
            notes=candidate_notes,
            selected_notes=list(selected_notes or []),
            analysis_info=analysis_info,
        )

    def _note_from_candidate_item(self, item: dict[str, object]) -> Note:
        return Note(
            pitch=str(item.get("pitch") or self._pitch_name_from_midi(item.get("pitch_center_midi"))),
            start_time=float(item.get("start_time") or item.get("start_time_sec") or 0.0),
            end_time=float(item.get("end_time") or item.get("end_time_sec") or 0.0),
            confidence=float(item.get("confidence") or 0.0),
            reason_codes=[str(value) for value in item.get("reason_codes") or []],
            candidate_id=str(item.get("candidate_id") or "") or None,
            source_candidate_id=str(item.get("source_candidate_id") or item.get("candidate_id") or "") or None,
            source_candidate_ids=[str(value) for value in item.get("source_candidate_ids") or []],
            source_contour_ids=[str(value) for value in item.get("source_contour_ids") or []],
            candidate_origin=str(item.get("candidate_origin") or "") or None,
            segmentation_evidence=self._segmentation_evidence_with_lineage(item),
        )

    def _note_from_selected_melody_item(self, item: dict[str, object]) -> Note:
        return Note(
            pitch=self._pitch_name_from_midi(item.get("pitch_center_midi")),
            start_time=float(item.get("start_time_sec") or item.get("start_time") or 0.0),
            end_time=float(item.get("end_time_sec") or item.get("end_time") or 0.0),
            confidence=float(item.get("confidence") or 0.0),
            reason_codes=[str(value) for value in item.get("reason_codes") or []],
            candidate_id=str(item.get("candidate_id") or "") or None,
            source_candidate_id=str(item.get("source_candidate_id") or item.get("candidate_id") or "") or None,
            source_candidate_ids=[str(value) for value in item.get("source_candidate_ids") or []],
            source_contour_ids=[str(value) for value in item.get("source_contour_ids") or []],
            candidate_origin=str(item.get("candidate_origin") or "") or None,
            contour_bridge_evidence=dict(item.get("contour_bridge_evidence") or {}),
            contour_bridge_guard_reason_codes=[str(value) for value in item.get("contour_bridge_guard_reason_codes") or []],
            segmentation_evidence=self._segmentation_evidence_with_lineage(item),
        )

    @staticmethod
    def _segmentation_evidence_with_lineage(item: dict[str, object]) -> dict[str, object]:
        evidence = dict(item.get("segmentation_evidence") or {})
        evidence.setdefault("source_f0_frame_range", dict(item.get("source_f0_frame_range") or {}))
        evidence.setdefault("source_contour_ids", [str(value) for value in item.get("source_contour_ids") or []])
        evidence.setdefault("source_candidate_ids", [str(value) for value in item.get("source_candidate_ids") or []])
        return evidence

    @staticmethod
    def _note_payload(note: Note) -> dict[str, object]:
        return {
            "pitch": note.pitch,
            "start_time": float(note.start_time),
            "end_time": float(note.end_time),
            "confidence": float(note.confidence),
            "reason_codes": list(getattr(note, "reason_codes", []) or []),
            "candidate_id": getattr(note, "candidate_id", None),
            "source_candidate_id": getattr(note, "source_candidate_id", None),
            "source_candidate_ids": list(getattr(note, "source_candidate_ids", []) or []),
            "source_contour_ids": list(getattr(note, "source_contour_ids", []) or []),
            "candidate_origin": getattr(note, "candidate_origin", None),
            "segmentation_evidence": dict(getattr(note, "segmentation_evidence", {}) or {}),
            "contour_bridge_evidence": dict(getattr(note, "contour_bridge_evidence", {}) or {}),
        }

    @staticmethod
    def _pitch_name_from_midi(value: object) -> str:
        try:
            from .note_utils import midi_to_note

            return str(midi_to_note(int(round(float(value)))))
        except Exception:
            return "C4"

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

    def _build_instrumental_hook_notes(
        self,
        *,
        decision: ArrangementDecision,
        bpm: float,
        beat_times: list[float],
        boundaries: list[float],
        beats_per_bar: int,
    ) -> list[QuantizedNote]:
        raw_candidates = self._instrumental_support_candidates(decision)
        selected = self._select_instrumental_topline(raw_candidates)
        if not selected:
            return []

        quantized = self.quantizer.quantize(selected, bpm, beat_times)
        self._recompute_quantized_positions(quantized, boundaries, beats_per_bar)
        for note in quantized:
            note.source = "instrumental_hook"
        return quantized

    def _instrumental_support_candidates(self, decision: ArrangementDecision) -> list[Note]:
        segments = [
            segment
            for segment in decision.segment_decisions
            if str(segment.state or "").strip().lower() == "instrumental"
        ]
        if not segments or not decision.selected_support_notes:
            return []

        candidates: list[Note] = []
        for note in decision.selected_support_notes:
            if any(self._note_overlaps_window(note, float(segment.start_time), float(segment.end_time)) for segment in segments):
                candidates.append(self._clone_note(note))
        return candidates

    def _select_instrumental_topline(self, notes: list[Note]) -> list[Note]:
        if not notes:
            return []

        window_sec = max(0.01, float(getattr(self.config, "arrangement_support_conflict_window_sec", 0.08) or 0.08))
        scored = [item for item in (self._score_hook_note(note) for note in notes) if item is not None]
        scored.sort(key=lambda item: (float(item.note.start_time), -item.score, -item.pitch_midi))

        selected: list[_ScoredHookNote] = []
        for item in scored:
            conflicting_indexes = [
                idx
                for idx, current in enumerate(selected)
                if self._notes_share_window(item.note, current.note, window_sec=window_sec)
            ]
            if not conflicting_indexes:
                selected.append(item)
                continue

            best = item
            best_index: int | None = None
            for idx in conflicting_indexes:
                current = selected[idx]
                if self._hook_priority_key(best) > self._hook_priority_key(current):
                    best_index = idx
                else:
                    best = current

            if best is item and best_index is not None:
                selected[best_index] = item

        selected.sort(key=lambda item: (float(item.note.start_time), item.pitch_midi, float(item.note.end_time)))
        return self._resolve_hook_overlaps(selected)

    def _resolve_hook_overlaps(self, selected: list[_ScoredHookNote]) -> list[Note]:
        resolved: list[_ScoredHookNote] = []
        for item in selected:
            if not resolved:
                resolved.append(item)
                continue
            previous = resolved[-1]
            if float(item.note.start_time) < float(previous.note.end_time):
                if self._hook_priority_key(item) > self._hook_priority_key(previous):
                    resolved[-1] = item
                continue
            resolved.append(item)

        return [
            self._clone_note(item.note)
            for item in resolved
            if float(item.note.end_time) > float(item.note.start_time)
        ]

    @staticmethod
    def _clone_note(note: Note) -> Note:
        return Note(
            pitch=str(note.pitch),
            start_time=float(note.start_time),
            end_time=float(note.end_time),
            confidence=float(note.confidence),
            reason_codes=list(getattr(note, "reason_codes", []) or []),
            candidate_id=getattr(note, "candidate_id", None),
            source_candidate_id=getattr(note, "source_candidate_id", None),
            source_candidate_ids=list(getattr(note, "source_candidate_ids", []) or []),
            source_contour_ids=list(getattr(note, "source_contour_ids", []) or []),
            candidate_origin=getattr(note, "candidate_origin", None),
            contour_bridge_evidence=dict(getattr(note, "contour_bridge_evidence", {}) or {}),
            contour_bridge_guard_reason_codes=list(getattr(note, "contour_bridge_guard_reason_codes", []) or []),
            segmentation_evidence=dict(getattr(note, "segmentation_evidence", {}) or {}),
        )

    @staticmethod
    def _hook_priority_key(item: _ScoredHookNote) -> tuple[float, int, float, float]:
        return (round(float(item.score), 6), int(item.pitch_midi), -float(item.note.start_time), float(item.duration_sec))

    @staticmethod
    def _note_overlaps_window(note: Note, start_time: float, end_time: float) -> bool:
        return float(note.end_time) > float(start_time) and float(note.start_time) < float(end_time)

    @staticmethod
    def _notes_share_window(left: Note, right: Note, *, window_sec: float) -> bool:
        left_start = float(left.start_time)
        right_start = float(right.start_time)
        if abs(left_start - right_start) <= window_sec:
            return True
        return float(left.end_time) > right_start and float(right.end_time) > left_start

    def _score_hook_note(self, note: Note) -> _ScoredHookNote | None:
        duration_sec = max(0.0, float(note.end_time) - float(note.start_time))
        if duration_sec <= 0.0:
            return None
        try:
            from .note_utils import note_to_midi

            pitch_midi = int(round(float(note_to_midi(str(note.pitch)))))
        except Exception:
            return None
        confidence = max(0.0, min(1.0, float(note.confidence)))
        score = (min(duration_sec, 1.5) * 0.6) + (confidence * 0.4)
        return _ScoredHookNote(note=note, score=score, pitch_midi=pitch_midi, duration_sec=duration_sec)

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

        lead_source_stem = self._infer_source_stem(lead_audio_path, path_stem_index, fallback="lead")
        lead_f0_track = self._extract_lead_f0_track(
            lead_audio_path=str(lead_audio_path),
            source_stem=lead_source_stem,
            fallback_raw_artifacts=detector_artifact_cache.get(f"{self.detector.backend_name}:{str(lead_audio_path)}"),
            warnings=warnings,
        )
        if lead_f0_track is None:
            raise RuntimeError("required_f0_extraction_failed:f0_track_unavailable")
        lead_f0_track.analysis_info = dict(lead_f0_track.analysis_info or {})
        lead_f0_track.analysis_info.setdefault("stage", "F0Track")
        lead_f0_track.analysis_info.setdefault("required_stage", True)
        lead_f0_track.analysis_info.setdefault("authoritative", True)
        legacy_detector_f0_track = self._build_f0_track(
            raw_artifacts=detector_artifact_cache.get(f"{self.detector.backend_name}:{str(lead_audio_path)}"),
            source_stem=self._infer_source_stem(lead_audio_path, path_stem_index, fallback="lead"),
        )
        pitch_contours_payload = self._build_pitch_contours_payload(lead_f0_track)
        contour_bridge_result = self.contour_candidate_bridge.bridge(
            contours=pitch_contours_payload.get("contours") if isinstance(pitch_contours_payload, dict) else None,
            raw_candidates=detected_notes,
            vocal_activity=lead_f0_track.vocal_activity if lead_f0_track is not None else None,
        )
        note_candidate_payload = self._build_note_candidate_payload(
            f0_track=lead_f0_track,
            pitch_contours_payload=pitch_contours_payload,
            raw_detector_notes=detected_notes,
        )
        authoritative_candidate_notes = self._note_candidate_set_from_payload(
            role="melody_candidates",
            audio_path=lead_audio_path,
            source_stem=lead_source_stem,
            note_candidate_payload=note_candidate_payload,
            selected_notes=[],
        ).notes
        support_source_stem = self._infer_source_stem(support_audio_path, path_stem_index, fallback="mix")
        arrangement_decision = self.melody_arbitrator.decide(
            rmvpe_candidate=MelodySourceCandidate(
                source_id=self._source_id(backend="note_candidate_set_v2", source_stem=lead_source_stem),
                backend="note_candidate_set_v2",
                source_stem=lead_source_stem,
                input_audio_path=str(lead_audio_path),
                notes=authoritative_candidate_notes,
                f0_track=lead_f0_track,
                analysis_info={"role": "lead_vocal", "candidate_authority": "note_candidate_set_v2"},
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

        melody_selection, selected_melody_payload = self._select_authoritative_melody(
            note_candidate_payload=note_candidate_payload,
        )
        lead_notes = melody_selection.notes
        if melody_selection.detected_count > 0 and melody_selection.kept_count == 0:
            warnings.append("Melody selection removed all NoteCandidateSet v2 candidates.")
        elif melody_selection.detected_count > 0 and melody_selection.kept_count <= max(
            2, int(round(melody_selection.detected_count * 0.25))
        ):
            warnings.append("Melody selection removed most NoteCandidateSet v2 candidates; melody may be unstable.")

        quantized_notes = self.quantizer.quantize(lead_notes, beat_result.bpm, beat_result.beat_times)
        self._restore_quantized_lineage(quantized_notes, lead_notes)
        self._recompute_quantized_positions(quantized_notes, boundaries, effective_beats_per_bar)
        measures = self._build_measures(
            quantized_notes,
            boundaries,
            effective_beats_per_bar,
            beat_duration_sec,
        )
        quantized_note_set_payload = self._build_quantized_note_set_payload(
            measures=measures,
            rhythm_grid=rhythm_grid,
        )
        arrangement_summary = self._build_arrangement_summary(
            decision=arrangement_decision,
            lead_source_stem=lead_source_stem,
            support_source_stem=support_source_stem,
        )
        instrumental_hook_notes = self._build_instrumental_hook_notes(
            decision=arrangement_decision,
            bpm=beat_result.bpm,
            beat_times=beat_result.beat_times,
            boundaries=boundaries,
            beats_per_bar=effective_beats_per_bar,
        )
        arrangement_summary["instrumental_hook_note_count"] = len(instrumental_hook_notes)
        arrangement_summary["instrumental_hook_status"] = "selected" if instrumental_hook_notes else "empty"
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
            melody_candidates=self._note_candidate_set_from_payload(
                role="melody_candidates",
                audio_path=lead_audio_path,
                source_stem=lead_source_stem,
                note_candidate_payload=note_candidate_payload,
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
        semantic_audio.melody_candidates.analysis_info["contour_to_candidate_bridge"] = contour_bridge_result.summary
        semantic_audio.melody_candidates.analysis_info["contour_to_candidate_bridge_mode"] = "shadow_diagnostics_only"
        semantic_audio.melody_candidates.analysis_info["pitch_contours"] = json_safe_clone_dict(pitch_contours_payload)
        semantic_audio.melody_candidates.analysis_info["note_candidate_set"] = json_safe_clone_dict(note_candidate_payload)
        semantic_audio.melody_candidates.analysis_info["selected_melody"] = json_safe_clone_dict(selected_melody_payload)
        semantic_audio.melody_candidates.analysis_info["quantized_notes"] = json_safe_clone_dict(quantized_note_set_payload)
        semantic_audio.melody_candidates.analysis_info["confidence_policy"] = self._confidence_policy_metadata()
        if isinstance(selected_melody_payload, dict):
            selected_analysis_info = selected_melody_payload.get("analysis_info")
            if isinstance(selected_analysis_info, dict):
                semantic_audio.melody_candidates.analysis_info["selection_input_source"] = selected_analysis_info.get(
                    "input_source"
                )
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
                "raw_detector_evidence_count": len(detected_notes),
                "authoritative_candidate_count": len(semantic_audio.melody_candidates.notes),
                "melody_note_count": len(lead_notes),
                "melody_notes_removed": max(0, melody_selection.detected_count - melody_selection.kept_count),
                "melody_selector_removed_pitch_range": melody_selection.removed_pitch_range,
                "melody_selector_removed_low_confidence": melody_selection.removed_low_confidence,
                "melody_selector_removed_short": melody_selection.removed_short,
                "melody_selector_removed_conflict": melody_selection.removed_conflict,
                "melody_selector_removed_big_leap": melody_selection.removed_big_leap,
                "melody_selector_merged": melody_selection.merged_count,
                "melody_postprocess_action_counts": dict(melody_selection.postprocess_action_counts or {}),
                "melody_postprocess_reason_code_counts": dict(melody_selection.postprocess_reason_code_counts or {}),
                "melody_postprocess_actions": list(melody_selection.postprocess_actions or [])[:200],
                "contour_to_candidate_bridge": contour_bridge_result.summary,
                "contour_to_candidate_bridge_mode": "shadow_diagnostics_only",
                "raw_notes_semantics": "detector_segmentation_optional_evidence",
                "lead_notes_semantics": "selected_lead_melody_from_note_candidate_set_v2",
                "lead_candidate_authority": "note_candidate_set_v2",
                "lead_note_source": "quantized_notes",
                "lead_selection_authoritative": True,
                "confidence_policy": self._confidence_policy_metadata(),
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
            instrumental_melody_notes=instrumental_hook_notes,
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
