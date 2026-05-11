from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


UNAVAILABLE = "unavailable"

GROUP_LOST_SUCCESS = "Lost Success"
GROUP_NEW_SUCCESS = "New Success"
GROUP_IMPROVED = "Improved"
GROUP_REGRESSED = "Regressed"
GROUP_UNCHANGED = "Unchanged"
GROUP_DIAGNOSTICS_CHANGED = "Diagnostics Changed"
GROUP_NEEDS_MANUAL_REVIEW = "Needs Manual Review"

GROUP_ORDER = [
    GROUP_LOST_SUCCESS,
    GROUP_NEW_SUCCESS,
    GROUP_IMPROVED,
    GROUP_REGRESSED,
    GROUP_DIAGNOSTICS_CHANGED,
    GROUP_UNCHANGED,
    GROUP_NEEDS_MANUAL_REVIEW,
]

RECALL_DELTA_THRESHOLD = 0.02
MATCHED_DELTA_THRESHOLD = 10


@dataclass(frozen=True)
class MetricSpec:
    name: str
    paths: tuple[tuple[str, ...], ...]
    source_names: tuple[str, ...] = ()


METRIC_SPECS = (
    MetricSpec("recall", (("metrics", "note_recall"), ("diagnostics", "note_recall"))),
    MetricSpec("f1", (("metrics", "note_f1"), ("diagnostics", "note_f1"))),
    MetricSpec(
        "matched",
        (
            ("metrics", "matched_notes"),
            ("metrics", "matched_count"),
            ("metrics", "matched_note_count"),
            ("alignment", "best_octave_shift_matched_notes"),
            ("alignment", "shift_corrected_matched"),
        ),
        (
            "metrics.matched_notes",
            "metrics.matched_count",
            "metrics.matched_note_count",
            "alignment.best_octave_shift_matched_notes",
            "alignment.shift_corrected_matched",
        ),
    ),
    MetricSpec("shift_recall", (("alignment", "shift_corrected_recall"), ("alignment", "smart_onset_alignment", "shift_corrected_recall"))),
    MetricSpec("dtw_recall", (("alignment", "dtw", "dtw_pitch_match_recall_proxy"),)),
    MetricSpec("coverage", (("audibility", "midi_coverage_ratio"), ("diagnostics", "coverage", "midi_coverage_ratio"))),
    MetricSpec("first_delay", (("audibility", "first_note_delay_sec"),)),
)

DIAGNOSTIC_METRIC_SPECS = (
    MetricSpec("predicted_note_count", (("notes", "predicted_note_count"), ("quantized_notes", "note_count"))),
    MetricSpec("predicted_short_note_ratio", (("notes", "predicted_short_note_ratio"),)),
    MetricSpec(
        "fragmentation",
        (
            ("quantized_notes", "fragmentation", "risk_score"),
            ("fragmentation", "risk_score"),
            ("quantized_notes", "fragmentation", "possible_fragment_pair_count"),
            ("fragmentation", "possible_fragment_pair_count"),
        ),
    ),
    MetricSpec(
        "overmerge",
        (
            ("quantized_notes", "overmerge", "risk_score"),
            ("overmerge", "risk_score"),
            ("quantized_notes", "overmerge", "possible_overmerge_note_count"),
            ("overmerge", "possible_overmerge_note_count"),
        ),
    ),
    MetricSpec("quantization_mean_error", (("quantized_notes", "mean_quantize_error_sec"), ("quantization", "mean_quantize_error_sec"))),
    MetricSpec("quantization_p95_error", (("quantized_notes", "p95_quantize_error_sec"), ("quantization", "p95_quantize_error_sec"))),
    MetricSpec("quantization_max_error", (("quantized_notes", "max_quantize_error_sec"), ("quantization", "max_quantize_error_sec"))),
)


def compare_benchmark_runs(baseline_run: Path, candidate_run: Path) -> dict[str, Any]:
    baseline = _load_run(Path(baseline_run))
    candidate = _load_run(Path(candidate_run))
    sample_ids = sorted(set(baseline["results_by_sample"]) | set(candidate["results_by_sample"]))

    per_sample = []
    groups: dict[str, list[str]] = {name: [] for name in GROUP_ORDER}
    for sample_id in sample_ids:
        comparison = _compare_sample(sample_id, baseline, candidate)
        per_sample.append(comparison)
        groups[comparison["group"]].append(sample_id)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_run": _safe_path_string(Path(baseline_run)),
        "candidate_run": _safe_path_string(Path(candidate_run)),
        "thresholds": {
            "recall_delta": RECALL_DELTA_THRESHOLD,
            "matched_delta": MATCHED_DELTA_THRESHOLD,
        },
        "aggregate_counts": {name: len(groups[name]) for name in GROUP_ORDER},
        "groups": groups,
        "per_sample": per_sample,
    }


