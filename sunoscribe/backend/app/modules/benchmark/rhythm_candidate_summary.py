from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


UNAVAILABLE = "unavailable"
LARGE_SCORE_DELTA = 0.12
SMALL_SCORE_DELTA = 0.05

GROUP_CURRENT_STABLE = "Current Grid Looks Stable"
GROUP_HALF_DOUBLE = "Half/Double Tempo Suspicion"
GROUP_DOWNBEAT_PHASE = "Downbeat Phase Suspicion"
GROUP_MISSING = "Candidate Diagnostics Missing"
GROUP_MANUAL = "Manual Review"

GROUP_ORDER = [
    GROUP_CURRENT_STABLE,
    GROUP_HALF_DOUBLE,
    GROUP_DOWNBEAT_PHASE,
    GROUP_MISSING,
    GROUP_MANUAL,
]


def build_rhythm_candidate_summary(run_root: Path) -> dict[str, Any]:
    run_root = Path(run_root)
    summary = _read_json(run_root / "summary.json")
    if not isinstance(summary, dict):
        summary = {}
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    titles = _title_index(summary)
    samples: list[dict[str, Any]] = []
    groups: dict[str, list[str]] = {group: [] for group in GROUP_ORDER}
    for result in results:
        if not isinstance(result, dict):
            continue
        sample_id = result.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            continue
        sample = _summarize_sample(run_root=run_root, result=result, title=titles.get(sample_id, sample_id))
        samples.append(sample)
        groups[sample["group"]].append(sample_id)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(run_root),
        "thresholds": {
            "large_score_delta": LARGE_SCORE_DELTA,
            "small_score_delta": SMALL_SCORE_DELTA,
        },
        "aggregate_counts": {group: len(groups[group]) for group in GROUP_ORDER},
        "groups": groups,
        "samples": samples,
    }


