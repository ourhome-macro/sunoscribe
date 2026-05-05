from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from typing import Any
import uuid

from app.modules.benchmark import (
    BenchmarkManifest,
    BenchmarkSample,
    MidiMetricConfig,
    MidiReadError,
    build_dataset_report,
    compute_midi_metrics,
    load_manifest,
    read_midi_notes,
    read_midi_track_info,
)
from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisService


@dataclass(slots=True)
class StageRecord:
    name: str
    status: str
    started_at: str
    duration_sec: float
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SampleRunResult:
    sample_id: str
    status: str
    run_dir: Path
    produced_midi_path: Path | None
    metrics: dict[str, Any] | None
    stage_records: list[StageRecord]
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _force_production_pitch_profile()
    manifest = load_manifest(args.manifest)
    run_id = args.run_id or _default_run_id()
    output_root = Path(args.output_root) if args.output_root else manifest.root / "benchmark_runs"
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    dataset_report = build_dataset_report(
        samples_root=manifest.root,
        manifest=manifest,
        manifest_path=args.manifest,
        include_checksums=not args.skip_checksum,
    )
    _write_json(run_root / "dataset_report.json", dataset_report.to_dict())

    if args.command == "validate":
        _write_summary_files(run_root=run_root, manifest=manifest, results=[], dataset_report=dataset_report.to_dict())
        print(f"dataset report written to {run_root / 'dataset_report.json'}")
        return 0 if not dataset_report.errors else 2

    selected_samples = _select_samples(manifest, sample_ids=args.sample_id, limit=args.limit)
    if not selected_samples:
        print("No enabled samples selected.", file=sys.stderr)
        return 2

    projects_root = Path(args.projects_root) if args.projects_root else run_root / "projects"
    config_snapshot = _build_config_snapshot(args=args, run_id=run_id, manifest=manifest)
    _write_json(run_root / "config.json", config_snapshot)

    results: list[SampleRunResult] = []
    for sample in selected_samples:
        result = asyncio.run(
            _run_sample(
                sample=sample,
                manifest=manifest,
                run_root=run_root,
                projects_root=projects_root,
                keep_project_workspaces=args.keep_project_workspaces,
                metric_config=MidiMetricConfig(onset_tolerance_sec=args.onset_tolerance_ms / 1000.0),
            )
        )
        results.append(result)
        print(f"{sample.id}: {result.status}")

    _write_summary_files(run_root=run_root, manifest=manifest, results=results, dataset_report=dataset_report.to_dict())
    failed = [result for result in results if result.status != "success"]
    return 1 if failed else 0


