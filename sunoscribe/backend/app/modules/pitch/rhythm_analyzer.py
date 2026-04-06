from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class RhythmAnalysisResult:
    rhythm_type: str  # stable / free / unstable
    stability_score: float


class RhythmAnalyzer:
    """基于节拍间隔稳定性分析节奏类型。"""

    def analyze(self, beat_times: List[float]) -> RhythmAnalysisResult:
        if len(beat_times) < 3:
            return RhythmAnalysisResult(rhythm_type="free", stability_score=0.0)

        intervals = np.diff(np.array(beat_times, dtype=np.float64))
        mean_interval = float(np.mean(intervals))
        if mean_interval <= 0:
            return RhythmAnalysisResult(rhythm_type="unstable", stability_score=0.0)

        coeff_var = float(np.std(intervals) / (mean_interval + 1e-8))
        stability = max(0.0, min(1.0, 1.0 - coeff_var))

        if coeff_var <= 0.08:
            rhythm_type = "stable"
        elif coeff_var <= 0.18:
            rhythm_type = "unstable"
        else:
            rhythm_type = "free"

        return RhythmAnalysisResult(rhythm_type=rhythm_type, stability_score=stability)