def write_rhythm_candidate_summary(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "rhythm_candidate_summary.json"
    markdown_path = output_dir / "rhythm_candidate_summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_rhythm_candidate_summary_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_rhythm_candidate_summary_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Rhythm Candidate Summary",
        "",
        f"- Run root: `{report.get('run_root', UNAVAILABLE)}`",
        f"- Generated at: `{report.get('generated_at', UNAVAILABLE)}`",
        "- diagnostic_only: true",
        "- no ScoreRevision, quantizer, quality gate, or benchmark status changes",
        "",
        "## Summary",
        "",
        "| Group | Count |",
        "| --- | ---: |",
    ]
    counts = report.get("aggregate_counts") if isinstance(report.get("aggregate_counts"), dict) else {}
    for group in GROUP_ORDER:
        lines.append(f"| {group} | {counts.get(group, 0)} |")
    samples = report.get("samples") if isinstance(report.get("samples"), list) else []
    by_group: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUP_ORDER}
    for sample in samples:
        if isinstance(sample, dict):
            by_group.setdefault(str(sample.get("group", GROUP_MANUAL)), []).append(sample)
    for group in GROUP_ORDER:
        lines.extend(["", f"## {group}", ""])
        rows = by_group.get(group, [])
        if not rows:
            lines.append("No samples.")
            continue
        lines.extend(
            [
                "| Sample | Status | Rank | Best | Δ Score | Current Off-grid | Best Off-grid | Action | Warning |",
                "| --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for sample in rows:
            lines.append(
                "| {sample_id} | {status} | {rank} | {best} | {delta} | {current_offgrid} | {best_offgrid} | {action} | {warning} |".format(
                    sample_id=_escape_md(str(sample.get("sample_id", UNAVAILABLE))),
                    status=_escape_md(str(sample.get("status", UNAVAILABLE))),
                    rank=_fmt(sample.get("current_candidate_rank")),
                    best=_escape_md(str(sample.get("best_diagnostic_candidate_id", UNAVAILABLE))),
                    delta=_fmt(sample.get("current_vs_best_score_delta")),
                    current_offgrid=_fmt(sample.get("current_off_grid_onset_ratio")),
                    best_offgrid=_fmt(sample.get("best_off_grid_onset_ratio")),
                    action=_escape_md(str(sample.get("recommended_next_action", UNAVAILABLE))),
                    warning=_escape_md(str(sample.get("rhythm_candidate_warning") or "none")),
                )
            )
    lines.append("")
    return "\n".join(lines)


def _summarize_sample(*, run_root: Path, result: dict[str, Any], title: str) -> dict[str, Any]:
    sample_id = str(result.get("sample_id"))
    diagnostics = _read_json(run_root / sample_id / "debug_package" / "derived_diagnostics.json")
    candidates_payload = _read_json(run_root / sample_id / "debug_package" / "rhythm_grid_candidates.json")
    rhythm = diagnostics.get("rhythm") if isinstance(diagnostics, dict) and isinstance(diagnostics.get("rhythm"), dict) else {}
    candidates = candidates_payload.get("candidates") if isinstance(candidates_payload, dict) and isinstance(candidates_payload.get("candidates"), list) else []
    by_id = {str(candidate.get("candidate_id")): candidate for candidate in candidates if isinstance(candidate, dict)}
    current = by_id.get("current_grid", {})
    best_id = _first_present(candidates_payload, rhythm, "best_diagnostic_candidate_id")
    best = by_id.get(str(best_id), {}) if best_id is not None else {}
    current_score = _number_or_unavailable(current.get("candidate_score"))
    best_score = _number_or_unavailable(best.get("candidate_score"))
    score_delta = _number_or_unavailable(_first_present(candidates_payload, rhythm, "current_vs_best_score_delta"))
    missing_candidates = not isinstance(candidates_payload, dict) or not candidates_payload.get("available") or not candidates
    recommended_next_action = _recommended_next_action(
        missing_candidates=missing_candidates,
        best_id=best_id,
        current_rank=_first_present(candidates_payload, rhythm, "current_candidate_rank"),
        score_delta=score_delta,
    )
    group = _group_for_action(recommended_next_action)
    return {
        "sample_id": sample_id,
        "title": title,
        "status": _status(result),
        "failed_checks": _failed_checks(result),
        "current_candidate_rank": _value_or_unavailable(_first_present(candidates_payload, rhythm, "current_candidate_rank")),
        "best_diagnostic_candidate_id": _value_or_unavailable(best_id),
        "current_score": current_score,
        "best_score": best_score,
        "current_vs_best_score_delta": score_delta,
        "current_off_grid_onset_ratio": _number_or_unavailable(current.get("off_grid_onset_ratio")),
        "best_off_grid_onset_ratio": _number_or_unavailable(best.get("off_grid_onset_ratio")),
        "current_downbeat_confidence": _number_or_unavailable(current.get("downbeat_confidence")),
        "best_downbeat_confidence": _number_or_unavailable(best.get("downbeat_confidence")),
        "current_bar_phase_confidence": _number_or_unavailable(current.get("bar_phase_confidence")),
        "best_bar_phase_confidence": _number_or_unavailable(best.get("bar_phase_confidence")),
        "rhythm_candidate_warning": _value_or_none(_first_present(candidates_payload, rhythm, "rhythm_candidate_warning")),
        "recommended_next_action": recommended_next_action,
        "group": group,
    }


def _recommended_next_action(*, missing_candidates: bool, best_id: Any, current_rank: Any, score_delta: Any) -> str:
    if missing_candidates:
        return "regenerate_debug_package"
    delta = _as_float(score_delta)
    if _as_int(current_rank) == 1 or (delta is not None and delta <= SMALL_SCORE_DELTA):
        return "keep_current_grid"
    best = str(best_id or "")
    if delta is not None and delta >= LARGE_SCORE_DELTA and best in {"half_tempo_grid", "double_tempo_grid"}:
        return "inspect_half_double_tempo"
    if delta is not None and delta >= LARGE_SCORE_DELTA and best.startswith("downbeat_phase_shift_"):
        return "inspect_downbeat_phase"
    return "manual_review"


def _group_for_action(action: str) -> str:
    if action == "keep_current_grid":
        return GROUP_CURRENT_STABLE
    if action == "inspect_half_double_tempo":
        return GROUP_HALF_DOUBLE
    if action == "inspect_downbeat_phase":
        return GROUP_DOWNBEAT_PHASE
    if action == "regenerate_debug_package":
        return GROUP_MISSING
    return GROUP_MANUAL


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _title_index(summary: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    manifest = summary.get("manifest") if isinstance(summary.get("manifest"), dict) else {}
    for sample in manifest.get("samples", []) if isinstance(manifest.get("samples"), list) else []:
        if not isinstance(sample, dict):
            continue
        sample_id = sample.get("id")
        title = sample.get("title") or sample.get("name") or sample.get("display_title")
        if isinstance(sample_id, str) and isinstance(title, str) and title:
            titles[sample_id] = title
    return titles


def _status(result: dict[str, Any]) -> str:
    status = result.get("status")
    return status if isinstance(status, str) and status else UNAVAILABLE


def _failed_checks(result: dict[str, Any]) -> list[str]:
    quality_gate = result.get("quality_gate") if isinstance(result.get("quality_gate"), dict) else {}
    failed = quality_gate.get("failed_checks")
    if isinstance(failed, list):
        return [str(item) for item in failed]
    failed = result.get("failed_checks")
    if isinstance(failed, list):
        return [str(item) for item in failed]
    return []


def _first_present(primary: Any, fallback: Any, key: str) -> Any:
    if isinstance(primary, dict) and key in primary:
        return primary.get(key)
    if isinstance(fallback, dict):
        return fallback.get(key)
    return None


def _number_or_unavailable(value: Any) -> float | str:
    number = _as_float(value)
    return round(number, 6) if number is not None else UNAVAILABLE


def _value_or_unavailable(value: Any) -> Any:
    return value if value is not None else UNAVAILABLE


def _value_or_none(value: Any) -> Any:
    return value if value not in (None, "") else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _fmt(value: Any) -> str:
    if value == UNAVAILABLE or value is None:
        return UNAVAILABLE
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
