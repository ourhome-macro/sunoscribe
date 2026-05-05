from __future__ import annotations

from typing import Any, Callable

from app.modules.analysis_ir import AnalysisIR
from app.modules.score_ir import ScoreIR, ScoreIRBuilder, ScoreIRSerializer


class ScoreBuildService:
    """Build ScoreIR and export-facing score_data from transcription outputs."""

    def __init__(
        self,
        *,
        score_ir_builder: ScoreIRBuilder | None,
        invoke_builder: Callable[[Any, list[dict], AnalysisIR | None], ScoreIR],
    ) -> None:
        self.score_ir_builder = score_ir_builder
        self.invoke_builder = invoke_builder

    def build(
        self,
        *,
        pitch_result_obj: Any,
        lyrics_segments: list[dict],
        analysis_ir_obj: AnalysisIR | None,
    ) -> tuple[ScoreIR, dict | None]:
        if self.score_ir_builder is None:
            raise RuntimeError("score_ir_builder is not configured")
        score_ir_obj = self.invoke_builder(pitch_result_obj, lyrics_segments, analysis_ir_obj)
        return score_ir_obj, ScoreIRSerializer.to_score_data(score_ir_obj)
