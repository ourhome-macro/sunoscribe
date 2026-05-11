from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.run_comparison import (
    GROUP_DIAGNOSTICS_CHANGED,
    GROUP_IMPROVED,
    GROUP_LOST_SUCCESS,
    GROUP_NEEDS_MANUAL_REVIEW,
    GROUP_NEW_SUCCESS,
    GROUP_REGRESSED,
    GROUP_UNCHANGED,
    UNAVAILABLE,
    compare_benchmark_runs,
    write_comparison_report,
)
from app.scripts.benchmark_compare_runs import main as compare_main


class BenchmarkCompareRunsTests(unittest.TestCase):
    def test_compare_runs_computes_deltas_and_groups(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline"
            candidate = root / "candidate"
            _write_run(
                baseline,
                [
                    _result("lost", "success", recall=0.50, f1=0.60, matched=50),
                    _result("new", "quality_failed", recall=0.10, f1=0.20, matched=5),
                    _result("improved", "quality_failed", recall=0.40, f1=0.40, matched=20),
                    _result("regressed", "quality_failed", recall=0.50, f1=0.50, matched=30),
                    _result("diag", "quality_failed", recall=0.30, f1=0.30, matched=10),
                    _result("same", "quality_failed", recall=0.30, f1=0.30, matched=10),
                    _result("missing_candidate", "quality_failed", recall=0.30, f1=0.30, matched=10),
                ],
            )
            _write_run(
                candidate,
                [
                    _result("lost", "quality_failed", recall=0.51, f1=0.61, matched=51),
                    _result("new", "success", recall=0.11, f1=0.21, matched=6),
                    _result("improved", "quality_failed", recall=0.43, f1=0.42, matched=31),
                    _result("regressed", "quality_failed", recall=0.47, f1=0.48, matched=19),
                    _result("diag", "quality_failed", recall=0.30, f1=0.30, matched=10),
                    _result("same", "quality_failed", recall=0.30, f1=0.30, matched=10),
                    _result("missing_baseline", "quality_failed", recall=0.30, f1=0.30, matched=10),
                ],
            )
            _write_diagnostics(baseline, "improved", predicted_count=100, short_ratio=0.20, quant_mean=0.010, quant_p95=0.020, quant_max=0.030)
            _write_diagnostics(candidate, "improved", predicted_count=120, short_ratio=0.25, quant_mean=0.006, quant_p95=0.012, quant_max=0.018)
            _write_diagnostics(baseline, "diag", stage="selector", pitch_flags=["low_confidence"])
            _write_diagnostics(candidate, "diag", stage="quantizer", pitch_flags=["low_confidence"])
            _write_diagnostics(baseline, "same", stage="selector")
            _write_diagnostics(candidate, "same", stage="selector")

            report = compare_benchmark_runs(baseline, candidate)
            by_id = {item["sample_id"]: item for item in report["per_sample"]}

            self.assertEqual(by_id["lost"]["group"], GROUP_LOST_SUCCESS)
            self.assertEqual(by_id["new"]["group"], GROUP_NEW_SUCCESS)
            self.assertEqual(by_id["improved"]["group"], GROUP_IMPROVED)
            self.assertEqual(by_id["regressed"]["group"], GROUP_REGRESSED)
            self.assertEqual(by_id["diag"]["group"], GROUP_DIAGNOSTICS_CHANGED)
            self.assertEqual(by_id["same"]["group"], GROUP_UNCHANGED)
            self.assertEqual(by_id["missing_baseline"]["group"], GROUP_NEEDS_MANUAL_REVIEW)
            self.assertEqual(by_id["missing_candidate"]["group"], GROUP_NEEDS_MANUAL_REVIEW)

            improved = by_id["improved"]
            self.assertAlmostEqual(improved["deltas"]["recall"], 0.03)
            self.assertAlmostEqual(improved["deltas"]["matched"], 11.0)
            self.assertAlmostEqual(improved["deltas"]["coverage"], 0.03)
            self.assertAlmostEqual(improved["deltas"]["first_delay"], -0.03)
            self.assertEqual(improved["metrics"]["matched"]["old"]["source"], "metrics.matched_note_count")
            self.assertAlmostEqual(improved["deltas"]["predicted_note_count"], 20.0)
            self.assertAlmostEqual(improved["deltas"]["predicted_short_note_ratio"], 0.05)
            self.assertAlmostEqual(improved["deltas"]["quantization_mean_error"], -0.004)
            self.assertAlmostEqual(improved["deltas"]["quantization_p95_error"], -0.008)
            self.assertAlmostEqual(improved["deltas"]["quantization_max_error"], -0.012)

            self.assertEqual(by_id["diag"]["preliminary_failure_stage_v2"], {"old": "selector", "new": "quantizer"})
            self.assertEqual(report["aggregate_counts"][GROUP_LOST_SUCCESS], 1)
            self.assertEqual(report["aggregate_counts"][GROUP_NEEDS_MANUAL_REVIEW], 2)

    def test_missing_fields_are_unavailable_without_crashing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline"
            candidate = root / "candidate"
            _write_run(baseline, [{"sample_id": "partial", "status": "quality_failed", "metrics": {"note_recall": 0.1}}])
            _write_run(candidate, [{"sample_id": "partial", "status": "quality_failed", "metrics": {"note_recall": 0.1}}])

            report = compare_benchmark_runs(baseline, candidate)
            sample = report["per_sample"][0]

            self.assertEqual(sample["group"], GROUP_NEEDS_MANUAL_REVIEW)
            self.assertEqual(sample["metrics"]["f1"]["old"]["value"], UNAVAILABLE)
            self.assertEqual(sample["metrics"]["quantization_mean_error"]["old"]["value"], UNAVAILABLE)
            self.assertEqual(sample["debug_diagnostics"]["old"]["available"], False)

    def test_cli_writes_json_and_markdown_reports(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline"
            candidate = root / "candidate"
            output = root / "ab_report"
            _write_run(baseline, [_result("same", "success", recall=0.5, f1=0.6, matched=10)])
            _write_run(candidate, [_result("same", "success", recall=0.5, f1=0.6, matched=10)])

            exit_code = compare_main(["--baseline-run", str(baseline), "--candidate-run", str(candidate), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "ab_report.json").exists())
            self.assertTrue((output / "ab_report.md").exists())
            payload = json.loads((output / "ab_report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["per_sample"][0]["sample_id"], "same")
            self.assertIn("Benchmark A/B Report", (output / "ab_report.md").read_text(encoding="utf-8"))

    def test_write_report_helper_creates_output_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "ab"
            json_path, markdown_path = write_comparison_report(
                {
                    "generated_at": "now",
                    "baseline_run": "old",
                    "candidate_run": "new",
                    "aggregate_counts": {},
                    "groups": {},
                    "per_sample": [],
                },
                output,
            )

            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())


def _write_run(path: Path, results: list[dict[str, object]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    summary = {
        "manifest": {
            "samples": [
                {"id": str(result["sample_id"]), "title": f"Title {result['sample_id']}"}
                for result in results
                if "sample_id" in result
            ]
        },
        "results": results,
    }
    (path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def _result(sample_id: str, status: str, *, recall: float, f1: float, matched: int) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "status": status,
        "metrics": {"note_recall": recall, "note_f1": f1, "matched_note_count": matched},
        "alignment": {
            "shift_corrected_recall": recall + 0.1,
            "dtw": {"dtw_pitch_match_recall_proxy": recall + 0.2},
        },
        "audibility": {"midi_coverage_ratio": recall + 0.3, "first_note_delay_sec": 2.0 - recall},
        "quality_gate": {"failed_checks": [] if status == "success" else ["low_recall"]},
    }


def _write_diagnostics(
    run_root: Path,
    sample_id: str,
    *,
    stage: str = "none",
    pitch_flags: list[str] | None = None,
    predicted_count: int = 10,
    short_ratio: float = 0.1,
    quant_mean: float = 0.01,
    quant_p95: float = 0.02,
    quant_max: float = 0.03,
) -> None:
    package = run_root / sample_id / "debug_package"
    package.mkdir(parents=True, exist_ok=True)
    payload = {
        "preliminary_failure_stage_v2": stage,
        "pitch_flags": pitch_flags or [],
        "notes": {
            "predicted_note_count": predicted_count,
            "predicted_short_note_ratio": short_ratio,
        },
        "quantized_notes": {
            "mean_quantize_error_sec": quant_mean,
            "p95_quantize_error_sec": quant_p95,
            "max_quantize_error_sec": quant_max,
            "fragmentation": {"risk_score": 0.2},
            "overmerge": {"risk_score": 0.1},
        },
    }
    (package / "derived_diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
