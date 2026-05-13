from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any

from app.modules.benchmark.dataset import BenchmarkSample, load_manifest
from app.modules.benchmark.debug_package import export_benchmark_debug_package
from app.modules.benchmark.midi_metrics import MidiMetricConfig


@dataclass(slots=True)
class BatchSampleResult:
    sample_id: str
    title: str
    status: str
    debug_package_path: str | None
    generated_files: list[str]
    missing_files: list[str]
    error: str | None = None


@dataclass(slots=True)
class DebugPackageBatchSummary:
    total_requested: int
    generated_count: int
    skipped_count: int
    failed_count: int
    per_sample: list[BatchSampleResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requested": self.total_requested,
            "generated_count": self.generated_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "per_sample": [asdict(item) for item in self.per_sample],
        }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    metric_config = MidiMetricConfig(onset_tolerance_sec=args.onset_tolerance_ms / 1000.0)
    if args.all_enabled or args.sample_ids:
        summary = _export_batch(
            run_root=Path(args.run_root),
            manifest_path=Path(args.manifest),
            sample_ids=_parse_sample_ids(args.sample_ids),
            all_enabled=bool(args.all_enabled),
            metric_config=metric_config,
        )
        _write_batch_summary(Path(args.run_root), summary)
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if summary.failed_count > 0 else 0

    if not args.sample_id:
        raise SystemExit("--sample-id is required unless --sample-ids or --all-enabled is used")
    result = export_benchmark_debug_package(
        run_root=Path(args.run_root),
        manifest_path=Path(args.manifest),
        sample_id=args.sample_id,
        metric_config=metric_config,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a benchmark per-sample MIR debug package.")
    parser.add_argument("--run-root", required=True, help="Benchmark run root containing summary.json and sample dirs.")
    parser.add_argument("--manifest", default="../samples/manifest.v1.json", help="Path to benchmark manifest JSON.")
    parser.add_argument("--sample-id", help="Single sample id to export.")
    parser.add_argument("--sample-ids", help="Comma-separated sample ids to export in batch mode.")
    parser.add_argument("--all-enabled", action="store_true", help="Export debug packages for every enabled manifest sample.")
    parser.add_argument("--onset-tolerance-ms", type=float, default=120.0, help="Onset tolerance for debug matching.")
    return parser.parse_args(argv)


def _export_batch(
    *,
    run_root: Path,
    manifest_path: Path,
    sample_ids: list[str],
    all_enabled: bool,
    metric_config: MidiMetricConfig,
) -> DebugPackageBatchSummary:
    manifest = load_manifest(manifest_path)
    requested_samples = _requested_samples(manifest.samples, sample_ids=sample_ids, all_enabled=all_enabled)
    rows: list[BatchSampleResult] = []
    for sample in requested_samples:
        try:
            result = export_benchmark_debug_package(
                run_root=run_root,
                manifest_path=manifest_path,
                sample_id=sample.id,
                metric_config=metric_config,
            )
            found = set(result.found_files)
            generated_files = sorted(
                file_name
                for file_name in [
                    "derived_diagnostics.json",
                    "rhythm_debug.json",
                    "rhythm_debug.md",
                    "rhythm_grid_candidates.json",
                    "rhythm_grid_candidates.md",
                    "note_funnel_debug.json",
                    "note_funnel_debug.md",
                    "gap_attribution.json",
                    "gap_attribution.md",
                    "debug_summary.md",
                    "timeline_debug.png",
                ]
                if file_name in found
            )
            status = "generated" if result.debug_dir else "skipped"
            rows.append(
                BatchSampleResult(
                    sample_id=sample.id,
                    title=_sample_title(sample),
                    status=status,
                    debug_package_path=result.debug_dir,
                    generated_files=generated_files,
                    missing_files=result.missing_files,
                    error=None,
                )
            )
        except Exception as exc:
            rows.append(
                BatchSampleResult(
                    sample_id=sample.id,
                    title=_sample_title(sample),
                    status="failed",
                    debug_package_path=None,
                    generated_files=[],
                    missing_files=[],
                    error=str(exc),
                )
            )
    generated_count = sum(1 for row in rows if row.status == "generated")
    skipped_count = sum(1 for row in rows if row.status == "skipped")
    failed_count = sum(1 for row in rows if row.status == "failed")
    return DebugPackageBatchSummary(
        total_requested=len(rows),
        generated_count=generated_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        per_sample=rows,
    )


def _requested_samples(samples: list[BenchmarkSample], *, sample_ids: list[str], all_enabled: bool) -> list[BenchmarkSample]:
    if all_enabled:
        return [sample for sample in samples if sample.enabled]
    if not sample_ids:
        return []
    by_id = {sample.id: sample for sample in samples}
    requested: list[BenchmarkSample] = []
    for sample_id in sample_ids:
        sample = by_id.get(sample_id)
        if sample is not None:
            requested.append(sample)
    return requested


def _write_batch_summary(run_root: Path, summary: DebugPackageBatchSummary) -> tuple[Path, Path]:
    json_path = run_root / "debug_package_batch_summary.json"
    markdown_path = run_root / "debug_package_batch_summary.md"
    payload = summary.to_dict()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_batch_summary_markdown(payload), encoding="utf-8")
    gap_payload = _gap_attribution_batch_payload(run_root, payload)
    (run_root / "gap_attribution_summary.json").write_text(
        json.dumps(gap_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_root / "gap_attribution_summary.md").write_text(
        _gap_attribution_batch_markdown(gap_payload),
        encoding="utf-8",
    )
    return json_path, markdown_path


def _batch_summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Debug Package Batch Summary",
        "",
        f"- total_requested: {payload.get('total_requested', 0)}",
        f"- generated_count: {payload.get('generated_count', 0)}",
        f"- skipped_count: {payload.get('skipped_count', 0)}",
        f"- failed_count: {payload.get('failed_count', 0)}",
        "",
        "| sample_id | status | generated_files | missing_files | error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("per_sample", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            "| {sample_id} | {status} | {generated} | {missing} | {error} |".format(
                sample_id=_escape_md(str(row.get("sample_id", ""))),
                status=_escape_md(str(row.get("status", ""))),
                generated=_escape_md(", ".join(str(item) for item in row.get("generated_files", [])) or "none"),
                missing=_escape_md(", ".join(str(item) for item in row.get("missing_files", [])) or "none"),
                error=_escape_md(str(row.get("error") or "none")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _gap_attribution_batch_payload(run_root: Path, batch_payload: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in batch_payload.get("per_sample", []):
        if not isinstance(row, dict) or row.get("status") != "generated":
            continue
        sample_id = str(row.get("sample_id") or "")
        if not sample_id:
            continue
        path = run_root / sample_id / "debug_package" / "gap_attribution.json"
        if not path.exists():
            rows.append({"sample_id": sample_id, "available": False, "unavailable_reason": "gap_attribution.json missing"})
            continue
        try:
            gap = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append({"sample_id": sample_id, "available": False, "unavailable_reason": str(exc)})
            continue
        rows.append(_gap_attribution_sample_summary(sample_id=sample_id, title=str(row.get("title") or sample_id), gap=gap))
    return {
        "version": "gap_attribution_batch_v1",
        "diagnostic_only": True,
        "reference_midi_used_for_benchmark_attribution_only": True,
        "sample_count": len(rows),
        "samples": rows,
    }


def _gap_attribution_sample_summary(*, sample_id: str, title: str, gap: dict[str, Any]) -> dict[str, Any]:
    metrics = gap.get("benchmark_metrics") if isinstance(gap.get("benchmark_metrics"), dict) else {}
    reference = gap.get("reference_alignment") if isinstance(gap.get("reference_alignment"), dict) else {}
    retention = gap.get("retention") if isinstance(gap.get("retention"), dict) else {}
    reason_counts = gap.get("reason_counts") if isinstance(gap.get("reason_counts"), dict) else {}
    return {
        "sample_id": sample_id,
        "title": title,
        "available": True,
        "quality_status": metrics.get("quality_status"),
        "note_recall": metrics.get("note_recall"),
        "note_f1": metrics.get("note_f1"),
        "matched_note_count": metrics.get("matched_note_count"),
        "expected_note_count": reference.get("expected_note_count"),
        "predicted_note_count": reference.get("predicted_note_count"),
        "gap50_ratio": metrics.get("gap50_ratio"),
        "midi_coverage_ratio": metrics.get("midi_coverage_ratio"),
        "raw_to_selected_count_ratio": retention.get("raw_to_selected_count_ratio"),
        "selected_to_quantized_count_ratio": retention.get("selected_to_quantized_count_ratio"),
        "score_ir_to_predicted_count_ratio": retention.get("score_ir_to_predicted_count_ratio"),
        "reason_counts": reason_counts,
        "recommended_fix_focus": gap.get("recommended_fix_focus") if isinstance(gap.get("recommended_fix_focus"), list) else [],
        "top_gaps": _compact_top_items(gap.get("top_gaps")),
        "top_lost_expected_notes": _compact_top_items(gap.get("top_lost_expected_notes")),
        "top_deleted_candidates": _compact_top_items(gap.get("top_deleted_candidates")),
    }


def _compact_top_items(items: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "start_sec": item.get("start_sec"),
                "duration_sec": item.get("duration_sec"),
                "pitch_name": item.get("pitch_name"),
                "classification": item.get("classification"),
                "reason_codes": item.get("reason_codes") or item.get("diagnostic_reason_codes"),
            }
        )
    return compact


def _gap_attribution_batch_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Gap Attribution Summary",
        "",
        "- diagnostic_only: true",
        "- reference_midi_used_for_benchmark_attribution_only: true",
        f"- sample_count: {payload.get('sample_count', 0)}",
        "",
        "## Samples",
        "| sample_id | status | recall | f1 | matched | expected | predicted | gap50 | raw_to_selected | selected_to_quantized | score_ir_to_midi |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("samples", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            "| {sample_id} | {status} | {recall} | {f1} | {matched} | {expected} | {predicted} | {gap50} | {raw_selected} | {selected_quantized} | {score_midi} |".format(
                sample_id=_escape_md(str(row.get("sample_id") or "")),
                status=_escape_md(str(row.get("quality_status") or row.get("unavailable_reason") or "missing")),
                recall=_fmt(row.get("note_recall")),
                f1=_fmt(row.get("note_f1")),
                matched=_fmt(row.get("matched_note_count")),
                expected=_fmt(row.get("expected_note_count")),
                predicted=_fmt(row.get("predicted_note_count")),
                gap50=_fmt(row.get("gap50_ratio")),
                raw_selected=_fmt(row.get("raw_to_selected_count_ratio")),
                selected_quantized=_fmt(row.get("selected_to_quantized_count_ratio")),
                score_midi=_fmt(row.get("score_ir_to_predicted_count_ratio")),
            )
        )
    for row in payload.get("samples", []):
        if not isinstance(row, dict) or not row.get("available"):
            continue
        lines.extend(
            [
                "",
                f"## {row.get('sample_id')}",
                f"- reason_counts: {_fmt(row.get('reason_counts'))}",
                f"- recommended_fix_focus: {_fmt(row.get('recommended_fix_focus'))}",
                "### Top Gaps",
                *(_compact_items_lines(row.get("top_gaps"))),
                "### Top Lost Expected Notes",
                *(_compact_items_lines(row.get("top_lost_expected_notes"))),
                "### Top Deleted Candidates",
                *(_compact_items_lines(row.get("top_deleted_candidates"))),
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _compact_items_lines(items: Any) -> list[str]:
    if not isinstance(items, list) or not items:
        return ["- none"]
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(
            "- start={start} dur={dur} pitch={pitch} class={classification} reasons={reasons}".format(
                start=_fmt(item.get("start_sec")),
                dur=_fmt(item.get("duration_sec")),
                pitch=_fmt(item.get("pitch_name")),
                classification=_fmt(item.get("classification")),
                reasons=_fmt(item.get("reason_codes")),
            )
        )
    return lines or ["- none"]


def _parse_sample_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _sample_title(sample: BenchmarkSample) -> str:
    return sample.input_mp4.stem or sample.id


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
