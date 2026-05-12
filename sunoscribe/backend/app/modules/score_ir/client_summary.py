from __future__ import annotations

from typing import Any

from app.modules.pitch.reason_codes import LOW_CONFIDENCE, UNCERTAIN

LOW_CONFIDENCE_THRESHOLD = 0.55
_STABLE_REASON_CODES = {
    "large_quantize_error",
    "octave_outlier",
    "possible_fragmentation",
    "possible_overmerge",
    "short_gap_bridged",
    "short_note_absorbed",
    "octave_jump_corrected",
    "phrase_median_smoothed",
    LOW_CONFIDENCE,
    UNCERTAIN,
    "low_voiced_ratio",
    "too_short",
    "too_unstable",
    "outside_vocal_range",
    "likely_harmonic",
    "likely_accompaniment_bleed",
    "duplicate_fragment",
    "overlaps_stronger_candidate",
    "insufficient_onset_evidence",
    "silence_or_breath_region",
    "suspected_vibrato",
    "suspected_glide",
    "dp_fallback",
    "rhythm_grid_unavailable",
    "dp_no_candidate_path",
    "quantizer_backend_unsupported",
}
_REASON_CODE_ALIASES = {
    "high_quantize_error": "large_quantize_error",
    "fragmentation_risk": "possible_fragmentation",
    "overmerge_risk": "possible_overmerge",
}


def build_score_revision_client_summary(
    *,
    revision: Any,
    export_status: str | None = None,
) -> dict[str, Any]:
    score_ir = getattr(revision, "score_ir", None)
    if not isinstance(score_ir, dict):
        score_ir = {}
    score_notes = build_score_note_client_summaries(score_ir)
    low_confidence_notes = [note for note in score_notes if _is_low_confidence_note(note)]
    return {
        "revision_id": str(getattr(revision, "id", "") or ""),
        "parent_revision_id": str(getattr(revision, "parent_revision_id", "") or "")
        if getattr(revision, "parent_revision_id", None)
        else None,
        "note_count": len(score_notes),
        "uncertain_note_count": sum(1 for note in score_notes if bool(note.get("uncertain"))),
        "low_confidence_note_count": len(low_confidence_notes),
        "low_confidence_regions": _low_confidence_regions(low_confidence_notes),
        "export_status": export_status or _export_status_from_revision(revision),
        "score_notes": score_notes,
    }


def build_score_note_client_summaries(score_ir: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(score_ir, dict):
        return []
    notes = score_ir.get("notes")
    if not isinstance(notes, list):
        return []
    return [_note_summary(note) for note in notes if isinstance(note, dict) and str(note.get("id") or "").strip()]


def stable_reason_codes(raw_codes: Any) -> list[str]:
    if not isinstance(raw_codes, list):
        return []
    normalized: list[str] = []
    for raw_code in raw_codes:
        code = str(raw_code or "").strip().lower()
        if not code:
            continue
        code = _REASON_CODE_ALIASES.get(code, code)
        if code in _STABLE_REASON_CODES and code not in normalized:
            normalized.append(code)
    return normalized


def _note_summary(note: dict[str, Any]) -> dict[str, Any]:
    confidence = _safe_optional_float(note.get("confidence"))
    reason_codes = stable_reason_codes(note.get("reason_codes"))
    if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD and LOW_CONFIDENCE not in reason_codes:
        reason_codes.append(LOW_CONFIDENCE)
    uncertain = bool(note.get("uncertain")) or bool(reason_codes)
    if uncertain and UNCERTAIN not in reason_codes:
        reason_codes.append(UNCERTAIN)
    return {
        "note_id": str(note.get("id") or ""),
        "pitch": str(note.get("pitch") or ""),
        "onset_tick": _coalesce_tick(note.get("onset_tick"), note.get("start_tick")),
        "duration_tick": _coalesce_tick(note.get("duration_tick")),
        "measure": _safe_optional_int(note.get("measure_num") if note.get("measure_num") is not None else note.get("measure")),
        "beat": _safe_optional_float(
            note.get("beat_position") if note.get("beat_position") is not None else note.get("beat")
        ),
        "confidence": confidence,
        "uncertain": uncertain,
        "reason_codes": reason_codes,
        "source_candidate_id": _optional_str(note.get("source_candidate_id")),
        "quantized_note_id": _optional_str(note.get("quantized_note_id")),
    }


def _is_low_confidence_note(note_summary: dict[str, Any]) -> bool:
    confidence = note_summary.get("confidence")
    return (isinstance(confidence, int | float) and float(confidence) < LOW_CONFIDENCE_THRESHOLD) or (
        LOW_CONFIDENCE in (note_summary.get("reason_codes") or [])
    )


def _low_confidence_regions(low_confidence_notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    previous_measure: int | None = None
    previous_note_id: str | None = None
    for note in low_confidence_notes:
        measure = note.get("measure")
        note_id = str(note.get("note_id") or "")
        if current is None or not isinstance(measure, int) or previous_measure is None or measure > previous_measure + 1:
            if current is not None:
                current["end_note_id"] = previous_note_id
                regions.append(current)
            current = {
                "start_note_id": note_id,
                "end_note_id": note_id,
                "measure_start": measure if isinstance(measure, int) else None,
                "measure_end": measure if isinstance(measure, int) else None,
                "note_count": 0,
            }
        current["end_note_id"] = note_id
        if isinstance(measure, int):
            if current.get("measure_start") is None:
                current["measure_start"] = measure
            current["measure_end"] = measure
        current["note_count"] = int(current.get("note_count") or 0) + 1
        previous_measure = measure if isinstance(measure, int) else previous_measure
        previous_note_id = note_id
    if current is not None:
        current["end_note_id"] = previous_note_id
        regions.append(current)
    return regions


def _export_status_from_revision(revision: Any) -> str:
    artifacts = list(getattr(revision, "artifacts", None) or [])
    if not artifacts:
        return "unknown"
    statuses = [str(getattr(artifact, "status", "") or "").strip().lower() for artifact in artifacts]
    if statuses and all(status == "available" for status in statuses):
        return "available"
    if any(status == "failed" for status in statuses):
        return "failed"
    return "partial"


def _coalesce_tick(*values: Any) -> int | None:
    for value in values:
        parsed = _safe_optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
