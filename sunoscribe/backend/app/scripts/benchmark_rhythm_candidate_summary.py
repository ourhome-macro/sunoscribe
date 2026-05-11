from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.modules.benchmark.rhythm_candidate_summary import (
    build_rhythm_candidate_summary,
    write_rhythm_candidate_summary,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_rhythm_candidate_summary(Path(args.run_root))
    json_path, markdown_path = write_rhythm_candidate_summary(report, Path(args.output))
    print(
        json.dumps(
            {
                "rhythm_candidate_summary_json": str(json_path),
                "rhythm_candidate_summary_md": str(markdown_path),
                "aggregate_counts": report["aggregate_counts"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a run-level RhythmGrid candidate diagnostics summary.")
    parser.add_argument("--run-root", required=True, help="Benchmark run root containing summary.json and sample debug packages.")
    parser.add_argument("--output", required=True, help="Directory where rhythm_candidate_summary.json/md will be written.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
