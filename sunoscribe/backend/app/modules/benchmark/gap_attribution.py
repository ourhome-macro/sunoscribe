from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from .midi_metrics import MidiMetricConfig, NoteEvent, compute_midi_continuity_metrics, compute_midi_metrics
from .reason_codes import (
    CANDIDATE_FORMATION_CONTEXT_PITCH_MISMATCH,
    CANDIDATE_FORMATION_LOW_CONFIDENCE,
    CANDIDATE_FORMATION_LOW_COVERAGE,
    CANDIDATE_FORMATION_LOW_OCTAVE_CLUSTER,
    CANDIDATE_FORMATION_NO_LOCAL_CONTEXT,
    CANDIDATE_FORMATION_PITCH_OUT_OF_RANGE,
    CANDIDATE_FORMATION_SAFE,
    CANDIDATE_FORMATION_SHORT_FRAGMENT_CLUSTER,
    CANDIDATE_FORMATION_SPLITS_BIG_GAP,
    CANDIDATE_FORMATION_TOO_SHORT,
    DEBUG_ATTR_BRIDGE_SEGMENTATION_REJECTED,
    DEBUG_ATTR_BRIDGE_SEGMENTATION_WEAK_QUALITY,
    DEBUG_ATTR_SELECTOR_REJECTED_UNSTABLE_SEGMENT,
    DEBUG_ATTR_SELECTOR_REJECTED_WEAK_SEGMENT,
    DELETED_CANDIDATE_LARGE_PITCH_JUMP,
    DELETED_CANDIDATE_LOW_CONFIDENCE,
    DELETED_CANDIDATE_OVERLAP,
    DELETED_CANDIDATE_SELECTOR_REMOVED,
    DELETED_CANDIDATE_SHORT_DURATION,
    GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED,
    GAP_ATTR_F0_EXISTS_NO_CANDIDATE,
    GAP_ATTR_QUANTIZATION_EXPORT_INDUCED,
    GAP_ATTR_RAW_F0_MISSING,
    GAP_ATTR_REFERENCE_ONLY_UNMATCHED,
    GAP_ATTR_UNCLASSIFIED,
    LOST_EXPECTED_CANDIDATE_EXISTS_SELECTOR_REMOVED,
    LOST_EXPECTED_F0_EXISTS_NO_CANDIDATE,
    LOST_EXPECTED_QUANTIZATION_EXPORT_INDUCED,
    LOST_EXPECTED_RAW_F0_MISSING,
    LOST_EXPECTED_REFERENCE_ONLY,
    LOST_EXPECTED_UNCLASSIFIED,
    SELECTOR_STAGE_CONFLICT_OR_BIG_LEAP,
    SELECTOR_STAGE_FINAL_SHORT_CLEANUP,
    SELECTOR_STAGE_LOW_CONFIDENCE,
    SELECTOR_STAGE_PITCH_RANGE,
    SELECTOR_STAGE_POSTPROCESS_REMOVED,
    SELECTOR_STAGE_SHORT_DURATION,
    SELECTOR_STAGE_UNKNOWN,
)
from app.modules.pitch.reason_codes import BRIDGE_FROM_F0_CONTOUR, CONTOUR_TO_CANDIDATE_BRIDGE


GAP_THRESHOLD_SEC = 0.5
MIN_EVIDENCE_OVERLAP_SEC = 0.05
MIN_F0_SPAN_SEC = 0.12
LOW_CONFIDENCE_THRESHOLD = 0.35
SHORT_CANDIDATE_THRESHOLD_SEC = 0.18
LARGE_PITCH_JUMP_SEMITONES = 7.0
TOP_LIMIT = 12


def build_gap_attribution(
    *,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    f0_track_path: Path | None,
    vocal_activity_path: Path | None,
    pitch_contours_path: Path | None,
    note_candidates_path: Path | None,
    selected_melody_path: Path | None,
    quantized_notes_path: Path | None,
    score_ir_path: Path | None,
    metrics_payload: dict[str, Any] | None = None,
    config: MidiMetricConfig | None = None,
) -> dict[str, Any]:
    """Build read-only P3/P4 gap attribution from benchmark artifacts.

    Reference MIDI is used only to label benchmark misses. This function never
    mutates production artifacts and never writes MIDI, MusicXML, ScoreIR, or DB
    revisions.
    """

    config = config or MidiMetricConfig()
    metrics_payload = metrics_payload or {}
    f0_payload = _read_json(f0_track_path)
    vocal_payload = _read_json(vocal_activity_path)
    contour_payload = _read_json(pitch_contours_path)
    candidate_payload = _read_json(note_candidates_path)
    selected_payload = _read_json(selected_melody_path)
    quantized_payload = _read_json(quantized_notes_path)
    score_ir_payload = _read_json(score_ir_path)

    raw_candidates = _candidate_records(candidate_payload, source="raw_notes")
    legacy_selected = _candidate_records(candidate_payload, source="legacy_selected_notes")
    selected_notes = _artifact_records(selected_payload, kind="selected_melody")
    selected_rejected_candidates = _selected_rejected_candidate_records(selected_payload)
    quantized_notes = _artifact_records(quantized_payload, kind="quantized_notes")
    score_ir_notes = _artifact_records(score_ir_payload, kind="score_ir")
    pitch_contours = _contour_records(contour_payload)
    contour_bridge_rejections = _contour_bridge_rejection_records(candidate_payload)
    f0_frames = _f0_frames(f0_payload)
    f0_spans = _voiced_spans(f0_frames)
    low_f0_spans = _low_confidence_spans(f0_frames, _vocal_activity_segments(vocal_payload, f0_payload))

    final_records = _note_events_to_records(predicted_notes, prefix="predicted_midi")
    if not final_records:
        final_records = score_ir_notes or quantized_notes or selected_notes

    octave_shift = _benchmark_pitch_shift(metrics_payload, expected_notes, predicted_notes, config)
    expected_matches = _match_expected_to_predicted(
        expected_notes,
        predicted_notes,
        config=config,
        predicted_pitch_shift=octave_shift,
    )
    matched_expected = {expected_index for expected_index, _ in expected_matches}
    unmatched_expected = [note for index, note in enumerate(expected_notes) if index not in matched_expected]

    top_gaps = _top_gap_attributions(
        final_records=final_records,
        raw_candidates=raw_candidates,
        selected_notes=selected_notes,
        quantized_notes=quantized_notes,
        score_ir_notes=score_ir_notes,
        pitch_contours=pitch_contours,
        contour_bridge_rejections=contour_bridge_rejections,
        f0_spans=f0_spans,
        low_f0_spans=low_f0_spans,
        selected_rejected_candidates=selected_rejected_candidates,
    )
    top_lost_expected = _top_lost_expected_notes(
        unmatched_expected=unmatched_expected,
        raw_candidates=raw_candidates,
        selected_notes=selected_notes,
        quantized_notes=quantized_notes,
        score_ir_notes=score_ir_notes,
        predicted_records=_note_events_to_records(predicted_notes, prefix="predicted_midi"),
        pitch_contours=pitch_contours,
        contour_bridge_rejections=contour_bridge_rejections,
        f0_spans=f0_spans,
        low_f0_spans=low_f0_spans,
        pitch_shift_for_reference_eval=octave_shift,
        selected_rejected_candidates=selected_rejected_candidates,
    )
    top_deleted_candidates = _top_deleted_candidates(
        raw_candidates=raw_candidates,
        selected_notes=selected_notes,
        lost_expected=top_lost_expected,
    )
    quantization_export = _quantization_export_diagnostics(
        selected_notes=selected_notes,
        quantized_notes=quantized_notes,
        score_ir_notes=score_ir_notes,
        predicted_notes=predicted_notes,
        quantized_payload=quantized_payload,
    )

    gap_reason_counts = Counter(_first_reason(item) for item in top_gaps)
    lost_reason_counts = Counter(_first_reason(item) for item in top_lost_expected)
    deleted_reason_counts: Counter[str] = Counter()
    for item in top_deleted_candidates:
        for reason in item.get("diagnostic_reason_codes") or []:
            deleted_reason_counts[str(reason)] += 1

    return {
        "version": "gap_attribution_v1",
        "diagnostic_only": True,
        "reference_midi_used_for_benchmark_attribution_only": True,
        "production_mutation_allowed": False,
        "thresholds": {
            "gap_threshold_sec": GAP_THRESHOLD_SEC,
            "min_evidence_overlap_sec": MIN_EVIDENCE_OVERLAP_SEC,
            "min_f0_span_sec": MIN_F0_SPAN_SEC,
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
            "short_candidate_threshold_sec": SHORT_CANDIDATE_THRESHOLD_SEC,
            "large_pitch_jump_semitones": LARGE_PITCH_JUMP_SEMITONES,
        },
        "benchmark_metrics": _benchmark_metric_summary(metrics_payload),
        "reference_alignment": {
            "expected_note_count": len(expected_notes),
            "predicted_note_count": len(predicted_notes),
            "matched_expected_count": len(matched_expected),
            "unmatched_expected_count": len(unmatched_expected),
            "pitch_shift_for_reference_eval_semitones": octave_shift,
            "onset_tolerance_sec": config.onset_tolerance_sec,
            "pitch_tolerance_semitones": config.pitch_tolerance_semitones,
        },
        "layer_summary": _layer_summary(
            raw_candidates=raw_candidates,
            legacy_selected=legacy_selected,
            selected_notes=selected_notes,
            quantized_notes=quantized_notes,
            score_ir_notes=score_ir_notes,
            predicted_notes=predicted_notes,
            pitch_contours=pitch_contours,
            f0_spans=f0_spans,
            low_f0_spans=low_f0_spans,
        ),
        "retention": _retention_summary(
            raw_candidates=raw_candidates,
            legacy_selected=legacy_selected,
            selected_notes=selected_notes,
            quantized_notes=quantized_notes,
            score_ir_notes=score_ir_notes,
            predicted_notes=predicted_notes,
        ),
        "contour_to_candidate_bridge": _contour_bridge_summary(candidate_payload),
        "debug_attribution": _debug_attribution_summary(
            selected_rejected_candidates=selected_rejected_candidates,
            contour_bridge_rejections=contour_bridge_rejections,
        ),
        "top_gaps": top_gaps,
        "top_lost_expected_notes": top_lost_expected,
        "top_deleted_candidates": top_deleted_candidates,
        "quantization_export": quantization_export,
        "reason_counts": {
            "gaps": dict(sorted(gap_reason_counts.items())),
            "lost_expected_notes": dict(sorted(lost_reason_counts.items())),
            "deleted_candidates": dict(sorted(deleted_reason_counts.items())),
        },
        "recommended_fix_focus": _recommended_fix_focus(
            gap_reason_counts=gap_reason_counts,
            lost_reason_counts=lost_reason_counts,
            deleted_reason_counts=deleted_reason_counts,
            quantization_export=quantization_export,
        ),
    }


