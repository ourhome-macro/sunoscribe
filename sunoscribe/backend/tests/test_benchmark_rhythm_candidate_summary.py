from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.rhythm_candidate_summary import (
    GROUP_CURRENT_STABLE,
    GROUP_HALF_DOUBLE,
    GROUP_MISSING,
    build_rhythm_candidate_summary,
    write_rhythm_candidate_summary,
)
from app.scripts.benchmark_rhythm_candidate_summary import main as summary_main


class BenchmarkRhythmCandidateSummaryTests(unittest.TestCase):
    def test_summary_groups_stable_half_tempo_and_missing_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "run"
            _write_summary(run_root, ["stable", "half", "missing"])
            _write_candidates(run_root, "stable", best_id="current_grid", current_rank=1, delta=0.0)
            _write_candidates(run_root, "half", best_id="half_tempo_grid", current_rank=2, delta=0.22)
            _write_derived_only(run_root, "missing")

            report = build_rhythm_candidate_summary(run_root)
            by_id = {sample["sample_id"]: sample for sample in report["samples"]}

            self.assertEqual(by_id["stable"]["recommended_next_action"], "keep_current_grid")
            self.assertEqual(by_id["stable"]["group"], GROUP_CURRENT_STABLE)
            self.assertEqual(by_id["half"]["recommended_next_action"], "inspect_half_double_tempo")
            self.assertEqual(by_id["half"]["group"], GROUP_HALF_DOUBLE)
            self.assertEqual(by_id["missing"]["recommended_next_action"], "regenerate_debug_package")
            self.assertEqual(by_id["missing"]["group"], GROUP_MISSING)
            self.assertEqual(by_id["half"]["current_score"], 0.6)
            self.assertEqual(by_id["half"]["best_score"], 0.82)
            self.assertEqual(by_id["half"]["current_off_grid_onset_ratio"], 0.3)
            self.assertEqual(report["aggregate_counts"][GROUP_CURRENT_STABLE], 1)
            self.assertEqual(report["aggregate_counts"][GROUP_HALF_DOUBLE], 1)
            self.assertEqual(report["aggregate_counts"][GROUP_MISSING], 1)

    def test_writes_json_markdown_and_cli_outputs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "run"
            output = root / "rhythm_candidate_summary"
            _write_summary(run_root, ["stable"])
            _write_candidates(run_root, "stable", best_id="current_grid", current_rank=1, delta=0.0)

            report = build_rhythm_candidate_summary(run_root)
            json_path, markdown_path = write_rhythm_candidate_summary(report, output)

            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertIn("Rhythm Candidate Summary", markdown_path.read_text(encoding="utf-8"))

            cli_output = root / "cli_output"
            exit_code = summary_main(["--run-root", str(run_root), "--output", str(cli_output)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((cli_output / "rhythm_candidate_summary.json").exists())
            self.assertTrue((cli_output / "rhythm_candidate_summary.md").exists())


def _write_summary(run_root: Path, sample_ids: list[str]) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {"samples": [{"id": sample_id, "title": f"Title {sample_id}"} for sample_id in sample_ids]},
        "results": [
            {
                "sample_id": sample_id,
                "status": "success" if sample_id == "stable" else "quality_failed",
                "quality_gate": {"failed_checks": [] if sample_id == "stable" else ["low_recall"]},
            }
            for sample_id in sample_ids
        ],
    }
    (run_root / "summary.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_candidates(run_root: Path, sample_id: str, *, best_id: str, current_rank: int, delta: float) -> None:
    package = run_root / sample_id / "debug_package"
    package.mkdir(parents=True, exist_ok=True)
    current_score = 0.6
    best_score = current_score + delta
    candidates = [
        _candidate("current_grid", current_score, off_grid=0.3, downbeat=0.5, bar_phase=0.5, rank=current_rank),
        _candidate(best_id, best_score, off_grid=0.1, downbeat=0.8, bar_phase=0.9, rank=1),
    ]
    if best_id == "current_grid":
        candidates = [_candidate("current_grid", 0.9, off_grid=0.05, downbeat=0.8, bar_phase=0.9, rank=1)]
        best_score = 0.9
    payload = {
        "available": True,
        "diagnostic_only": True,
        "candidates": candidates,
        "best_diagnostic_candidate_id": best_id,
        "current_candidate_rank": current_rank,
        "current_vs_best_score_delta": delta,
        "rhythm_candidate_warning": "possible_half_or_double_tempo_grid" if best_id == "half_tempo_grid" else None,
    }
    (package / "rhythm_grid_candidates.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (package / "derived_diagnostics.json").write_text(
        json.dumps({"rhythm": {"best_diagnostic_candidate_id": best_id, "current_candidate_rank": current_rank, "current_vs_best_score_delta": delta}}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_derived_only(run_root: Path, sample_id: str) -> None:
    package = run_root / sample_id / "debug_package"
    package.mkdir(parents=True, exist_ok=True)
    (package / "derived_diagnostics.json").write_text(json.dumps({"rhythm": {}}, ensure_ascii=False), encoding="utf-8")


def _candidate(candidate_id: str, score: float, *, off_grid: float, downbeat: float, bar_phase: float, rank: int) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_score": round(score, 6),
        "off_grid_onset_ratio": off_grid,
        "downbeat_confidence": downbeat,
        "bar_phase_confidence": bar_phase,
        "rank": rank,
    }


if __name__ == "__main__":
    unittest.main()
