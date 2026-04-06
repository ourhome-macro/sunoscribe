from __future__ import annotations

import librosa

from .beat_tracker import BeatTracker
from .config import PitchDetectionConfig
from .detector import PitchDetector
from .key_analyzer import KeyAnalyzer
from .quantizer import NoteQuantizer
from .types import MetaInfo, PitchAnalysisResult, QuantizedNote


class PitchPipeline:
    """
    P0/P1 流水线：
    - 原始音符序列（basic-pitch）
    - BPM（librosa）
    - 调式（librosa chroma）
    - 音符量化 + 小节分组（P1 baseline）
    """

    VERSION = "1.1"

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.detector = PitchDetector(self.config)
        self.beat_tracker = BeatTracker(self.config)
        self.key_analyzer = KeyAnalyzer(self.config)
        self.quantizer = NoteQuantizer(self.config)

    @staticmethod
    def _build_measures(notes: list[QuantizedNote]) -> list[dict]:
        grouped: dict[int, list[QuantizedNote]] = {}
        for note in notes:
            measure_num = note.measure_num or 1
            grouped.setdefault(measure_num, []).append(note)

        measures: list[dict] = []
        for measure_num in sorted(grouped.keys()):
            m_notes = sorted(grouped[measure_num], key=lambda n: n.start_time)
            measures.append(
                {
                    "measure_num": measure_num,
                    "start_time": m_notes[0].start_time,
                    "is_anacrusis": False,
                    "notes": [
                        {
                            "pitch": n.pitch,
                            "start_time": n.start_time,
                            "end_time": n.end_time,
                            "duration_beats": n.duration_beats,
                            "note_type": n.note_type.value,
                            "beat_position": n.beat_position,
                            "lyric": n.lyric,
                            "confidence": n.confidence,
                        }
                        for n in m_notes
                    ],
                }
            )
        return measures

    def run(self, audio_path: str) -> PitchAnalysisResult:
        warnings = []

        notes = self.detector.detect(audio_path)
        beat_result = self.beat_tracker.track(audio_path)
        key_result = self.key_analyzer.analyze(audio_path)
        quantized_notes = self.quantizer.quantize(notes, beat_result.bpm, beat_result.beat_times)
        measures = self._build_measures(quantized_notes)

        duration_sec = float(librosa.get_duration(path=audio_path))

        meta = MetaInfo(
            bpm=beat_result.bpm,
            bpm_confidence=beat_result.confidence,
            time_signature="4/4",
            key=key_result.key,
            key_confidence=key_result.confidence,
            rhythm_type="stable",
            duration_sec=duration_sec,
            total_measures=len(measures) if measures else None,
        )

        return PitchAnalysisResult(
            version=self.VERSION,
            meta=meta,
            analysis_info={
                "quantize_mode": self.config.quantize_mode,
                "measure_segmentation": "enabled",
                "detector": "basic-pitch",
                "beat_backend": "librosa",
                "key_backend": "librosa_chroma",
            },
            measures=measures,
            raw_notes=notes,
            warnings=warnings,
        )