async def _run_sample(
    *,
    sample: BenchmarkSample,
    manifest: BenchmarkManifest,
    run_root: Path,
    projects_root: Path,
    keep_project_workspaces: bool,
    metric_config: MidiMetricConfig,
) -> SampleRunResult:
    sample_run_dir = run_root / sample.id
    sample_run_dir.mkdir(parents=True, exist_ok=True)
    stage_records: list[StageRecord] = []
    produced_midi_path: Path | None = None
    metrics_payload: dict[str, Any] | None = None
    warnings: list[str] = []
    error_payload: dict[str, Any] | None = None
    project_id = _project_id_for_sample(sample.id)

    try:
        validation_record = _validate_sample_stage(sample=sample, root=manifest.root)
        stage_records.append(validation_record)
        if validation_record.status != "success":
            raise RuntimeError("sample validation failed")

        service = AudioAnalysisService(projects_root=projects_root)
        pipeline_start = time.perf_counter()
        pipeline_started_at = _utc_now()
        analysis_result = await service.process_audio(
            sample.input_mp4,
            AudioAnalysisOptions(
                project_id=project_id,
                enable_vocal_separation=True,
                enable_llm_refine=False,
                include_refine_debug=False,
            ),
        )
        pipeline_duration = time.perf_counter() - pipeline_start
        result_dict = analysis_result.to_dict()
        warnings.extend(str(warning) for warning in result_dict.get("warnings") or [])
        produced_midi_path = Path(str(analysis_result.midi_path)) if analysis_result.midi_path else None
        outputs = _pipeline_outputs(result_dict)
        required_errors = _required_pipeline_errors(result_dict, produced_midi_path)
        pipeline_status = "success" if not required_errors else "failed"
        stage_records.append(
            StageRecord(
                name="mp4_to_midi_pipeline",
                status=pipeline_status,
                started_at=pipeline_started_at,
                duration_sec=pipeline_duration,
                inputs={"input_mp4": str(sample.input_mp4)},
                outputs=outputs,
                warnings=list(warnings),
                error=None if pipeline_status == "success" else {"errors": required_errors},
            )
        )
        _write_json(sample_run_dir / "artifacts.json", outputs)
        if pipeline_status != "success" or produced_midi_path is None:
            raise RuntimeError("pipeline did not produce MIDI")
        shutil.copy2(produced_midi_path, sample_run_dir / "produced.mid")

        metrics_record, metrics_payload = _compute_metrics_stage(
            sample=sample,
            produced_midi_path=sample_run_dir / "produced.mid",
            metric_config=metric_config,
        )
        stage_records.append(metrics_record)
        if metrics_record.status != "success":
            raise RuntimeError("MIDI metrics failed")
        _write_json(sample_run_dir / "metrics.json", metrics_payload)
        status = "success"
    except Exception as exc:
        status = "failed"
        error_payload = _error_payload(exc)
        _write_json(sample_run_dir / "error.json", error_payload)
    finally:
        _write_json(sample_run_dir / "stage_status.json", {"stages": [record.to_dict() for record in stage_records]})
        if not keep_project_workspaces:
            project_dir = projects_root / project_id
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)

    return SampleRunResult(
        sample_id=sample.id,
        status=status,
        run_dir=sample_run_dir,
        produced_midi_path=sample_run_dir / "produced.mid" if (sample_run_dir / "produced.mid").exists() else produced_midi_path,
        metrics=metrics_payload,
        stage_records=stage_records,
        error=error_payload,
        warnings=warnings,
    )


def _validate_sample_stage(*, sample: BenchmarkSample, root: Path) -> StageRecord:
    started_at = _utc_now()
    start = time.perf_counter()
    errors: list[dict[str, Any]] = []
    if not sample.input_mp4.exists():
        errors.append({"code": "MISSING_INPUT_MP4", "path": str(sample.input_mp4)})
    if not sample.expected_midi.exists():
        errors.append({"code": "MISSING_EXPECTED_MIDI", "path": str(sample.expected_midi)})
    if sample.expected_melody_track is None:
        errors.append({"code": "MISSING_MELODY_TRACK"})
    try:
        track_info = [track.to_dict() for track in read_midi_track_info(sample.expected_midi)] if sample.expected_midi.exists() else []
    except MidiReadError as exc:
        track_info = []
        errors.append({"code": "CORRUPT_EXPECTED_MIDI", "message": str(exc)})
    if sample.expected_melody_track is not None and track_info:
        track_indexes = {int(track["index"]) for track in track_info}
        if sample.expected_melody_track not in track_indexes:
            errors.append({"code": "MELODY_TRACK_OUT_OF_RANGE", "track": sample.expected_melody_track})
    return StageRecord(
        name="dataset_validation",
        status="success" if not errors else "failed",
        started_at=started_at,
        duration_sec=time.perf_counter() - start,
        inputs={
            "input_mp4": _relative_or_str(sample.input_mp4, root),
            "expected_midi": _relative_or_str(sample.expected_midi, root),
            "expected_melody_track": sample.expected_melody_track,
        },
        outputs={"expected_midi_tracks": track_info},
        error={"errors": errors} if errors else None,
    )


def _compute_metrics_stage(
    *,
    sample: BenchmarkSample,
    produced_midi_path: Path,
    metric_config: MidiMetricConfig,
) -> tuple[StageRecord, dict[str, Any] | None]:
    started_at = _utc_now()
    start = time.perf_counter()
    try:
        expected_notes = read_midi_notes(sample.expected_midi, track_index=sample.expected_melody_track)
        predicted_notes = read_midi_notes(produced_midi_path, track_index=None)
        metrics = compute_midi_metrics(expected_notes, predicted_notes, config=metric_config)
        payload = {
            "sample_id": sample.id,
            "expected_midi": str(sample.expected_midi),
            "expected_melody_track": sample.expected_melody_track,
            "produced_midi": str(produced_midi_path),
            "config": asdict(metric_config),
            "expected_tracks": [track.to_dict() for track in read_midi_track_info(sample.expected_midi)],
            "predicted_tracks": [track.to_dict() for track in read_midi_track_info(produced_midi_path)],
            "metrics": metrics.to_dict(),
        }
        return (
            StageRecord(
                name="midi_metrics",
                status="success",
                started_at=started_at,
                duration_sec=time.perf_counter() - start,
                inputs={"expected_midi": str(sample.expected_midi), "produced_midi": str(produced_midi_path)},
                outputs={"metrics": metrics.to_dict()},
            ),
            payload,
        )
    except Exception as exc:
        return (
            StageRecord(
                name="midi_metrics",
                status="failed",
                started_at=started_at,
                duration_sec=time.perf_counter() - start,
                inputs={"expected_midi": str(sample.expected_midi), "produced_midi": str(produced_midi_path)},
                error=_error_payload(exc),
            ),
            None,
        )


