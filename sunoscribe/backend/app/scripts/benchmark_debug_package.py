from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.modules.benchmark.debug_package import export_benchmark_debug_package
from app.modules.benchmark.midi_metrics import MidiMetricConfig


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = export_benchmark_debug_package(
        run_root=Path(args.run_root),
        manifest_path=Path(args.manifest),
        sample_id=args.sample_id,
        metric_config=MidiMetricConfig(onset_tolerance_sec=args.onset_tolerance_ms / 1000.0),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a benchmark per-sample MIR debug package.")
    parser.add_argument("--run-root", required=True, help="Benchmark run root containing summary.json and sample dirs.")
    parser.add_argument("--manifest", default="../samples/manifest.v1.json", help="Path to benchmark manifest JSON.")
    parser.add_argument("--sample-id", required=True, help="Sample id to export.")
    parser.add_argument("--onset-tolerance-ms", type=float, default=120.0, help="Onset tolerance for debug matching.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