def build_gap_attribution_markdown(
    *,
    sample_id: str,
    sample_title: str,
    gap_attribution: dict[str, Any] | None,
) -> str:
    if not isinstance(gap_attribution, dict):
        return f"# Gap Attribution - {sample_title}\n\n- available: false\n"

    metrics = gap_attribution.get("benchmark_metrics") if isinstance(gap_attribution.get("benchmark_metrics"), dict) else {}
    reference = gap_attribution.get("reference_alignment") if isinstance(gap_attribution.get("reference_alignment"), dict) else {}
    layer_summary = gap_attribution.get("layer_summary") if isinstance(gap_attribution.get("layer_summary"), dict) else {}
    retention = gap_attribution.get("retention") if isinstance(gap_attribution.get("retention"), dict) else {}
    contour_bridge = gap_attribution.get("contour_to_candidate_bridge") if isinstance(gap_attribution.get("contour_to_candidate_bridge"), dict) else {}
    reason_counts = gap_attribution.get("reason_counts") if isinstance(gap_attribution.get("reason_counts"), dict) else {}
    fix_focus = gap_attribution.get("recommended_fix_focus") if isinstance(gap_attribution.get("recommended_fix_focus"), list) else []
    quantization_export = gap_attribution.get("quantization_export") if isinstance(gap_attribution.get("quantization_export"), dict) else {}

    lines = [
        f"# Gap Attribution - {sample_title}",
        "",
        f"- sample_id: `{sample_id}`",
        "- diagnostic_only: true",
        "- reference_midi_used_for_benchmark_attribution_only: true",
        "- production_mutation_allowed: false",
        "",
        "## Benchmark Status",
        f"- quality_status: {_fmt(metrics.get('quality_status'))}",
        f"- note_recall: {_fmt(metrics.get('note_recall'))}",
        f"- note_f1: {_fmt(metrics.get('note_f1'))}",
        f"- matched_notes: {_fmt(metrics.get('matched_note_count'))}",
        f"- midi_coverage_ratio: {_fmt(metrics.get('midi_coverage_ratio'))}",
        f"- first_note_delay_sec: {_fmt(metrics.get('first_note_delay_sec'))}",
        f"- gap50_ratio: {_fmt(metrics.get('gap50_ratio'))}",
        "",
        "## Reference Alignment",
        f"- expected_note_count: {_fmt(reference.get('expected_note_count'))}",
        f"- predicted_note_count: {_fmt(reference.get('predicted_note_count'))}",
        f"- matched_expected_count: {_fmt(reference.get('matched_expected_count'))}",
        f"- unmatched_expected_count: {_fmt(reference.get('unmatched_expected_count'))}",
        f"- pitch_shift_for_reference_eval_semitones: {_fmt(reference.get('pitch_shift_for_reference_eval_semitones'))}",
        "",
        "## Layer Counts",
        "| layer | count | total_duration_sec | gap50_ratio |",
        "| --- | ---: | ---: | ---: |",
    ]
    for layer in [
        "f0_voiced_spans",
        "pitch_contours",
        "note_candidates_raw_notes",
        "note_candidates_selected_notes",
        "selected_melody_selected_notes",
        "quantized_notes",
        "score_ir_notes",
        "predicted_midi",
    ]:
        row = layer_summary.get(layer) if isinstance(layer_summary.get(layer), dict) else {}
        lines.append(
            f"| {layer} | {_fmt(row.get('count'))} | {_fmt(row.get('total_duration_sec'))} | {_fmt(row.get('gap50_ratio'))} |"
        )
    lines.extend(
        [
            "",
            "## Retention",
            f"- raw_to_selected_count_ratio: {_fmt(retention.get('raw_to_selected_count_ratio'))}",
            f"- selected_to_quantized_count_ratio: {_fmt(retention.get('selected_to_quantized_count_ratio'))}",
            f"- quantized_to_score_ir_count_ratio: {_fmt(retention.get('quantized_to_score_ir_count_ratio'))}",
            f"- score_ir_to_predicted_count_ratio: {_fmt(retention.get('score_ir_to_predicted_count_ratio'))}",
            "",
            "## Contour-To-Candidate Bridge",
            f"- enabled: {_fmt(contour_bridge.get('enabled'))}",
            f"- candidate_count: {_fmt(contour_bridge.get('candidate_count'))}",
            f"- accepted_count: {_fmt(contour_bridge.get('accepted_count'))}",
            f"- rejected_count: {_fmt(contour_bridge.get('rejected_count'))}",
            f"- raw_bridge_candidate_count: {_fmt(contour_bridge.get('raw_bridge_candidate_count'))}",
            f"- selected_bridge_candidate_count: {_fmt(contour_bridge.get('selected_bridge_candidate_count'))}",
            f"- guard_reason_counts: {_fmt(contour_bridge.get('guard_reason_counts'))}",
            "",
            "## Reason Counts",
            f"- gaps: {_fmt(reason_counts.get('gaps'))}",
            f"- lost_expected_notes: {_fmt(reason_counts.get('lost_expected_notes'))}",
            f"- deleted_candidates: {_fmt(reason_counts.get('deleted_candidates'))}",
            "",
            "## Recommended Fix Focus",
        ]
    )
    if fix_focus:
        lines.extend(f"- {item}" for item in fix_focus)
    else:
        lines.append("- none")

    lines.extend(_markdown_gap_table(gap_attribution.get("top_gaps"), heading="## Top Gaps"))
    lines.extend(_markdown_lost_expected_table(gap_attribution.get("top_lost_expected_notes"), heading="## Top Lost Expected Notes"))
    lines.extend(_markdown_deleted_candidate_table(gap_attribution.get("top_deleted_candidates"), heading="## Top Deleted Candidates"))
    lines.extend(
        [
            "",
            "## Quantization / Export",
            f"- quantizer_backend: {_fmt(quantization_export.get('quantizer_backend'))}",
            f"- fallback_used: {_fmt(quantization_export.get('fallback_used'))}",
            f"- max_selected_to_quantized_onset_shift_sec: {_fmt(quantization_export.get('max_selected_to_quantized_onset_shift_sec'))}",
            f"- max_score_ir_to_predicted_onset_shift_sec: {_fmt(quantization_export.get('max_score_ir_to_predicted_onset_shift_sec'))}",
            f"- count_drop_stage: {_fmt(quantization_export.get('count_drop_stage'))}",
            "",
        ]
    )
    return "\n".join(lines)