def _write_summary_files(
    *,
    run_root: Path,
    manifest: BenchmarkManifest,
    results: list[SampleRunResult],
    dataset_report: dict[str, Any],
) -> None:
    metrics_values = [result.metrics["metrics"] for result in results if result.metrics and result.metrics.get("metrics")]
    summary = {
        "run_root": str(run_root),
        "created_at": _utc_now(),
        "manifest": manifest.to_dict(),
        "dataset": dataset_report,
        "results": [
            {
                "sample_id": result.sample_id,
                "status": result.status,
                "run_dir": str(result.run_dir),
                "produced_midi_path": str(result.produced_midi_path) if result.produced_midi_path else None,
                "metrics": result.metrics.get("metrics") if result.metrics else None,
                "error": result.error,
                "warnings": result.warnings,
            }
            for result in results
        ],
        "aggregate_metrics": _aggregate_metrics(metrics_values),
    }
    _write_json(run_root / "summary.json", summary)
    (run_root / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")


def _summary_markdown(summary: dict[str, Any]) -> str:
    results = summary.get("results") or []
    aggregate = summary.get("aggregate_metrics") or {}
    lines = [
        "# MP4->MIDI Benchmark Summary",
        "",
        f"- Created at: `{summary.get('created_at')}`",
        f"- Samples run: `{len(results)}`",
        f"- Success: `{sum(1 for result in results if result.get('status') == 'success')}`",
        f"- Failed: `{sum(1 for result in results if result.get('status') != 'success')}`",
        f"- Mean note F1: `{aggregate.get('note_f1_mean')}`",
        f"- Mean pitch accuracy: `{aggregate.get('pitch_accuracy_mean')}`",
        "",
        "| Sample | Status | Note F1 | Pitch Acc | Onset MAE ms | Error |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        metrics = result.get("metrics") or {}
        error = result.get("error") or {}
        lines.append(
            "| {sample} | {status} | {f1} | {pitch} | {onset} | {error} |".format(
                sample=result.get("sample_id"),
                status=result.get("status"),
                f1=_fmt_metric(metrics.get("note_f1")),
                pitch=_fmt_metric(metrics.get("pitch_accuracy")),
                onset=_fmt_metric(metrics.get("onset_mae_ms")),
                error=(error.get("type") or ""),
            )
        )
    dataset = summary.get("dataset") or {}
    lines.extend(
        [
            "",
            "## Dataset Completeness",
            "",
            f"- MP4 files: `{dataset.get('mp4_count')}`",
            f"- MIDI files: `{dataset.get('midi_count')}`",
            f"- Paired files: `{dataset.get('paired_count')}`",
            f"- Enabled samples: `{dataset.get('enabled_count')}`",
            f"- MP4 only: `{len(dataset.get('mp4_only') or [])}`",
            f"- MIDI only: `{len(dataset.get('midi_only') or [])}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _aggregate_metrics(metrics_values: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ["note_precision", "note_recall", "note_f1", "pitch_accuracy", "duration_overlap", "octave_error_rate"]
    aggregate: dict[str, Any] = {"metric_sample_count": len(metrics_values)}
    for key in keys:
        values = [float(metrics[key]) for metrics in metrics_values if metrics.get(key) is not None]
        aggregate[f"{key}_mean"] = (sum(values) / len(values)) if values else None
    onset_values = [float(metrics["onset_mae_ms"]) for metrics in metrics_values if metrics.get("onset_mae_ms") is not None]
    aggregate["onset_mae_ms_mean"] = (sum(onset_values) / len(onset_values)) if onset_values else None
    return aggregate


def _pipeline_outputs(result_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_audio_path": result_dict.get("source_audio_path"),
        "canonical_audio_path": result_dict.get("normalized_audio_path"),
        "vocals_path": result_dict.get("vocals_path"),
        "accompaniment_path": result_dict.get("accompaniment_path"),
        "midi_path": result_dict.get("midi_path"),
        "stem_paths": result_dict.get("stem_paths"),
        "has_f0_track": result_dict.get("f0_track") is not None,
        "has_note_candidates": result_dict.get("note_candidates") is not None,
        "has_rhythm_grid": result_dict.get("rhythm_grid") is not None,
        "has_score_data": result_dict.get("score_data") is not None,
        "warnings": result_dict.get("warnings") or [],
    }


def _required_pipeline_errors(result_dict: dict[str, Any], produced_midi_path: Path | None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not result_dict.get("normalized_audio_path"):
        errors.append({"code": "CANONICAL_AUDIO_MISSING"})
    if not result_dict.get("vocals_path"):
        errors.append({"code": "VOCALS_STEM_MISSING"})
    if result_dict.get("f0_track") is None:
        errors.append({"code": "F0_TRACK_MISSING"})
    if result_dict.get("note_candidates") is None:
        errors.append({"code": "NOTE_CANDIDATES_MISSING"})
    if result_dict.get("score_data") is None:
        errors.append({"code": "SCORE_DATA_MISSING"})
    if produced_midi_path is None or not produced_midi_path.exists():
        errors.append({"code": "MIDI_EXPORT_FAILED"})
    return errors


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic MP4->lead-vocal MIDI benchmark.")
    parser.add_argument("command", choices=["validate", "run"], help="Validate the dataset or run the full benchmark.")
    parser.add_argument("--manifest", default="../samples/manifest.v1.json", help="Path to manifest JSON.")
    parser.add_argument("--output-root", default=None, help="Benchmark runs output directory.")
    parser.add_argument("--projects-root", default=None, help="Temporary ProjectWorkspace root for pipeline artifacts.")
    parser.add_argument("--run-id", default=None, help="Stable run id. Defaults to timestamp.")
    parser.add_argument("--sample-id", action="append", default=[], help="Run only selected sample id; can be repeated.")
    parser.add_argument("--limit", type=int, default=None, help="Run at most N enabled samples.")
    parser.add_argument("--onset-tolerance-ms", type=float, default=120.0, help="Onset tolerance for MIDI matching.")
    parser.add_argument("--skip-checksum", action="store_true", help="Do not validate manifest checksums.")
    parser.add_argument("--keep-project-workspaces", action="store_true", help="Keep per-sample pipeline workspaces.")
    return parser.parse_args(argv)


def _select_samples(manifest: BenchmarkManifest, *, sample_ids: list[str], limit: int | None) -> list[BenchmarkSample]:
    samples = manifest.enabled_samples
    if sample_ids:
        selected_ids = set(sample_ids)
        samples = [sample for sample in samples if sample.id in selected_ids]
    if limit is not None:
        samples = samples[: max(0, int(limit))]
    return samples


def _build_config_snapshot(*, args: argparse.Namespace, run_id: str, manifest: BenchmarkManifest) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "manifest_version": manifest.version,
        "pitch_profile": os.environ.get("PITCH_PROFILE", "production"),
        "pitch_allow_backend_fallbacks": os.environ.get("PITCH_ALLOW_BACKEND_FALLBACKS", "false"),
        "pitch_backend_fallbacks": os.environ.get("PITCH_BACKEND_FALLBACKS", ""),
        "onset_tolerance_ms": args.onset_tolerance_ms,
        "command": args.command,
    }


def _force_production_pitch_profile() -> None:
    os.environ["PITCH_PROFILE"] = "production"
    os.environ["PITCH_ALLOW_BACKEND_FALLBACKS"] = "false"
    os.environ["PITCH_BACKEND_FALLBACKS"] = ""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:],
    }


def _project_id_for_sample(sample_id: str) -> str:
    return f"bench_{sample_id[:36]}_{uuid.uuid4().hex[:8]}"[:64]


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_or_str(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return str(path)


def _fmt_metric(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.4f}"
    except Exception:
        return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