def write_comparison_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "ab_report.json"
    markdown_path = output / "ab_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Benchmark A/B Report",
        "",
        f"- Baseline run: `{report.get('baseline_run', UNAVAILABLE)}`",
        f"- Candidate run: `{report.get('candidate_run', UNAVAILABLE)}`",
        f"- Generated at: `{report.get('generated_at', UNAVAILABLE)}`",
        "",
        "## Summary",
        "",
        "| Group | Count |",
        "| --- | ---: |",
    ]
    counts = report.get("aggregate_counts") if isinstance(report.get("aggregate_counts"), dict) else {}
    for group in GROUP_ORDER:
        lines.append(f"| {group} | {counts.get(group, 0)} |")

    comparisons = report.get("per_sample") if isinstance(report.get("per_sample"), list) else []
    comparisons_by_group: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUP_ORDER}
    for comparison in comparisons:
        if isinstance(comparison, dict):
            comparisons_by_group.setdefault(str(comparison.get("group", GROUP_NEEDS_MANUAL_REVIEW)), []).append(comparison)

    for group in GROUP_ORDER:
        lines.extend(["", f"## {group}", ""])
        items = comparisons_by_group.get(group, [])
        if not items:
            lines.append("No samples.")
            continue
        lines.extend(
            [
                "| Sample | Status | Δ Recall | Δ Matched | Δ Coverage | Δ First Delay | Notes |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for item in items:
            deltas = item.get("deltas") if isinstance(item.get("deltas"), dict) else {}
            reasons = item.get("manual_review_reasons") if isinstance(item.get("manual_review_reasons"), list) else []
            notes = "; ".join(str(reason) for reason in reasons[:3]) or _diagnostic_change_note(item)
            lines.append(
                "| {sample} | {old} → {new} | {recall} | {matched} | {coverage} | {delay} | {notes} |".format(
                    sample=_escape_md(str(item.get("sample_id", UNAVAILABLE))),
                    old=_escape_md(str(item.get("old_status", UNAVAILABLE))),
                    new=_escape_md(str(item.get("new_status", UNAVAILABLE))),
                    recall=_format_delta(deltas.get("recall")),
                    matched=_format_delta(deltas.get("matched")),
                    coverage=_format_delta(deltas.get("coverage")),
                    delay=_format_delta(deltas.get("first_delay")),
                    notes=_escape_md(notes),
                )
            )
    lines.append("")
    return "\n".join(lines)


def _load_run(run_root: Path) -> dict[str, Any]:
    summary_path = run_root / "summary.json"
    summary = _read_json(summary_path)
    if not isinstance(summary, dict):
        summary = {}
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    results_by_sample: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        sample_id = result.get("sample_id")
        if isinstance(sample_id, str) and sample_id:
            results_by_sample[sample_id] = result
    return {
        "run_root": run_root,
        "summary": summary,
        "results_by_sample": results_by_sample,
        "titles": _build_title_index(summary),
    }


def _compare_sample(sample_id: str, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    old_result = baseline["results_by_sample"].get(sample_id)
    new_result = candidate["results_by_sample"].get(sample_id)
    old_diag = _read_sample_diagnostics(baseline["run_root"], sample_id)
    new_diag = _read_sample_diagnostics(candidate["run_root"], sample_id)

    metrics: dict[str, Any] = {}
    deltas: dict[str, Any] = {}
    for spec in (*METRIC_SPECS, *DIAGNOSTIC_METRIC_SPECS):
        old_value = _metric_value(spec, old_result, old_diag)
        new_value = _metric_value(spec, new_result, new_diag)
        delta = _delta(old_value["value"], new_value["value"])
        metrics[spec.name] = {"old": old_value, "new": new_value, "delta": delta}
        deltas[spec.name] = delta

    old_stage = _failure_stage(old_diag)
    new_stage = _failure_stage(new_diag)
    old_pitch_flags = _collect_flags(old_diag, "pitch")
    new_pitch_flags = _collect_flags(new_diag, "pitch")
    old_rhythm_flags = _collect_flags(old_diag, "rhythm")
    new_rhythm_flags = _collect_flags(new_diag, "rhythm")

    old_status = _status(old_result)
    new_status = _status(new_result)
    manual_review_reasons = _manual_review_reasons(
        old_result=old_result,
        new_result=new_result,
        old_status=old_status,
        new_status=new_status,
        metrics=metrics,
    )
    diagnostics_changed = old_stage != new_stage or old_pitch_flags != new_pitch_flags or old_rhythm_flags != new_rhythm_flags
    group = _classify_group(
        old_status=old_status,
        new_status=new_status,
        deltas=deltas,
        diagnostics_changed=diagnostics_changed,
        manual_review_reasons=manual_review_reasons,
    )

    return {
        "sample_id": sample_id,
        "title": _title(sample_id, baseline, candidate, old_result, new_result),
        "group": group,
        "old_status": old_status,
        "new_status": new_status,
        "old_failed_checks": _failed_checks(old_result),
        "new_failed_checks": _failed_checks(new_result),
        "metrics": metrics,
        "deltas": deltas,
        "preliminary_failure_stage_v2": {"old": old_stage, "new": new_stage},
        "triggered_flags": {
            "pitch": {"old": old_pitch_flags, "new": new_pitch_flags},
            "rhythm": {"old": old_rhythm_flags, "new": new_rhythm_flags},
        },
        "diagnostics_changed": diagnostics_changed,
        "manual_review_reasons": manual_review_reasons,
        "debug_diagnostics": {
            "old": _diagnostics_status(old_diag),
            "new": _diagnostics_status(new_diag),
        },
    }


def _classify_group(
    *,
    old_status: str,
    new_status: str,
    deltas: dict[str, Any],
    diagnostics_changed: bool,
    manual_review_reasons: list[str],
) -> str:
    old_success = old_status == "success"
    new_success = new_status == "success"
    if old_success and not new_success:
        return GROUP_LOST_SUCCESS
    if not old_success and new_success:
        return GROUP_NEW_SUCCESS
    if _has_one_sided_sample(manual_review_reasons) or _has_core_metric_unavailable(manual_review_reasons):
        return GROUP_NEEDS_MANUAL_REVIEW
    recall_delta = _number_or_none(deltas.get("recall"))
    matched_delta = _number_or_none(deltas.get("matched"))
    if (recall_delta is not None and recall_delta >= RECALL_DELTA_THRESHOLD) or (
        matched_delta is not None and matched_delta >= MATCHED_DELTA_THRESHOLD
    ):
        return GROUP_IMPROVED
    if (recall_delta is not None and recall_delta <= -RECALL_DELTA_THRESHOLD) or (
        matched_delta is not None and matched_delta <= -MATCHED_DELTA_THRESHOLD
    ):
        return GROUP_REGRESSED
    if diagnostics_changed:
        return GROUP_DIAGNOSTICS_CHANGED
    if manual_review_reasons:
        return GROUP_NEEDS_MANUAL_REVIEW
    return GROUP_UNCHANGED


def _manual_review_reasons(
    *,
    old_result: dict[str, Any] | None,
    new_result: dict[str, Any] | None,
    old_status: str,
    new_status: str,
    metrics: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if old_result is None:
        reasons.append("sample missing from baseline run")
    if new_result is None:
        reasons.append("sample missing from candidate run")
    for name in ("recall", "f1", "matched"):
        metric = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
        if _is_unavailable(metric.get("old")) or _is_unavailable(metric.get("new")):
            reasons.append(f"core metric {name} unavailable")
    if old_status == UNAVAILABLE or new_status == UNAVAILABLE:
        reasons.append("status unavailable")
    return reasons


def _metric_value(spec: MetricSpec, result: dict[str, Any] | None, diagnostics: dict[str, Any]) -> dict[str, Any]:
    for index, path in enumerate(spec.paths):
        value = _get_path(result, path)
        if value is None:
            value = _get_path(diagnostics, path)
        number = _number_or_none(value)
        if number is not None:
            source = spec.source_names[index] if index < len(spec.source_names) else ".".join(path)
            return {"value": number, "source": source, "available": True}
    return {"value": UNAVAILABLE, "source": UNAVAILABLE, "available": False}


def _delta(old_value: Any, new_value: Any) -> float | str:
    old_number = _number_or_none(old_value)
    new_number = _number_or_none(new_value)
    if old_number is None or new_number is None:
        return UNAVAILABLE
    return round(new_number - old_number, 6)


def _read_sample_diagnostics(run_root: Path, sample_id: str) -> dict[str, Any]:
    diagnostics_path = run_root / sample_id / "debug_package" / "derived_diagnostics.json"
    payload = _read_json(diagnostics_path)
    if not isinstance(payload, dict):
        return {"available": False, "reason": "derived_diagnostics.json missing"}
    payload = dict(payload)
    payload.setdefault("available", True)
    return payload


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _build_title_index(summary: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    manifest = summary.get("manifest") if isinstance(summary.get("manifest"), dict) else {}
    for sample in manifest.get("samples", []) if isinstance(manifest.get("samples"), list) else []:
        if not isinstance(sample, dict):
            continue
        sample_id = sample.get("id")
        title = sample.get("title") or sample.get("name") or sample.get("display_title")
        if isinstance(sample_id, str) and isinstance(title, str) and title:
            titles[sample_id] = title
    dataset = summary.get("dataset") if isinstance(summary.get("dataset"), dict) else {}
    for sample in dataset.get("sample_status", []) if isinstance(dataset.get("sample_status"), list) else []:
        if not isinstance(sample, dict):
            continue
        sample_id = sample.get("id")
        title = sample.get("title") or sample.get("name") or sample.get("display_title")
        if isinstance(sample_id, str) and isinstance(title, str) and title:
            titles.setdefault(sample_id, title)
    return titles


def _title(
    sample_id: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    old_result: dict[str, Any] | None,
    new_result: dict[str, Any] | None,
) -> str:
    for result in (new_result, old_result):
        if isinstance(result, dict):
            title = result.get("title") or result.get("sample_title") or result.get("name")
            if isinstance(title, str) and title:
                return title
    for run in (candidate, baseline):
        title = run.get("titles", {}).get(sample_id)
        if isinstance(title, str) and title:
            return title
    return sample_id


def _status(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return UNAVAILABLE
    status = result.get("status")
    return status if isinstance(status, str) and status else UNAVAILABLE


def _failed_checks(result: dict[str, Any] | None) -> list[str] | str:
    if not isinstance(result, dict):
        return UNAVAILABLE
    quality_gate = result.get("quality_gate") if isinstance(result.get("quality_gate"), dict) else {}
    failed = quality_gate.get("failed_checks")
    if isinstance(failed, list):
        return [str(item) for item in failed]
    failed = result.get("failed_checks")
    if isinstance(failed, list):
        return [str(item) for item in failed]
    return []


def _failure_stage(diagnostics: dict[str, Any]) -> str:
    value = diagnostics.get("preliminary_failure_stage_v2")
    if value is None:
        value = _get_path(diagnostics, ("failure_attribution", "preliminary_failure_stage_v2"))
    return value if isinstance(value, str) and value else UNAVAILABLE


def _collect_flags(diagnostics: dict[str, Any], domain: str) -> list[str] | str:
    flags: set[str] = set()
    for key in (f"{domain}_flags", "triggered_flags", "flags"):
        value = diagnostics.get(key)
        if key == "triggered_flags" and isinstance(value, dict):
            value = value.get(domain)
        _add_flags(flags, value)
    domain_payload = diagnostics.get(domain)
    if isinstance(domain_payload, dict):
        for key in ("flags", "triggered_flags", f"{domain}_flags"):
            _add_flags(flags, domain_payload.get(key))
    if not flags:
        return UNAVAILABLE
    return sorted(flags)


def _add_flags(flags: set[str], value: Any) -> None:
    if isinstance(value, str) and value:
        flags.add(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item:
                flags.add(item)
    elif isinstance(value, dict):
        for key, enabled in value.items():
            if enabled and isinstance(key, str):
                flags.add(key)


def _diagnostics_status(diagnostics: dict[str, Any]) -> dict[str, Any]:
    if diagnostics.get("available") is True:
        return {"available": True}
    return {"available": False, "reason": diagnostics.get("reason", "derived diagnostics unavailable")}


def _get_path(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _is_unavailable(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("available") is False or value.get("value") == UNAVAILABLE
    return value == UNAVAILABLE


def _has_one_sided_sample(reasons: list[str]) -> bool:
    return any("sample missing" in reason for reason in reasons)


def _has_core_metric_unavailable(reasons: list[str]) -> bool:
    return any(reason.startswith("core metric") for reason in reasons)


def _safe_path_string(path: Path) -> str:
    return str(path)


def _format_delta(value: Any) -> str:
    number = _number_or_none(value)
    if number is None:
        return UNAVAILABLE
    return f"{number:+.4f}"


def _diagnostic_change_note(item: dict[str, Any]) -> str:
    if item.get("diagnostics_changed"):
        stage = item.get("preliminary_failure_stage_v2") if isinstance(item.get("preliminary_failure_stage_v2"), dict) else {}
        return f"diagnostics changed: {stage.get('old', UNAVAILABLE)} → {stage.get('new', UNAVAILABLE)}"
    return ""


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
