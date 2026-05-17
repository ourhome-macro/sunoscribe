from __future__ import annotations

from .types import AgentRevisionContext, RvcJobSpec


class RvcPrepareAgent:
    """Deterministic RVC job spec preparation over revision-scoped artifacts."""

    def prepare(
        self,
        context: AgentRevisionContext,
        *,
        voice_model_id: str,
        transpose_semitones: int = 0,
        mode: str = "score_guided",
        rvc_backend: str | None = None,
    ) -> RvcJobSpec:
        warnings: list[str] = []
        normalized_mode = str(mode or "score_guided").strip().lower()
        if normalized_mode not in {"score_guided", "voice_conversion"}:
            normalized_mode = "score_guided"
            warnings.append("unsupported_rvc_mode_defaulted_to_score_guided")

        vocal_ids = context.artifact_ids_by_type("vocals_stem")
        accompaniment_ids = context.artifact_ids_by_type("accompaniment_stem")
        corrected_f0_ids = context.artifact_ids_by_type("corrected_f0_track")

        if not vocal_ids:
            warnings.append("missing_vocals_stem_artifact")
        if normalized_mode == "score_guided" and not accompaniment_ids:
            warnings.append("missing_accompaniment_artifact")
        if normalized_mode == "score_guided" and not corrected_f0_ids:
            warnings.append("missing_corrected_f0_artifact")
        if normalized_mode == "voice_conversion":
            warnings.append("voice_conversion_mode_not_score_guided")

        return RvcJobSpec(
            mode=normalized_mode,
            project_id=context.project_id,
            revision_id=context.revision_id,
            vocal_stem_artifact_id=vocal_ids[0] if vocal_ids else None,
            accompaniment_artifact_id=accompaniment_ids[0] if accompaniment_ids else None,
            corrected_f0_artifact_id=corrected_f0_ids[0] if corrected_f0_ids else None,
            voice_model_id=str(voice_model_id).strip(),
            transpose_semitones=int(transpose_semitones),
            rvc_backend=str(rvc_backend or "external").strip() or "external",
            warnings=warnings,
        )
