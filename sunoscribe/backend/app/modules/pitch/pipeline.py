from __future__ import annotations

import librosa

from .beat_tracker import BeatTracker
from .config import PitchDetectionConfig
from .detector import PitchDetector
from .downbeat_tracker import DownbeatTracker
from .exceptions import DownbeatTrackingError
from .key_analyzer import KeyAnalyzer
from .quantizer import NoteQuantizer
from .rhythm_analyzer import RhythmAnalyzer
from .types import MetaInfo, PitchAnalysisResult, QuantizedNote


class PitchPipeline:
    """
    P0/P1 流水线：
    - 原始音符序列（basic-pitch）
    - BPM（librosa）
    - 调式（librosa chroma）
    - 音符量化 + 小节分组（P1 baseline）
    """

    VERSION = "1.2"

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.detector = PitchDetector(self.config)
        self.beat_tracker = BeatTracker(self.config)
        self.downbeat_tracker = DownbeatTracker(self.config)
        self.key_analyzer = KeyAnalyzer(self.config)
        self.quantizer = NoteQuantizer(self.config)
        self.rhythm_analyzer = RhythmAnalyzer()

    def _build_measures(
        self,
        notes: list[QuantizedNote],
        downbeat_times: list[float],
        duration_sec: float,
    ) -> list[dict]:
        if not downbeat_times:
            return []

        boundaries = sorted(set(float(t) for t in downbeat_times if 0.0 <= t <= duration_sec))
        if not boundaries:
            return []
        if boundaries[0] > 0.2:
            boundaries = [0.0] + boundaries
        if boundaries[-1] < duration_sec:
            boundaries.append(duration_sec)

        measures: list[dict] = []
        beats_per_bar = max(2, int(self.config.beats_per_bar))

        for i in range(len(boundaries) - 1):
            m_start, m_end = boundaries[i], boundaries[i + 1]
            m_num = i + 1
            m_notes = sorted((n for n in notes if m_start <= n.start_time < m_end), key=lambda n: n.start_time)

            bar_dur = max(1e-6, m_end - m_start)
            beat_dur = bar_dur / beats_per_bar

            packed = []
            for n in m_notes:
                beat_pos = 1.0 + (n.start_time - m_start) / beat_dur
                packed.append(
                    {
                        "pitch": n.pitch,
                        "start_time": n.start_time,
                        "end_time": n.end_time,
                        "duration_beats": n.duration_beats,
                        "note_type": n.note_type.value,
                        "beat_position": round(float(beat_pos), 3),
                        "lyric": n.lyric,
                        "confidence": n.confidence,
                    }
                )

            measures.append(
                {
                    "measure_num": m_num,
                    "start_time": m_start,
                    "is_anacrusis": i == 0 and boundaries[0] == 0.0 and downbeat_times[0] > 0.2,
                    "notes": packed,
                }
            )

        return measures

    def run(self, audio_path: str) -> PitchAnalysisResult:
        warnings = []

        notes = self.detector.detect(audio_path)
        beat_result = self.beat_tracker.track(audio_path)
        key_result = self.key_analyzer.analyze(audio_path)
        quantized_notes = self.quantizer.quantize(notes, beat_result.bpm, beat_result.beat_times)
        rhythm_result = self.rhythm_analyzer.analyze(beat_result.beat_times)

        duration_sec = float(librosa.get_duration(path=audio_path))

        try:
            downbeat_result = self.downbeat_tracker.track(audio_path, beat_result.beat_times)
        except DownbeatTrackingError as exc:
            warnings.append(str(exc))
            fallback_downbeats = beat_result.beat_times[:: max(2, int(self.config.beats_per_bar))]
            if not fallback_downbeats:
                fallback_downbeats = [0.0]
            from .downbeat_tracker import DownbeatTrackingResult

            downbeat_result = DownbeatTrackingResult(
                downbeat_times=[float(t) for t in fallback_downbeats],
                method="fallback_from_beats",
                confidence=0.2,
                beats_per_bar=max(2, int(self.config.beats_per_bar)),
            )

        measures = self._build_measures(quantized_notes, downbeat_result.downbeat_times, duration_sec)

        meta = MetaInfo(
            bpm=beat_result.bpm,
            bpm_confidence=beat_result.confidence,
            time_signature=f"{max(2, int(self.config.beats_per_bar))}/4",
            key=key_result.key,
            key_confidence=key_result.confidence,
            rhythm_type=rhythm_result.rhythm_type,
            duration_sec=duration_sec,
            total_measures=len(measures) if measures else None,
        )

        # 简化伴奏判断（P1 baseline）：检测到多个小节且音符密度较高，认为更可能有伴奏。
        note_density = len(notes) / max(duration_sec, 1.0)
        has_accompaniment = bool(note_density >= 1.8 and len(measures) >= 4)

        return PitchAnalysisResult(
            version=self.VERSION,
            meta=meta,
            analysis_info={
                "stage": "p1_downbeat",
                "has_accompaniment": has_accompaniment,
                "downbeat_method": downbeat_result.method,
                "downbeat_confidence": round(downbeat_result.confidence, 4),
                "downbeat_count": len(downbeat_result.downbeat_times),
                "quantize_mode": self.config.quantize_mode,
                "measure_segmentation": "enabled",
                "measure_count": len(measures),
                "rhythm_stability": round(rhythm_result.stability_score, 4),
                "detector": "basic-pitch",
                "beat_backend": "librosa",
                "key_backend": "librosa_chroma",
            },
            measures=measures,
            raw_notes=notes,
            warnings=warnings,
        )