def _top_gap_attributions(
    *,
    final_records: list[dict[str, Any]],
    raw_candidates: list[dict[str, Any]],
    selected_notes: list[dict[str, Any]],
    quantized_notes: list[dict[str, Any]],
    score_ir_notes: list[dict[str, Any]],
    pitch_contours: list[dict[str, Any]],
    contour_bridge_rejections: list[dict[str, Any]],
    f0_spans: list[dict[str, Any]],
    low_f0_spans: list[dict[str, Any]],
    selected_rejected_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = sorted([record for record in final_records if _duration(record) > 0], key=lambda item: (_start(item), _end(item)))
    gaps: list[dict[str, Any]] = []
    for index in range(len(records) - 1):
        left = records[index]
        right = records[index + 1]
        start = _end(left)
        end = _start(right)
        duration = end - start
        if duration < GAP_THRESHOLD_SEC:
            continue
        interval = {"start": start, "end": end}
        attribution = _classify_interval(
            interval=interval,
            raw_candidates=raw_candidates,
            selected_notes=selected_notes,
            quantized_notes=quantized_notes,
            score_ir_notes=score_ir_notes,
            pitch_contours=pitch_contours,
            contour_bridge_rejections=contour_bridge_rejections,
            f0_spans=f0_spans,
            low_f0_spans=low_f0_spans,
            selected_rejected_candidates=selected_rejected_candidates,
        )
        gaps.append(
            {
                "gap_id": f"gap_{len(gaps) + 1:05d}",
                "start_sec": _round(start),
                "end_sec": _round(end),
                "duration_sec": _round(duration),
                "left_note": _public_note(left),
                "right_note": _public_note(right),
                **attribution,
            }
        )
    gaps.sort(key=lambda item: (-float(item.get("duration_sec") or 0.0), float(item.get("start_sec") or 0.0)))
    return gaps[:TOP_LIMIT]


def _top_lost_expected_notes(
    *,
    unmatched_expected: list[NoteEvent],
    raw_candidates: list[dict[str, Any]],
    selected_notes: list[dict[str, Any]],
    quantized_notes: list[dict[str, Any]],
    score_ir_notes: list[dict[str, Any]],
    predicted_records: list[dict[str, Any]],
    pitch_contours: list[dict[str, Any]],
    contour_bridge_rejections: list[dict[str, Any]],
    f0_spans: list[dict[str, Any]],
    low_f0_spans: list[dict[str, Any]],
    pitch_shift_for_reference_eval: int,
    selected_rejected_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, note in enumerate(unmatched_expected):
        interval = {"start": float(note.start), "end": float(note.end), "pitch": float(note.pitch)}
        raw_matches = _records_matching_note(raw_candidates, note, pitch_shift=pitch_shift_for_reference_eval)
        selected_matches = _records_matching_note(selected_notes, note, pitch_shift=pitch_shift_for_reference_eval)
        quantized_matches = _records_matching_note(quantized_notes, note, pitch_shift=pitch_shift_for_reference_eval)
        score_matches = _records_matching_note(score_ir_notes, note, pitch_shift=pitch_shift_for_reference_eval)
        predicted_matches = _records_matching_note(predicted_records, note, pitch_shift=pitch_shift_for_reference_eval)
        contour_matches = _records_matching_note(pitch_contours, note, pitch_shift=pitch_shift_for_reference_eval, pitch_tolerance=1.5)
        bridge_rejections = _records_overlapping(contour_bridge_rejections, note.start, note.end)
        selector_rejections = _records_overlapping(selected_rejected_candidates, note.start, note.end)
        f0_overlap = _span_overlap_summary(f0_spans, note.start, note.end, target_pitch=note.pitch, pitch_shift=pitch_shift_for_reference_eval)
        low_f0_overlap = _span_overlap_summary(low_f0_spans, note.start, note.end)

        if raw_matches and not selected_matches:
            reason = LOST_EXPECTED_CANDIDATE_EXISTS_SELECTOR_REMOVED
            category = GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED
        elif (f0_overlap.get("duration_sec") or 0.0) >= MIN_EVIDENCE_OVERLAP_SEC and not raw_matches:
            reason = LOST_EXPECTED_F0_EXISTS_NO_CANDIDATE
            category = GAP_ATTR_F0_EXISTS_NO_CANDIDATE
        elif low_f0_overlap.get("duration_sec") and not raw_matches:
            reason = LOST_EXPECTED_RAW_F0_MISSING
            category = GAP_ATTR_RAW_F0_MISSING
        elif selected_matches and (not quantized_matches or not score_matches or not predicted_matches):
            reason = LOST_EXPECTED_QUANTIZATION_EXPORT_INDUCED
            category = GAP_ATTR_QUANTIZATION_EXPORT_INDUCED
        elif raw_matches or selected_matches or quantized_matches or score_matches or predicted_matches:
            reason = LOST_EXPECTED_REFERENCE_ONLY
            category = GAP_ATTR_REFERENCE_ONLY_UNMATCHED
        elif not raw_matches and not selected_matches and not f0_overlap.get("duration_sec"):
            reason = LOST_EXPECTED_REFERENCE_ONLY
            category = GAP_ATTR_REFERENCE_ONLY_UNMATCHED
        else:
            reason = LOST_EXPECTED_UNCLASSIFIED
            category = GAP_ATTR_UNCLASSIFIED

        rows.append(
            {
                "expected_id": f"lost_exp_{index + 1:05d}",
                "start_sec": _round(note.start),
                "end_sec": _round(note.end),
                "duration_sec": _round(note.duration),
                "pitch_midi": int(note.pitch),
                "pitch_name": _pitch_name(int(note.pitch)),
                "classification": category,
                "reason_codes": [reason],
                "evidence": {
                    "raw_candidate_matches": len(raw_matches),
                    "selected_matches": len(selected_matches),
                    "quantized_matches": len(quantized_matches),
                    "score_ir_matches": len(score_matches),
                    "predicted_midi_matches": len(predicted_matches),
                    "pitch_contour_matches": len(contour_matches),
                    "contour_bridge_rejections_in_gap": len(bridge_rejections),
                    "top_contour_bridge_rejections": _compact_bridge_rejection_records(bridge_rejections),
                    "top_contour_bridge_segmentation_summaries": _compact_bridge_segmentation_summaries(bridge_rejections),
                    "debug_attribution": _debug_attribution_summary(
                        selected_rejected_candidates=selector_rejections,
                        contour_bridge_rejections=bridge_rejections,
                    ),
                    "f0_voiced_overlap": f0_overlap,
                    "low_confidence_or_unvoiced_overlap": low_f0_overlap,
                    "pitch_shift_for_reference_eval_semitones": pitch_shift_for_reference_eval,
                    "reference_midi_used_for_benchmark_attribution_only": True,
                },
                "nearest_raw_candidate": _public_note(raw_matches[0]) if raw_matches else _nearest_public_note(raw_candidates, interval),
                "nearest_selected_note": _public_note(selected_matches[0]) if selected_matches else _nearest_public_note(selected_notes, interval),
            }
        )
    rows.sort(key=lambda item: (-float(item.get("duration_sec") or 0.0), float(item.get("start_sec") or 0.0)))
    return rows[:TOP_LIMIT]


def _top_deleted_candidates(
    *,
    raw_candidates: list[dict[str, Any]],
    selected_notes: list[dict[str, Any]],
    lost_expected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deleted: list[dict[str, Any]] = []
    for index, candidate in enumerate(raw_candidates):
        matching_selected = _matching_records(candidate, selected_notes, pitch_tolerance=1.0)
        if matching_selected:
            continue
        prev_candidate = raw_candidates[index - 1] if index > 0 else None
        next_candidate = raw_candidates[index + 1] if index + 1 < len(raw_candidates) else None
        pitch_jump = _candidate_pitch_jump(candidate, prev_candidate, next_candidate)
        selected_overlap = _max_overlap(candidate, selected_notes)
        nearby_lost = _nearby_lost_expected(candidate, lost_expected)
        confidence = _as_float(candidate.get("confidence"))
        duration = _duration(candidate)
        diagnostic_reasons = [DELETED_CANDIDATE_SELECTOR_REMOVED]
        if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
            diagnostic_reasons.append(DELETED_CANDIDATE_LOW_CONFIDENCE)
        if duration < SHORT_CANDIDATE_THRESHOLD_SEC:
            diagnostic_reasons.append(DELETED_CANDIDATE_SHORT_DURATION)
        if pitch_jump is not None and pitch_jump >= LARGE_PITCH_JUMP_SEMITONES:
            diagnostic_reasons.append(DELETED_CANDIDATE_LARGE_PITCH_JUMP)
        if selected_overlap.get("duration_sec"):
            diagnostic_reasons.append(DELETED_CANDIDATE_OVERLAP)
        deleted.append(
            {
                **_public_note(candidate),
                "diagnostic_reason_codes": diagnostic_reasons,
                "input_reason_codes": list(candidate.get("reason_codes") or []),
                "confidence": _round_optional(confidence),
                "pitch_jump_semitones": _round_optional(pitch_jump),
                "nearest_selected_overlap": selected_overlap,
                "nearby_lost_expected": nearby_lost,
                "impact_score": _round((confidence if confidence is not None else 0.5) * max(0.0, duration)),
            }
        )
    deleted.sort(key=lambda item: (-float(item.get("impact_score") or 0.0), float(item.get("start_sec") or 0.0)))
    return deleted[:TOP_LIMIT]


def _classify_interval(
    *,
    interval: dict[str, float],
    raw_candidates: list[dict[str, Any]],
    selected_notes: list[dict[str, Any]],
    quantized_notes: list[dict[str, Any]],
    score_ir_notes: list[dict[str, Any]],
    pitch_contours: list[dict[str, Any]],
    contour_bridge_rejections: list[dict[str, Any]],
    f0_spans: list[dict[str, Any]],
    low_f0_spans: list[dict[str, Any]],
    selected_rejected_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    start = float(interval["start"])
    end = float(interval["end"])
    raw_inside = _records_overlapping(raw_candidates, start, end)
    selected_inside = _records_overlapping(selected_notes, start, end)
    quantized_inside = _records_overlapping(quantized_notes, start, end)
    score_inside = _records_overlapping(score_ir_notes, start, end)
    contours_inside = _records_overlapping(pitch_contours, start, end)
    bridge_rejections_inside = _records_overlapping(contour_bridge_rejections, start, end)
    selector_rejections_inside = _records_overlapping(selected_rejected_candidates, start, end)
    f0_overlap = _span_overlap_summary(f0_spans, start, end)
    low_f0_overlap = _span_overlap_summary(low_f0_spans, start, end)

    deleted_inside = [candidate for candidate in raw_inside if not _matching_records(candidate, selected_notes, pitch_tolerance=1.0)]
    if deleted_inside:
        classification = GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED
        evidence_note = deleted_inside[0]
    elif (f0_overlap.get("duration_sec") or 0.0) >= MIN_EVIDENCE_OVERLAP_SEC and not raw_inside:
        classification = GAP_ATTR_F0_EXISTS_NO_CANDIDATE
        evidence_note = contours_inside[0] if contours_inside else None
    elif low_f0_overlap.get("duration_sec") and not raw_inside:
        classification = GAP_ATTR_RAW_F0_MISSING
        evidence_note = None
    elif selected_inside and (not quantized_inside or not score_inside):
        classification = GAP_ATTR_QUANTIZATION_EXPORT_INDUCED
        evidence_note = selected_inside[0]
    else:
        classification = GAP_ATTR_UNCLASSIFIED
        evidence_note = raw_inside[0] if raw_inside else selected_inside[0] if selected_inside else None

    return {
        "classification": classification,
        "reason_codes": [classification],
        "evidence": {
            "raw_candidates_in_gap": len(raw_inside),
            "deleted_raw_candidates_in_gap": len(deleted_inside),
            "selected_notes_in_gap": len(selected_inside),
            "quantized_notes_in_gap": len(quantized_inside),
            "score_ir_notes_in_gap": len(score_inside),
            "pitch_contours_in_gap": len(contours_inside),
            "contour_bridge_rejections_in_gap": len(bridge_rejections_inside),
            "top_contour_bridge_rejections": _compact_bridge_rejection_records(bridge_rejections_inside),
            "top_contour_bridge_segmentation_summaries": _compact_bridge_segmentation_summaries(bridge_rejections_inside),
            "debug_attribution": _debug_attribution_summary(
                selected_rejected_candidates=selector_rejections_inside,
                contour_bridge_rejections=bridge_rejections_inside,
            ),
            "selector_stage_reason_counts": _selector_stage_reason_counts(deleted_inside, selected_notes=selected_notes),
            "top_selector_removed_candidates": _compact_selector_removed_candidates(deleted_inside, selected_notes=selected_notes),
            "candidate_formation_opportunity": _candidate_formation_opportunity(
                deleted_inside,
                gap_start=start,
                gap_end=end,
                left_context=_previous_record(selected_notes, start),
                right_context=_next_record(selected_notes, end),
            ),
            "f0_voiced_overlap": f0_overlap,
            "low_confidence_or_unvoiced_overlap": low_f0_overlap,
        },
        "top_evidence_note": _public_note(evidence_note) if evidence_note else None,
    }


def _quantization_export_diagnostics(
    *,
    selected_notes: list[dict[str, Any]],
    quantized_notes: list[dict[str, Any]],
    score_ir_notes: list[dict[str, Any]],
    predicted_notes: list[NoteEvent],
    quantized_payload: Any,
) -> dict[str, Any]:
    selected_by_candidate_id = {str(note.get("candidate_id")): note for note in selected_notes if note.get("candidate_id")}
    quantized_shifts: list[dict[str, Any]] = []
    for note in quantized_notes:
        source_id = str(note.get("source_candidate_id") or "")
        selected = selected_by_candidate_id.get(source_id)
        if not selected:
            continue
        quantized_start = _as_float(note.get("quantized_start_time_sec"))
        quantized_duration = _as_float(note.get("quantized_duration_sec"))
        onset_shift = None if quantized_start is None else quantized_start - _start(selected)
        duration_ratio = _safe_divide(quantized_duration, _duration(selected)) if quantized_duration is not None else None
        quantized_shifts.append(
            {
                "source_candidate_id": source_id,
                "selected_start_sec": _round(_start(selected)),
                "performance_start_sec": _round(_start(note)),
                "quantized_start_sec": _round_optional(quantized_start),
                "onset_shift_sec": _round_optional(onset_shift),
                "duration_ratio": _round_optional(duration_ratio),
                "quantize_error_sec": _round_optional(note.get("quantize_error_sec")),
                "reason_codes": list(note.get("reason_codes") or []),
            }
        )
    quantized_shifts.sort(key=lambda item: -abs(float(item.get("onset_shift_sec") or 0.0)))

    predicted_records = _note_events_to_records(predicted_notes, prefix="predicted_midi")
    export_shifts: list[dict[str, Any]] = []
    for index, score_note in enumerate(score_ir_notes[: len(predicted_records)]):
        predicted = predicted_records[index]
        onset_shift = _start(predicted) - _start(score_note)
        duration_ratio = _safe_divide(_duration(predicted), _duration(score_note))
        export_shifts.append(
            {
                "score_ir_id": score_note.get("id"),
                "predicted_index": index,
                "score_ir_start_sec": _round(_start(score_note)),
                "predicted_start_sec": _round(_start(predicted)),
                "onset_shift_sec": _round(onset_shift),
                "duration_ratio": _round_optional(duration_ratio),
            }
        )
    export_shifts.sort(key=lambda item: -abs(float(item.get("onset_shift_sec") or 0.0)))

    count_drop_stage = None
    if len(quantized_notes) < len(selected_notes):
        count_drop_stage = "selected_to_quantized"
    elif len(score_ir_notes) < len(quantized_notes):
        count_drop_stage = "quantized_to_score_ir"
    elif len(predicted_notes) < len(score_ir_notes):
        count_drop_stage = "score_ir_to_predicted_midi"

    summary = quantized_payload.get("summary") if isinstance(quantized_payload, dict) and isinstance(quantized_payload.get("summary"), dict) else {}
    diagnostics = quantized_payload.get("diagnostics") if isinstance(quantized_payload, dict) and isinstance(quantized_payload.get("diagnostics"), dict) else {}
    return {
        "quantizer_backend": quantized_payload.get("quantizer_backend") if isinstance(quantized_payload, dict) else None,
        "requested_quantizer_backend": quantized_payload.get("requested_quantizer_backend") if isinstance(quantized_payload, dict) else None,
        "fallback_used": quantized_payload.get("fallback_used") if isinstance(quantized_payload, dict) else None,
        "fallback_reason": quantized_payload.get("fallback_reason") if isinstance(quantized_payload, dict) else None,
        "count_drop_stage": count_drop_stage,
        "selected_count": len(selected_notes),
        "quantized_count": len(quantized_notes),
        "score_ir_count": len(score_ir_notes),
        "predicted_count": len(predicted_notes),
        "mean_quantize_error_sec": _round_optional(summary.get("mean_quantize_error_sec") or diagnostics.get("mean_quantize_error_sec")),
        "p95_quantize_error_sec": _round_optional(summary.get("p95_quantize_error_sec") or diagnostics.get("p95_quantize_error_sec")),
        "max_quantize_error_sec": _round_optional(summary.get("max_quantize_error_sec") or diagnostics.get("max_quantize_error_sec")),
        "max_selected_to_quantized_onset_shift_sec": _round_optional(_max_abs(item.get("onset_shift_sec") for item in quantized_shifts)),
        "max_score_ir_to_predicted_onset_shift_sec": _round_optional(_max_abs(item.get("onset_shift_sec") for item in export_shifts)),
        "top_selected_to_quantized_shifts": quantized_shifts[:TOP_LIMIT],
        "top_score_ir_to_predicted_shifts": export_shifts[:TOP_LIMIT],
    }


def _candidate_records(payload: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    melody = payload.get("melody_candidates") if isinstance(payload.get("melody_candidates"), dict) else {}
    if source == "raw_notes":
        items = melody.get("notes") if isinstance(melody.get("notes"), list) else payload.get("notes")
        prefix = "raw_candidate"
    elif source == "legacy_selected_notes":
        items = melody.get("selected_notes") if isinstance(melody.get("selected_notes"), list) else payload.get("selected_notes")
        prefix = "legacy_selected"
    else:
        items = []
        prefix = source
    return _records_from_items(items if isinstance(items, list) else [], kind=source, prefix=prefix)


def _selected_rejected_candidate_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("rejected_candidates") if isinstance(payload.get("rejected_candidates"), list) else []
    return _records_from_items(items, kind="selected_rejected_candidate", prefix="selected_rejected")


def _contour_bridge_summary(candidate_payload: Any) -> dict[str, Any]:
    if not isinstance(candidate_payload, dict):
        return {"available": False}
    melody = candidate_payload.get("melody_candidates") if isinstance(candidate_payload.get("melody_candidates"), dict) else {}
    analysis = melody.get("analysis_info") if isinstance(melody.get("analysis_info"), dict) else {}
    bridge = analysis.get("contour_to_candidate_bridge") if isinstance(analysis.get("contour_to_candidate_bridge"), dict) else {}
    raw_notes = melody.get("notes") if isinstance(melody.get("notes"), list) else []
    selected_notes = melody.get("selected_notes") if isinstance(melody.get("selected_notes"), list) else []
    raw_bridge_notes = [note for note in raw_notes if _is_contour_bridge_note(note)]
    selected_bridge_notes = [note for note in selected_notes if _is_contour_bridge_note(note)]
    return {
        "available": bool(bridge),
        "version": bridge.get("version"),
        "enabled": bridge.get("enabled"),
        "candidate_count": bridge.get("candidate_count"),
        "accepted_count": bridge.get("accepted_count"),
        "rejected_count": bridge.get("rejected_count"),
        "guard_reason_counts": dict(bridge.get("guard_reason_counts") or {}) if isinstance(bridge.get("guard_reason_counts"), dict) else {},
        "accepted_candidates": _compact_bridge_items(bridge.get("accepted_candidates")),
        "top_rejected_candidates": _compact_bridge_items(bridge.get("rejected_candidates")),
        "raw_bridge_candidate_count": len(raw_bridge_notes),
        "selected_bridge_candidate_count": len(selected_bridge_notes),
        "raw_bridge_candidates": [_public_note(record) for record in _records_from_items(raw_bridge_notes, kind="raw_notes", prefix="raw_bridge")[:TOP_LIMIT]],
        "selected_bridge_candidates": [_public_note(record) for record in _records_from_items(selected_bridge_notes, kind="legacy_selected_notes", prefix="selected_bridge")[:TOP_LIMIT]],
    }


def _contour_bridge_rejection_records(candidate_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(candidate_payload, dict):
        return []
    melody = candidate_payload.get("melody_candidates") if isinstance(candidate_payload.get("melody_candidates"), dict) else {}
    analysis = melody.get("analysis_info") if isinstance(melody.get("analysis_info"), dict) else {}
    bridge = analysis.get("contour_to_candidate_bridge") if isinstance(analysis.get("contour_to_candidate_bridge"), dict) else {}
    items = bridge.get("rejected_candidates") if isinstance(bridge.get("rejected_candidates"), list) else []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        start = _as_float(_first_present(item, "start_time_sec", "start_time", "start"))
        end = _as_float(_first_present(item, "end_time_sec", "end_time", "end"))
        duration = _as_float(_first_present(item, "duration_sec", "duration"))
        if start is None:
            start = _as_float(_first_present(evidence, "candidate_start_time_sec", "source_start_time_sec"))
        if end is None:
            end = _as_float(_first_present(evidence, "candidate_end_time_sec", "source_end_time_sec"))
        if end is None and start is not None and duration is not None:
            end = start + duration
        if start is None or end is None:
            continue
        record = {
            "id": str(item.get("candidate_id") or f"contour_bridge_rejection_{index + 1:05d}"),
            "kind": "contour_bridge_rejection",
            "start_sec": float(start),
            "end_sec": float(end),
            "duration_sec": max(0.0, float(end) - float(start)),
            "pitch_midi": _pitch_midi(item),
            "confidence": _as_float(_first_present(item, "confidence", "mean_confidence")),
            "reason_codes": list(item.get("reason_codes") or []) if isinstance(item.get("reason_codes"), list) else [],
            "candidate_id": item.get("candidate_id"),
            "source_contour_id": item.get("source_contour_id") or evidence.get("source_contour_id"),
            "source_contour_ids": [str(item.get("source_contour_id") or evidence.get("source_contour_id"))]
            if item.get("source_contour_id") or evidence.get("source_contour_id")
            else [],
            "candidate_origin": CONTOUR_TO_CANDIDATE_BRIDGE,
            "contour_bridge_guard_reason_codes": list(item.get("contour_bridge_guard_reason_codes") or [])
            if isinstance(item.get("contour_bridge_guard_reason_codes"), list)
            else [],
            "contour_bridge_evidence": evidence,
        }
        if record["pitch_midi"] is not None:
            record["pitch_name"] = _pitch_name(int(round(float(record["pitch_midi"]))))
        records.append(record)
    records.sort(key=lambda item: (_start(item), _end(item), _pitch(item) or -1.0, str(item.get("id") or "")))
    return records


def _is_contour_bridge_note(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("candidate_origin") or "") == CONTOUR_TO_CANDIDATE_BRIDGE:
        return True
    reason_codes = [str(code) for code in item.get("reason_codes") or []] if isinstance(item.get("reason_codes"), list) else []
    return CONTOUR_TO_CANDIDATE_BRIDGE in reason_codes or BRIDGE_FROM_F0_CONTOUR in reason_codes


def _compact_bridge_items(items: Any) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return compacted
    for item in items[:TOP_LIMIT]:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        compacted.append(
            {
                "candidate_id": item.get("candidate_id"),
                "source_contour_id": item.get("source_contour_id"),
                "start_time_sec": _round_optional(item.get("start_time_sec")),
                "end_time_sec": _round_optional(item.get("end_time_sec")),
                "duration_sec": _round_optional(item.get("duration_sec")),
                "pitch_center_midi": _round_optional(item.get("pitch_center_midi")),
                "confidence": _round_optional(item.get("confidence")),
                "reason_codes": list(item.get("reason_codes") or []),
                "guard_reason_codes": list(item.get("contour_bridge_guard_reason_codes") or []),
                "nearest_raw_gap": evidence.get("nearest_raw_gap") if isinstance(evidence.get("nearest_raw_gap"), dict) else None,
                "raw_overlap_duration_sec": _round_optional(evidence.get("raw_overlap_duration_sec")),
                "selected_context_overlap_duration_sec": _round_optional(evidence.get("selected_context_overlap_duration_sec")),
                "vocal_activity_overlap_ratio": _round_optional(evidence.get("vocal_activity_overlap_ratio")),
            }
        )
    return compacted


def _compact_bridge_rejection_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for record in records[:TOP_LIMIT]:
        evidence = record.get("contour_bridge_evidence") if isinstance(record.get("contour_bridge_evidence"), dict) else {}
        compacted.append(
            {
                **_public_note(record),
                "source_contour_id": record.get("source_contour_id"),
                "guard_reason_codes": list(record.get("contour_bridge_guard_reason_codes") or []),
                "nearest_raw_gap": evidence.get("nearest_raw_gap") if isinstance(evidence.get("nearest_raw_gap"), dict) else None,
                "raw_overlap_duration_sec": _round_optional(evidence.get("raw_overlap_duration_sec")),
                "selected_context_overlap_duration_sec": _round_optional(evidence.get("selected_context_overlap_duration_sec")),
                "vocal_activity_overlap_ratio": _round_optional(evidence.get("vocal_activity_overlap_ratio")),
                "segmentation_attempt_summary": _compact_segmentation_attempt_summary(evidence.get("segmentation_attempt_summary")),
            }
        )
    return compacted


def _compact_bridge_segmentation_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for record in records[:TOP_LIMIT]:
        evidence = record.get("contour_bridge_evidence") if isinstance(record.get("contour_bridge_evidence"), dict) else {}
        summary = _compact_segmentation_attempt_summary(evidence.get("segmentation_attempt_summary"))
        if not summary:
            continue
        summaries.append(
            {
                "candidate_id": record.get("candidate_id"),
                "source_contour_id": record.get("source_contour_id"),
                **summary,
            }
        )
    return summaries


def _compact_segmentation_attempt_summary(summary: Any) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    attempts = summary.get("attempts") if isinstance(summary.get("attempts"), list) else []
    compact_attempts = [_compact_segmentation_attempt(item) for item in attempts[:TOP_LIMIT] if isinstance(item, dict)]
    return {
        "enabled": summary.get("enabled"),
        "candidate_count": summary.get("candidate_count"),
        "attempted_count": summary.get("attempted_count"),
        "accepted_count": summary.get("accepted_count"),
        "rejected_count": summary.get("rejected_count"),
        "reason_codes": list(summary.get("reason_codes") or []),
        "guard_reason_counts": dict(summary.get("guard_reason_counts") or {})
        if isinstance(summary.get("guard_reason_counts"), dict)
        else {},
        "quality_factor_stats": _segmentation_evidence_stats(attempts, "quality_factor"),
        "mad_semitones_stats": _segmentation_evidence_stats(attempts, "mad_semitones"),
        "span_semitones_stats": _segmentation_evidence_stats(attempts, "span_semitones"),
        "attempt_guard_reason_counts": _guard_reason_counts(attempts),
        "attempts": compact_attempts,
    }


def _compact_segmentation_attempt(item: dict[str, Any]) -> dict[str, Any]:
    segmentation_evidence = item.get("segmentation_evidence") if isinstance(item.get("segmentation_evidence"), dict) else {}
    return {
        "candidate_id": item.get("candidate_id"),
        "start_time_sec": _round_optional(item.get("start_time_sec")),
        "end_time_sec": _round_optional(item.get("end_time_sec")),
        "duration_sec": _round_optional(item.get("duration_sec")),
        "pitch_center_midi": _round_optional(item.get("pitch_center_midi")),
        "confidence": _round_optional(item.get("confidence")),
        "guard_reason_codes": list(item.get("guard_reason_codes") or []),
        "nearest_raw_gap": item.get("nearest_raw_gap") if isinstance(item.get("nearest_raw_gap"), dict) else None,
        "raw_overlap_duration_sec": _round_optional(item.get("raw_overlap_duration_sec")),
        "left_context_pitch_midi": _round_optional(item.get("left_context_pitch_midi")),
        "right_context_pitch_midi": _round_optional(item.get("right_context_pitch_midi")),
        "left_context_gap_sec": _round_optional(item.get("left_context_gap_sec")),
        "right_context_gap_sec": _round_optional(item.get("right_context_gap_sec")),
        "segment_index": segmentation_evidence.get("segment_index"),
        "segment_frame_count": segmentation_evidence.get("segment_frame_count"),
        "segment_pitch_range_semitones": _round_optional(segmentation_evidence.get("segment_pitch_range_semitones")),
        "segment_mean_confidence": _round_optional(segmentation_evidence.get("segment_mean_confidence")),
    }


def _selector_stage_reason_counts(candidates: list[dict[str, Any]], *, selected_notes: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for candidate in candidates:
        counts[_selector_stage_reason(candidate, selected_notes=selected_notes)] += 1
    return dict(sorted(counts.items()))


def _compact_selector_removed_candidates(
    candidates: list[dict[str, Any]],
    *,
    selected_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates[:TOP_LIMIT]:
        rows.append(
            {
                **_public_note(candidate),
                "selector_stage_reason": _selector_stage_reason(candidate, selected_notes=selected_notes),
                "segmentation_evidence": _compact_note_segmentation_evidence(candidate.get("segmentation_evidence")),
                "nearest_selected_overlap": _max_overlap(candidate, selected_notes),
            }
        )
    return rows


def _debug_attribution_summary(
    *,
    selected_rejected_candidates: list[dict[str, Any]],
    contour_bridge_rejections: list[dict[str, Any]],
) -> dict[str, Any]:
    selector_summary = _selector_rejected_segmentation_summary(selected_rejected_candidates)
    bridge_summary = _bridge_rejected_segmentation_summary(contour_bridge_rejections)
    reason_codes: list[str] = []
    reason_codes.extend(selector_summary.get("reason_codes") or [])
    reason_codes.extend(bridge_summary.get("reason_codes") or [])
    return {
        "diagnostic_only": True,
        "production_mutation_allowed": False,
        "reason_codes": sorted(set(str(code) for code in reason_codes if code)),
        "selector_rejected_segmentation_summary": selector_summary,
        "bridge_rejected_segmentation_summary": bridge_summary,
    }


def _selector_rejected_segmentation_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    with_evidence = [candidate for candidate in candidates if isinstance(candidate.get("segmentation_evidence"), dict) and candidate.get("segmentation_evidence")]
    reason_codes: list[str] = []
    if any((_as_float((candidate.get("segmentation_evidence") or {}).get("quality_factor")) or 1.0) < 0.55 for candidate in with_evidence):
        reason_codes.append(DEBUG_ATTR_SELECTOR_REJECTED_WEAK_SEGMENT)
    if any(
        ((_as_float((candidate.get("segmentation_evidence") or {}).get("mad_semitones")) or 0.0) >= 1.0)
        or ((_as_float((candidate.get("segmentation_evidence") or {}).get("span_semitones")) or 0.0) >= 3.0)
        for candidate in with_evidence
    ):
        reason_codes.append(DEBUG_ATTR_SELECTOR_REJECTED_UNSTABLE_SEGMENT)
    return {
        "count": len(candidates),
        "with_segmentation_evidence_count": len(with_evidence),
        "reason_codes": sorted(set(reason_codes)),
        "reason_code_counts": _reason_code_counts(candidates),
        "quality_factor_stats": _record_segmentation_evidence_stats(with_evidence, "quality_factor"),
        "mad_semitones_stats": _record_segmentation_evidence_stats(with_evidence, "mad_semitones"),
        "span_semitones_stats": _record_segmentation_evidence_stats(with_evidence, "span_semitones"),
        "examples": _compact_selector_removed_candidates(with_evidence, selected_notes=[])[: min(TOP_LIMIT, 5)],
    }


def _bridge_rejected_segmentation_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    guard_reason_counts: Counter[str] = Counter()
    for record in records:
        evidence = record.get("contour_bridge_evidence") if isinstance(record.get("contour_bridge_evidence"), dict) else {}
        summary = evidence.get("segmentation_attempt_summary") if isinstance(evidence.get("segmentation_attempt_summary"), dict) else {}
        for reason, count in (summary.get("guard_reason_counts") or {}).items() if isinstance(summary.get("guard_reason_counts"), dict) else []:
            guard_reason_counts[str(reason)] += int(count or 0)
        for attempt in summary.get("attempts") if isinstance(summary.get("attempts"), list) else []:
            if isinstance(attempt, dict):
                attempts.append(attempt)
                for reason in attempt.get("guard_reason_codes") or [] if isinstance(attempt.get("guard_reason_codes"), list) else []:
                    guard_reason_counts[str(reason)] += 1

    reason_codes: list[str] = []
    if records or attempts:
        reason_codes.append(DEBUG_ATTR_BRIDGE_SEGMENTATION_REJECTED)
    if any((_as_float((attempt.get("segmentation_evidence") or {}).get("quality_factor")) or 1.0) < 0.55 for attempt in attempts):
        reason_codes.append(DEBUG_ATTR_BRIDGE_SEGMENTATION_WEAK_QUALITY)
    return {
        "count": len(records),
        "attempt_count": len(attempts),
        "reason_codes": sorted(set(reason_codes)),
        "guard_reason_counts": dict(sorted(guard_reason_counts.items())),
        "quality_factor_stats": _segmentation_evidence_stats(attempts, "quality_factor"),
        "mad_semitones_stats": _segmentation_evidence_stats(attempts, "mad_semitones"),
        "span_semitones_stats": _segmentation_evidence_stats(attempts, "span_semitones"),
        "examples": [_compact_segmentation_attempt(attempt) for attempt in attempts[: min(TOP_LIMIT, 5)]],
    }


def _compact_note_segmentation_evidence(evidence: Any) -> dict[str, Any] | None:
    if not isinstance(evidence, dict) or not evidence:
        return None
    keys = [
        "backend",
        "start_frame_index",
        "end_frame_index",
        "voiced_frame_count",
        "frame_hop_sec",
        "avg_confidence",
        "adjusted_confidence",
        "quality_factor",
        "stability_factor",
        "span_factor",
        "mad_semitones",
        "span_semitones",
        "voiced_threshold",
        "jump_threshold_semitones",
    ]
    return {key: evidence.get(key) for key in keys if key in evidence}


def _record_segmentation_evidence_stats(records: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    values = []
    for record in records:
        evidence = record.get("segmentation_evidence") if isinstance(record.get("segmentation_evidence"), dict) else {}
        value = _as_float(evidence.get(key))
        if value is not None and math.isfinite(value):
            values.append(value)
    return _numeric_stats(values)


def _segmentation_evidence_stats(items: list[Any], key: str) -> dict[str, Any] | None:
    values = []
    for item in items:
        if not isinstance(item, dict):
            continue
        evidence = item.get("segmentation_evidence") if isinstance(item.get("segmentation_evidence"), dict) else {}
        value = _as_float(evidence.get(key))
        if value is not None and math.isfinite(value):
            values.append(value)
    return _numeric_stats(values)


def _numeric_stats(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": _round(ordered[0]),
        "median": _round(median(ordered)),
        "max": _round(ordered[-1]),
    }


def _reason_code_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        for reason in record.get("reason_codes") or [] if isinstance(record.get("reason_codes"), list) else []:
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))


def _guard_reason_counts(items: list[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            continue
        for reason in item.get("guard_reason_codes") or [] if isinstance(item.get("guard_reason_codes"), list) else []:
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))


def _selector_stage_reason(candidate: dict[str, Any], *, selected_notes: list[dict[str, Any]]) -> str:
    pitch = _pitch(candidate)
    confidence = _as_float(candidate.get("confidence"))
    duration = _duration(candidate)
    if pitch is None or pitch < 48.0 or pitch > 84.0:
        return SELECTOR_STAGE_PITCH_RANGE
    if duration < SHORT_CANDIDATE_THRESHOLD_SEC and confidence is not None and confidence < 0.62:
        return SELECTOR_STAGE_SHORT_DURATION
    if confidence is not None and confidence < 0.52:
        return SELECTOR_STAGE_LOW_CONFIDENCE
    if duration < SHORT_CANDIDATE_THRESHOLD_SEC:
        return SELECTOR_STAGE_FINAL_SHORT_CLEANUP
    if _max_overlap(candidate, selected_notes).get("duration_sec"):
        return SELECTOR_STAGE_POSTPROCESS_REMOVED
    jump = _candidate_pitch_jump(candidate, None, None)
    if jump is not None and jump >= LARGE_PITCH_JUMP_SEMITONES:
        return SELECTOR_STAGE_CONFLICT_OR_BIG_LEAP
    return SELECTOR_STAGE_UNKNOWN


def _candidate_formation_opportunity(
    candidates: list[dict[str, Any]],
    *,
    gap_start: float,
    gap_end: float,
    left_context: dict[str, Any] | None,
    right_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda item: (_start(item), _end(item), _pitch(item) or -1.0))
    pitches = [_pitch(item) for item in ordered]
    durations = [_duration(item) for item in ordered]
    confidences = [_as_float(item.get("confidence")) for item in ordered]
    total_fragment_duration = sum(duration for duration in durations if duration > 0)
    start = min(_start(item) for item in ordered)
    end = max(_end(item) for item in ordered)
    duration = max(0.0, end - start)
    weighted_pitch = _weighted_average(
        [(pitch, duration) for pitch, duration in zip(pitches, durations) if pitch is not None and duration > 0]
    )
    weighted_confidence = _weighted_average(
        [(confidence, duration) for confidence, duration in zip(confidences, durations) if confidence is not None and duration > 0]
    )
    coverage_ratio = _safe_divide(total_fragment_duration, duration) if duration > 0 else None
    shifted_pitch = weighted_pitch + 12.0 if weighted_pitch is not None and weighted_pitch < 48.0 else weighted_pitch
    left_pitch = _pitch(left_context) if left_context is not None else None
    right_pitch = _pitch(right_context) if right_context is not None else None
    context_pitches = [pitch for pitch in (left_pitch, right_pitch) if pitch is not None]
    reason_codes: list[str] = []
    low_octave_cluster = weighted_pitch is not None and weighted_pitch < 48.0 and shifted_pitch is not None
    if low_octave_cluster:
        reason_codes.append(CANDIDATE_FORMATION_LOW_OCTAVE_CLUSTER)
    elif any(duration < SHORT_CANDIDATE_THRESHOLD_SEC for duration in durations):
        reason_codes.append(CANDIDATE_FORMATION_SHORT_FRAGMENT_CLUSTER)
    if duration < 0.18:
        reason_codes.append(CANDIDATE_FORMATION_TOO_SHORT)
    if weighted_confidence is None or weighted_confidence < 0.62:
        reason_codes.append(CANDIDATE_FORMATION_LOW_CONFIDENCE)
    if coverage_ratio is None or coverage_ratio < 0.45:
        reason_codes.append(CANDIDATE_FORMATION_LOW_COVERAGE)
    if shifted_pitch is None or shifted_pitch < 48.0 or shifted_pitch > 84.0:
        reason_codes.append(CANDIDATE_FORMATION_PITCH_OUT_OF_RANGE)
    if not context_pitches:
        reason_codes.append(CANDIDATE_FORMATION_NO_LOCAL_CONTEXT)
    elif shifted_pitch is not None:
        nearest_delta = min(abs(shifted_pitch - pitch) for pitch in context_pitches)
        if nearest_delta > 4.0:
            reason_codes.append(CANDIDATE_FORMATION_CONTEXT_PITCH_MISMATCH)
    if _would_split_big_gap(gap_start=gap_start, gap_end=gap_end, candidate_start=start, candidate_end=end):
        reason_codes.append(CANDIDATE_FORMATION_SPLITS_BIG_GAP)
    if not any(reason for reason in reason_codes if reason not in {CANDIDATE_FORMATION_LOW_OCTAVE_CLUSTER, CANDIDATE_FORMATION_SHORT_FRAGMENT_CLUSTER}):
        reason_codes.append(CANDIDATE_FORMATION_SAFE)

    return {
        "candidate_count": len(ordered),
        "source_candidate_ids": [str(item.get("candidate_id") or item.get("id") or "") for item in ordered],
        "start_sec": _round(start),
        "end_sec": _round(end),
        "duration_sec": _round(duration),
        "fragment_duration_sec": _round(total_fragment_duration),
        "coverage_ratio": _round_optional(coverage_ratio),
        "pitch_center_midi": _round_optional(weighted_pitch),
        "shifted_pitch_center_midi": _round_optional(shifted_pitch),
        "confidence": _round_optional(weighted_confidence),
        "mean_confidence": _round_optional(weighted_confidence),
        "left_context_pitch_midi": _round_optional(left_pitch),
        "right_context_pitch_midi": _round_optional(right_pitch),
        "left_gap_sec": _round_optional(start - _end(left_context)) if left_context is not None else None,
        "right_gap_sec": _round_optional(_start(right_context) - end) if right_context is not None else None,
        "reason_codes": _unique_text(reason_codes),
        "fragments": [_public_note(item) for item in ordered[:TOP_LIMIT]],
    }


def _previous_record(records: list[dict[str, Any]], end: float) -> dict[str, Any] | None:
    previous = [record for record in records if _end(record) <= end]
    return max(previous, key=lambda item: _end(item), default=None)


def _next_record(records: list[dict[str, Any]], start: float) -> dict[str, Any] | None:
    following = [record for record in records if _start(record) >= start]
    return min(following, key=lambda item: _start(item), default=None)


def _would_split_big_gap(*, gap_start: float, gap_end: float, candidate_start: float, candidate_end: float) -> bool:
    big_gap = GAP_THRESHOLD_SEC
    original_gap = max(0.0, gap_end - gap_start)
    if original_gap <= big_gap:
        return False
    left_gap = max(0.0, candidate_start - gap_start)
    right_gap = max(0.0, gap_end - candidate_end)
    before_big_count = 1 if original_gap > big_gap else 0
    after_big_count = int(left_gap > big_gap) + int(right_gap > big_gap)
    return after_big_count > before_big_count


def _weighted_average(values: list[tuple[float | None, float]]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for value, weight in values:
        if value is None or weight <= 0:
            continue
        numerator += float(value) * float(weight)
        denominator += float(weight)
    if denominator <= 0:
        return None
    return numerator / denominator


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _artifact_records(payload: Any, *, kind: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if kind == "selected_melody":
        items = payload.get("selected_notes") if isinstance(payload.get("selected_notes"), list) else []
    elif kind in {"quantized_notes", "score_ir"}:
        items = payload.get("notes") if isinstance(payload.get("notes"), list) else []
    else:
        items = []
    return _records_from_items(items, kind=kind, prefix=kind)


def _contour_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("contours"), list):
        return []
    return _records_from_items(payload["contours"], kind="pitch_contour", prefix="pitch_contour")


def _records_from_items(items: list[Any], *, kind: str, prefix: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        record = _record_from_item(item, kind=kind, fallback_id=f"{prefix}_{index + 1:05d}")
        if record is not None:
            records.append(record)
    records.sort(key=lambda item: (_start(item), _end(item), _pitch(item) or -1.0))
    return records


def _record_from_item(item: dict[str, Any], *, kind: str, fallback_id: str) -> dict[str, Any] | None:
    if kind == "score_ir":
        start = _as_float(_first_present(item, "performance_start_time_sec", "start_time_sec", "start_time", "onset_sec", "start"))
        end = _as_float(_first_present(item, "performance_end_time_sec", "end_time_sec", "end_time", "offset_sec", "end"))
    else:
        start = _as_float(_first_present(item, "start_time_sec", "start_time", "onset_sec", "start_sec", "start", "time_sec"))
        end = _as_float(_first_present(item, "end_time_sec", "end_time", "offset_sec", "end_sec", "end"))
    duration = _as_float(_first_present(item, "duration_sec", "duration"))
    if start is None:
        return None
    if end is None and duration is not None:
        end = start + duration
    if end is None:
        return None
    pitch = _pitch_midi(item)
    record = {
        "id": str(_first_present(item, "candidate_id", "id", "quantized_note_id") or fallback_id),
        "kind": kind,
        "start_sec": float(start),
        "end_sec": float(end),
        "duration_sec": max(0.0, float(end) - float(start)),
        "pitch_midi": pitch,
        "confidence": _as_float(_first_present(item, "confidence", "mean_confidence", "max_confidence")),
        "reason_codes": list(item.get("reason_codes") or []) if isinstance(item.get("reason_codes"), list) else [],
        "candidate_id": item.get("candidate_id") or item.get("source_candidate_id"),
        "source_candidate_id": item.get("source_candidate_id"),
        "quantized_note_id": item.get("quantized_note_id") or item.get("id") if kind == "quantized_notes" else item.get("quantized_note_id"),
        "source_contour_ids": list(item.get("source_contour_ids") or []) if isinstance(item.get("source_contour_ids"), list) else [],
        "candidate_origin": item.get("candidate_origin"),
        "segmentation_evidence": dict(item.get("segmentation_evidence") or {}) if isinstance(item.get("segmentation_evidence"), dict) else {},
        "contour_bridge_guard_reason_codes": list(item.get("contour_bridge_guard_reason_codes") or []) if isinstance(item.get("contour_bridge_guard_reason_codes"), list) else [],
        "quantized_start_time_sec": _as_float(item.get("quantized_start_time_sec")),
        "quantized_end_time_sec": _as_float(item.get("quantized_end_time_sec")),
        "quantized_duration_sec": _as_float(item.get("quantized_duration_sec")),
        "quantize_error_sec": _as_float(item.get("quantize_error_sec")),
    }
    if record["pitch_midi"] is not None:
        record["pitch_name"] = _pitch_name(int(round(record["pitch_midi"])))
    return record


def _note_events_to_records(notes: list[NoteEvent], *, prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{prefix}_{index + 1:05d}",
            "kind": prefix,
            "start_sec": float(note.start),
            "end_sec": float(note.end),
            "duration_sec": float(note.duration),
            "pitch_midi": float(note.pitch),
            "pitch_name": _pitch_name(int(note.pitch)),
            "confidence": None,
            "reason_codes": [],
        }
        for index, note in enumerate(notes)
    ]


def _f0_frames(payload: Any) -> list[dict[str, Any]]:
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, list):
        return []
    parsed: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        time_sec = _as_float(_first_present(frame, "time_sec", "time", "t", "timestamp"))
        if time_sec is None:
            continue
        pitch = _pitch_midi(frame)
        confidence = _as_float(_first_present(frame, "confidence", "conf", "probability"))
        parsed.append(
            {
                "time_sec": float(time_sec),
                "pitch_midi": pitch,
                "confidence": confidence,
                "voiced": _frame_is_voiced(frame),
            }
        )
    parsed.sort(key=lambda item: item["time_sec"])
    return parsed


def _voiced_spans(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _frame_spans(frames, lambda frame: bool(frame.get("voiced")), source="f0_voiced")


def _low_confidence_spans(frames: list[dict[str, Any]], vocal_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not frames or not vocal_segments:
        return []
    frame_spans = _frame_spans(
        frames,
        lambda frame: not bool(frame.get("voiced")) or (_as_float(frame.get("confidence")) is not None and float(frame.get("confidence")) < LOW_CONFIDENCE_THRESHOLD),
        source="f0_unvoiced_or_low_confidence",
    )
    clipped: list[dict[str, Any]] = []
    for span in frame_spans:
        for segment in vocal_segments:
            start = max(_start(span), _start(segment))
            end = min(_end(span), _end(segment))
            if end - start >= MIN_F0_SPAN_SEC:
                clipped.append(
                    {
                        **span,
                        "start_sec": start,
                        "end_sec": end,
                        "duration_sec": end - start,
                        "vocal_activity_state": segment.get("state"),
                    }
                )
    return _merge_spans(clipped, max_gap_sec=0.05)


def _frame_spans(frames: list[dict[str, Any]], predicate: Any, *, source: str) -> list[dict[str, Any]]:
    if not frames:
        return []
    hop = _infer_hop(frames)
    spans: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    previous_time: float | None = None
    for frame in frames:
        time_sec = float(frame["time_sec"])
        if predicate(frame):
            if current and previous_time is not None and time_sec - previous_time > max(0.05, hop * 2.5):
                spans.append(_span_from_frames(current, hop=hop, source=source))
                current = []
            current.append(frame)
        elif current:
            spans.append(_span_from_frames(current, hop=hop, source=source))
            current = []
        previous_time = time_sec
    if current:
        spans.append(_span_from_frames(current, hop=hop, source=source))
    return [span for span in spans if _duration(span) >= MIN_F0_SPAN_SEC]


def _span_from_frames(frames: list[dict[str, Any]], *, hop: float, source: str) -> dict[str, Any]:
    pitches = [_as_float(frame.get("pitch_midi")) for frame in frames]
    pitches = [pitch for pitch in pitches if pitch is not None]
    confidences = [_as_float(frame.get("confidence")) for frame in frames]
    confidences = [confidence for confidence in confidences if confidence is not None]
    start = float(frames[0]["time_sec"])
    end = float(frames[-1]["time_sec"]) + hop
    return {
        "id": f"{source}_{start:.3f}_{end:.3f}",
        "kind": source,
        "start_sec": start,
        "end_sec": end,
        "duration_sec": max(0.0, end - start),
        "pitch_midi": median(pitches) if pitches else None,
        "confidence": sum(confidences) / len(confidences) if confidences else None,
        "frame_count": len(frames),
    }


def _vocal_activity_segments(vocal_payload: Any, f0_payload: Any) -> list[dict[str, Any]]:
    payloads = [vocal_payload]
    if isinstance(f0_payload, dict):
        payloads.append({"segments": f0_payload.get("vocal_activity")})
    segments: list[dict[str, Any]] = []
    for payload in payloads:
        items = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            state = str(_first_present(item, "state", "label", "activity") or "").lower()
            if state not in {"vocal", "active", "singing", "voiced"}:
                continue
            start = _as_float(_first_present(item, "start_time", "start_time_sec", "start_sec", "start"))
            end = _as_float(_first_present(item, "end_time", "end_time_sec", "end_sec", "end"))
            if start is None or end is None or end <= start:
                continue
            segments.append(
                {
                    "id": f"vocal_activity_{index + 1:05d}",
                    "kind": "vocal_activity",
                    "start_sec": float(start),
                    "end_sec": float(end),
                    "duration_sec": float(end) - float(start),
                    "state": state,
                    "voiced_ratio": _as_float(item.get("voiced_ratio")),
                    "confidence": _as_float(_first_present(item, "mean_confidence", "confidence")),
                }
            )
    return _merge_spans(segments, max_gap_sec=0.03)


def _merge_spans(spans: list[dict[str, Any]], *, max_gap_sec: float) -> list[dict[str, Any]]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda item: (_start(item), _end(item)))
    merged: list[dict[str, Any]] = []
    current = dict(ordered[0])
    for span in ordered[1:]:
        if _start(span) - _end(current) <= max_gap_sec:
            current["end_sec"] = max(_end(current), _end(span))
            current["duration_sec"] = _end(current) - _start(current)
            current["frame_count"] = (current.get("frame_count") or 0) + (span.get("frame_count") or 0)
        else:
            merged.append(current)
            current = dict(span)
    merged.append(current)
    return merged


def _match_expected_to_predicted(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig,
    predicted_pitch_shift: int,
) -> list[tuple[int, int]]:
    match_config = config
    if config.auto_octave_normalize:
        match_config = MidiMetricConfig(
            onset_tolerance_sec=config.onset_tolerance_sec,
            pitch_tolerance_semitones=config.pitch_tolerance_semitones,
            octave_tolerance_semitones=-1,
            auto_octave_normalize=False,
        )
    edges: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(expected_notes):
        for predicted_index, predicted in enumerate(predicted_notes):
            shifted_pitch = int(predicted.pitch) + int(predicted_pitch_shift)
            onset_delta = abs(float(predicted.start) - float(expected.start))
            if onset_delta > match_config.onset_tolerance_sec:
                continue
            pitch_cost = _pitch_match_cost(int(expected.pitch), shifted_pitch, config=match_config)
            if pitch_cost is None:
                continue
            duration_cost = 1.0 - _duration_iou(expected, NoteEvent(start=predicted.start, end=predicted.end, pitch=shifted_pitch))
            edges.append((onset_delta + pitch_cost + duration_cost * 0.01, expected_index, predicted_index))
    edges.sort(key=lambda item: item[0])
    used_expected: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[tuple[int, int]] = []
    for _, expected_index, predicted_index in edges:
        if expected_index in used_expected or predicted_index in used_predicted:
            continue
        used_expected.add(expected_index)
        used_predicted.add(predicted_index)
        matches.append((expected_index, predicted_index))
    return matches


def _pitch_match_cost(expected_pitch: int, predicted_pitch: int, *, config: MidiMetricConfig) -> float | None:
    pitch_delta = abs(int(expected_pitch) - int(predicted_pitch))
    if pitch_delta <= config.pitch_tolerance_semitones:
        return float(pitch_delta)
    if pitch_delta == 1:
        return float(pitch_delta + 100)
    if config.octave_tolerance_semitones > 0 and pitch_delta == config.octave_tolerance_semitones:
        return float(pitch_delta + 100)
    return None


def _duration_iou(expected: NoteEvent, predicted: NoteEvent) -> float:
    intersection = max(0.0, min(expected.end, predicted.end) - max(expected.start, predicted.start))
    union = max(expected.end, predicted.end) - min(expected.start, predicted.start)
    if union <= 0 or math.isclose(union, 0.0):
        return 0.0
    return intersection / union


def _records_matching_note(
    records: list[dict[str, Any]],
    note: NoteEvent,
    *,
    pitch_shift: int,
    pitch_tolerance: float = 0.5,
) -> list[dict[str, Any]]:
    matches = []
    for record in records:
        pitch = _pitch(record)
        if pitch is None:
            continue
        if abs((pitch + pitch_shift) - float(note.pitch)) > pitch_tolerance:
            continue
        if _overlap_seconds(_start(record), _end(record), float(note.start), float(note.end)) >= MIN_EVIDENCE_OVERLAP_SEC:
            matches.append(record)
    matches.sort(key=lambda item: -_overlap_seconds(_start(item), _end(item), float(note.start), float(note.end)))
    return matches


def _matching_records(record: dict[str, Any], records: list[dict[str, Any]], *, pitch_tolerance: float) -> list[dict[str, Any]]:
    pitch = _pitch(record)
    matches = []
    for other in records:
        other_pitch = _pitch(other)
        if pitch is not None and other_pitch is not None and abs(pitch - other_pitch) > pitch_tolerance:
            continue
        if _overlap_seconds(_start(record), _end(record), _start(other), _end(other)) >= MIN_EVIDENCE_OVERLAP_SEC:
            matches.append(other)
    matches.sort(key=lambda item: -_overlap_seconds(_start(record), _end(record), _start(item), _end(item)))
    return matches


def _records_overlapping(records: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    overlaps = [record for record in records if _overlap_seconds(_start(record), _end(record), start, end) >= MIN_EVIDENCE_OVERLAP_SEC]
    overlaps.sort(key=lambda item: (-_overlap_seconds(_start(item), _end(item), start, end), _start(item)))
    return overlaps


def _span_overlap_summary(
    spans: list[dict[str, Any]],
    start: float,
    end: float,
    *,
    target_pitch: float | None = None,
    pitch_shift: int = 0,
) -> dict[str, Any]:
    total = 0.0
    matched_total = 0.0
    max_overlap = 0.0
    best: dict[str, Any] | None = None
    for span in spans:
        overlap = _overlap_seconds(_start(span), _end(span), start, end)
        if overlap <= 0:
            continue
        total += overlap
        pitch = _pitch(span)
        pitch_matches = target_pitch is None or (pitch is not None and abs((pitch + pitch_shift) - target_pitch) <= 1.5)
        if pitch_matches:
            matched_total += overlap
        if overlap > max_overlap:
            max_overlap = overlap
            best = span
    return {
        "duration_sec": _round(total),
        "pitch_matched_duration_sec": _round(matched_total) if target_pitch is not None else None,
        "best_span": _public_note(best) if best else None,
    }


def _layer_summary(
    *,
    raw_candidates: list[dict[str, Any]],
    legacy_selected: list[dict[str, Any]],
    selected_notes: list[dict[str, Any]],
    quantized_notes: list[dict[str, Any]],
    score_ir_notes: list[dict[str, Any]],
    predicted_notes: list[NoteEvent],
    pitch_contours: list[dict[str, Any]],
    f0_spans: list[dict[str, Any]],
    low_f0_spans: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "f0_voiced_spans": _record_layer_stats(f0_spans),
        "f0_unvoiced_or_low_confidence_spans": _record_layer_stats(low_f0_spans),
        "pitch_contours": _record_layer_stats(pitch_contours),
        "note_candidates_raw_notes": _record_layer_stats(raw_candidates),
        "note_candidates_selected_notes": _record_layer_stats(legacy_selected),
        "selected_melody_selected_notes": _record_layer_stats(selected_notes),
        "quantized_notes": _record_layer_stats(quantized_notes),
        "score_ir_notes": _record_layer_stats(score_ir_notes),
        "predicted_midi": _note_event_layer_stats(predicted_notes),
    }


def _record_layer_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    events = [NoteEvent(start=_start(record), end=_end(record), pitch=int(round(_pitch(record) or 60))) for record in records]
    return _event_layer_stats(events)


def _note_event_layer_stats(notes: list[NoteEvent]) -> dict[str, Any]:
    return _event_layer_stats(notes)


def _event_layer_stats(notes: list[NoteEvent]) -> dict[str, Any]:
    if not notes:
        return {"count": 0, "total_duration_sec": 0.0, "gap50_ratio": None, "big_gap_count": None}
    continuity = compute_midi_continuity_metrics(notes).to_dict()
    return {
        "count": len(notes),
        "total_duration_sec": _round(sum(note.duration for note in notes)),
        "gap50_ratio": continuity.get("gap50_ratio"),
        "big_gap_count": continuity.get("big_gap_count"),
    }


def _retention_summary(
    *,
    raw_candidates: list[dict[str, Any]],
    legacy_selected: list[dict[str, Any]],
    selected_notes: list[dict[str, Any]],
    quantized_notes: list[dict[str, Any]],
    score_ir_notes: list[dict[str, Any]],
    predicted_notes: list[NoteEvent],
) -> dict[str, Any]:
    return {
        "raw_candidate_count": len(raw_candidates),
        "legacy_selected_count": len(legacy_selected),
        "selected_count": len(selected_notes),
        "quantized_count": len(quantized_notes),
        "score_ir_count": len(score_ir_notes),
        "predicted_count": len(predicted_notes),
        "raw_to_selected_count_ratio": _round_optional(_safe_divide(len(selected_notes), len(raw_candidates))),
        "legacy_selected_to_selected_count_ratio": _round_optional(_safe_divide(len(selected_notes), len(legacy_selected))),
        "selected_to_quantized_count_ratio": _round_optional(_safe_divide(len(quantized_notes), len(selected_notes))),
        "quantized_to_score_ir_count_ratio": _round_optional(_safe_divide(len(score_ir_notes), len(quantized_notes))),
        "score_ir_to_predicted_count_ratio": _round_optional(_safe_divide(len(predicted_notes), len(score_ir_notes))),
    }


def _benchmark_metric_summary(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    metrics = metrics_payload.get("metrics") if isinstance(metrics_payload.get("metrics"), dict) else {}
    diagnostics = metrics_payload.get("diagnostics") if isinstance(metrics_payload.get("diagnostics"), dict) else {}
    audibility = metrics_payload.get("audibility") if isinstance(metrics_payload.get("audibility"), dict) else {}
    continuity = metrics_payload.get("continuity") if isinstance(metrics_payload.get("continuity"), dict) else {}
    quality = metrics_payload.get("quality_gate") if isinstance(metrics_payload.get("quality_gate"), dict) else {}
    return {
        "quality_status": quality.get("status") or metrics_payload.get("status"),
        "note_recall": _first_present(metrics, "note_recall") if metrics else diagnostics.get("note_recall"),
        "note_f1": _first_present(metrics, "note_f1") if metrics else diagnostics.get("note_f1"),
        "matched_note_count": _first_present(metrics, "matched_note_count") if metrics else diagnostics.get("matched_note_count"),
        "predicted_note_count": _first_present(metrics, "predicted_note_count") if metrics else diagnostics.get("predicted_note_count"),
        "expected_note_count": _first_present(metrics, "expected_note_count") if metrics else diagnostics.get("expected_note_count"),
        "midi_coverage_ratio": audibility.get("midi_coverage_ratio"),
        "first_note_delay_sec": audibility.get("first_note_delay_sec"),
        "gap50_ratio": continuity.get("gap50_ratio"),
        "big_gap_count": continuity.get("big_gap_count"),
        "large_jump_ratio": continuity.get("large_jump_ratio"),
        "short_note_ratio": continuity.get("short_note_ratio"),
    }


def _recommended_fix_focus(
    *,
    gap_reason_counts: Counter[str],
    lost_reason_counts: Counter[str],
    deleted_reason_counts: Counter[str],
    quantization_export: dict[str, Any],
) -> list[str]:
    focus: list[str] = []
    if gap_reason_counts.get(GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED) or lost_reason_counts.get(LOST_EXPECTED_CANDIDATE_EXISTS_SELECTOR_REMOVED):
        focus.append("selector/segmentation review: raw candidates exist but are not retained; inspect deleted candidate evidence before changing RMVPE thresholds")
    if gap_reason_counts.get(GAP_ATTR_F0_EXISTS_NO_CANDIDATE) or lost_reason_counts.get(LOST_EXPECTED_F0_EXISTS_NO_CANDIDATE):
        focus.append("post-F0 contour bridge: voiced F0 spans exist without note candidates; add conservative bridge with explicit reason_codes and evidence")
    if gap_reason_counts.get(GAP_ATTR_RAW_F0_MISSING) or lost_reason_counts.get(LOST_EXPECTED_RAW_F0_MISSING):
        focus.append("raw F0 diagnostics: vocal activity contains unvoiced/low-confidence gaps; do not tune RMVPE threshold without separate evidence")
    if gap_reason_counts.get(GAP_ATTR_QUANTIZATION_EXPORT_INDUCED) or lost_reason_counts.get(LOST_EXPECTED_QUANTIZATION_EXPORT_INDUCED) or quantization_export.get("count_drop_stage"):
        focus.append("dp_v1/export policy review: selected notes exist before quantization/export; fix policy rather than fabricating F0")
    if deleted_reason_counts.get(DELETED_CANDIDATE_SHORT_DURATION):
        focus.append("segmentation cleanup: many deleted raw candidates are short; prefer conservative merge/bridge over aggressive deletion")
    return focus


def _benchmark_pitch_shift(metrics_payload: dict[str, Any], expected_notes: list[NoteEvent], predicted_notes: list[NoteEvent], config: MidiMetricConfig) -> int:
    metrics = metrics_payload.get("metrics") if isinstance(metrics_payload.get("metrics"), dict) else {}
    shift = _as_int(metrics.get("octave_shift_applied"))
    if shift is not None:
        return shift
    if expected_notes and predicted_notes:
        try:
            return int(compute_midi_metrics(expected_notes, predicted_notes, config=config).octave_shift_applied or 0)
        except Exception:
            return 0
    return 0


def _frame_is_voiced(frame: dict[str, Any]) -> bool:
    voiced = _first_present(frame, "voiced", "is_voiced")
    if voiced is not None:
        return bool(voiced)
    state = str(_first_present(frame, "state", "label") or "").lower()
    if state in {"voiced", "active", "vocal", "singing"}:
        return True
    confidence = _as_float(_first_present(frame, "confidence", "conf", "probability"))
    pitch = _pitch_midi(frame)
    return pitch is not None and (confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD)


def _pitch_midi(item: dict[str, Any]) -> float | None:
    value = _as_float(_first_present(item, "pitch_midi", "midi_pitch", "pitch_center_midi", "midi_float"))
    if value is not None:
        return value
    frequency = _as_float(_first_present(item, "frequency_hz", "f0_hz", "frequency", "f0"))
    if frequency is not None and frequency > 0:
        return 69.0 + 12.0 * math.log2(frequency / 440.0)
    pitch_name = _first_present(item, "pitch", "pitch_name")
    if isinstance(pitch_name, str):
        return _parse_pitch_name(pitch_name)
    return None


def _parse_pitch_name(value: str) -> float | None:
    match = value.strip().upper().replace("\u266f", "#").replace("\u266d", "B")
    if len(match) < 2:
        return None
    if len(match) >= 3 and match[1] in {"#", "B"}:
        name = match[:2]
        octave_text = match[2:]
    else:
        name = match[:1]
        octave_text = match[1:]
    pitch_classes = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
    if name not in pitch_classes:
        return None
    try:
        octave = int(octave_text)
    except ValueError:
        return None
    return float((octave + 1) * 12 + pitch_classes[name])


def _pitch_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[int(pitch) % 12]}{int(pitch) // 12 - 1}"


def _candidate_pitch_jump(candidate: dict[str, Any], previous: dict[str, Any] | None, next_candidate: dict[str, Any] | None) -> float | None:
    pitch = _pitch(candidate)
    if pitch is None:
        return None
    jumps = []
    for other in [previous, next_candidate]:
        if other is None:
            continue
        other_pitch = _pitch(other)
        if other_pitch is not None:
            jumps.append(abs(pitch - other_pitch))
    return max(jumps) if jumps else None


def _nearby_lost_expected(candidate: dict[str, Any], lost_expected: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    center = (_start(candidate) + _end(candidate)) / 2.0
    for lost in lost_expected:
        lost_center = (float(lost.get("start_sec") or 0.0) + float(lost.get("end_sec") or 0.0)) / 2.0
        distance = abs(center - lost_center)
        if distance > 0.75:
            continue
        if best is None or distance < best[0]:
            best = (distance, lost)
    if best is None:
        return None
    lost = best[1]
    return {
        "expected_id": lost.get("expected_id"),
        "distance_sec": _round(best[0]),
        "classification": lost.get("classification"),
        "reason_codes": lost.get("reason_codes"),
    }


def _max_overlap(record: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    best_overlap = 0.0
    best: dict[str, Any] | None = None
    for other in records:
        overlap = _overlap_seconds(_start(record), _end(record), _start(other), _end(other))
        if overlap > best_overlap:
            best_overlap = overlap
            best = other
    return {"duration_sec": _round(best_overlap), "note": _public_note(best) if best else None}


def _nearest_public_note(records: list[dict[str, Any]], interval: dict[str, float]) -> dict[str, Any] | None:
    if not records:
        return None
    center = (float(interval["start"]) + float(interval["end"])) / 2.0
    best = min(records, key=lambda item: abs(((_start(item) + _end(item)) / 2.0) - center))
    return _public_note(best)


def _public_note(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    pitch = _pitch(record)
    return {
        "id": record.get("id"),
        "kind": record.get("kind"),
        "start_sec": _round(_start(record)),
        "end_sec": _round(_end(record)),
        "duration_sec": _round(_duration(record)),
        "pitch_midi": _round_optional(pitch),
        "pitch_name": _pitch_name(int(round(pitch))) if pitch is not None else None,
        "confidence": _round_optional(record.get("confidence")),
        "reason_codes": list(record.get("reason_codes") or []),
        "candidate_id": record.get("candidate_id"),
        "source_candidate_id": record.get("source_candidate_id"),
        "quantized_note_id": record.get("quantized_note_id"),
        "candidate_origin": record.get("candidate_origin"),
        "source_contour_ids": list(record.get("source_contour_ids") or []),
        "contour_bridge_guard_reason_codes": list(record.get("contour_bridge_guard_reason_codes") or []),
    }


def _markdown_gap_table(items: Any, *, heading: str) -> list[str]:
    rows = items if isinstance(items, list) else []
    lines = ["", heading, "| start | end | dur | class | evidence |", "| ---: | ---: | ---: | --- | --- |"]
    if not rows:
        lines.append("|  |  |  | none |  |")
        return lines
    for item in rows:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        lines.append(
            "| {start} | {end} | {dur} | {cls} | raw={raw}, selected={selected}, f0={f0}, low_f0={low_f0}, selector_stage={selector_stage} |".format(
                start=_fmt(item.get("start_sec")),
                end=_fmt(item.get("end_sec")),
                dur=_fmt(item.get("duration_sec")),
                cls=_escape_md(str(item.get("classification") or "")),
                raw=_fmt(evidence.get("raw_candidates_in_gap")),
                selected=_fmt(evidence.get("selected_notes_in_gap")),
                f0=_fmt((evidence.get("f0_voiced_overlap") or {}).get("duration_sec") if isinstance(evidence.get("f0_voiced_overlap"), dict) else None),
                low_f0=_fmt((evidence.get("low_confidence_or_unvoiced_overlap") or {}).get("duration_sec") if isinstance(evidence.get("low_confidence_or_unvoiced_overlap"), dict) else None),
                selector_stage=_escape_md(_fmt(evidence.get("selector_stage_reason_counts"))),
            )
        )
    return lines


def _markdown_lost_expected_table(items: Any, *, heading: str) -> list[str]:
    rows = items if isinstance(items, list) else []
    lines = ["", heading, "| start | dur | pitch | class | evidence |", "| ---: | ---: | --- | --- | --- |"]
    if not rows:
        lines.append("|  |  |  | none |  |")
        return lines
    for item in rows:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        lines.append(
            "| {start} | {dur} | {pitch} | {cls} | raw={raw}, selected={selected}, quantized={quantized}, score_ir={score_ir}, predicted={predicted}, f0={f0} |".format(
                start=_fmt(item.get("start_sec")),
                dur=_fmt(item.get("duration_sec")),
                pitch=_escape_md(str(item.get("pitch_name") or item.get("pitch_midi") or "")),
                cls=_escape_md(str(item.get("classification") or "")),
                raw=_fmt(evidence.get("raw_candidate_matches")),
                selected=_fmt(evidence.get("selected_matches")),
                quantized=_fmt(evidence.get("quantized_matches")),
                score_ir=_fmt(evidence.get("score_ir_matches")),
                predicted=_fmt(evidence.get("predicted_midi_matches")),
                f0=_fmt((evidence.get("f0_voiced_overlap") or {}).get("duration_sec") if isinstance(evidence.get("f0_voiced_overlap"), dict) else None),
            )
        )
    return lines


def _markdown_deleted_candidate_table(items: Any, *, heading: str) -> list[str]:
    rows = items if isinstance(items, list) else []
    lines = ["", heading, "| start | dur | pitch | conf | diagnostic_reason_codes | input_reason_codes |", "| ---: | ---: | --- | ---: | --- | --- |"]
    if not rows:
        lines.append("|  |  |  |  | none |  |")
        return lines
    for item in rows:
        lines.append(
            "| {start} | {dur} | {pitch} | {conf} | {diag} | {input_codes} |".format(
                start=_fmt(item.get("start_sec")),
                dur=_fmt(item.get("duration_sec")),
                pitch=_escape_md(str(item.get("pitch_name") or item.get("pitch_midi") or "")),
                conf=_fmt(item.get("confidence")),
                diag=_escape_md(", ".join(str(code) for code in item.get("diagnostic_reason_codes") or [])),
                input_codes=_escape_md(", ".join(str(code) for code in item.get("input_reason_codes") or [])),
            )
        )
    return lines


def _read_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _first_reason(item: dict[str, Any]) -> str:
    reasons = item.get("reason_codes") if isinstance(item.get("reason_codes"), list) else []
    return str(reasons[0]) if reasons else str(item.get("classification") or GAP_ATTR_UNCLASSIFIED)


def _start(record: dict[str, Any]) -> float:
    return float(record.get("start_sec") or record.get("start") or 0.0)


def _end(record: dict[str, Any]) -> float:
    return float(record.get("end_sec") or record.get("end") or _start(record))


def _duration(record: dict[str, Any]) -> float:
    return max(0.0, _end(record) - _start(record))


def _pitch(record: dict[str, Any]) -> float | None:
    return _as_float(record.get("pitch_midi"))


def _overlap_seconds(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def _infer_hop(frames: list[dict[str, Any]]) -> float:
    times = [float(frame["time_sec"]) for frame in frames]
    diffs = [b - a for a, b in zip(times, times[1:]) if b > a]
    return median(diffs) if diffs else 0.01


def _safe_divide(numerator: Any, denominator: Any) -> float | None:
    numerator_float = _as_float(numerator)
    denominator_float = _as_float(denominator)
    if numerator_float is None or denominator_float is None or denominator_float == 0:
        return None
    return numerator_float / denominator_float


def _max_abs(values: Any) -> float | None:
    parsed = [_as_float(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return max((abs(value) for value in parsed), default=None)


def _round(value: Any) -> float:
    value_float = _as_float(value)
    return 0.0 if value_float is None else round(float(value_float), 6)


def _round_optional(value: Any) -> float | None:
    value_float = _as_float(value)
    return None if value_float is None else round(float(value_float), 6)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
