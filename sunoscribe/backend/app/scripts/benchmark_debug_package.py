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


def _parse_sample_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _sample_title(sample: BenchmarkSample) -> str:
    return sample.input_mp4.stem or sample.id


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
