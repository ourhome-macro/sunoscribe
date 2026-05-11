from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.modules.benchmark.run_comparison import compare_benchmark_runs, write_comparison_report


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = compare_benchmark_runs(
        baseline_run=Path(args.baseline_run),
        candidate_run=Path(args.candidate_run),
    )
    json_path, markdown_path = write_comparison_report(report, Path(args.output))
    print(
        json.dumps(
            {
                "ab_report_json": str(json_path),
                "ab_report_md": str(markdown_path),
                "aggregate_counts": report["aggregate_counts"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two SunoScribe benchmark run outputs.")
    parser.add_argument("--baseline-run", required=True, help="Baseline benchmark run root containing summary.json.")
    parser.add_argument("--candidate-run", required=True, help="Candidate benchmark run root containing summary.json.")
    parser.add_argument("--output", required=True, help="Directory where ab_report.json and ab_report.md will be written.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
