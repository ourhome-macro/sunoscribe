from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
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
    build_midi_diagnostics,
    build_dataset_report,
    compute_midi_alignment_diagnostics,
    compute_midi_audibility_metrics,
    compute_midi_metrics,
    find_midi_track_index_by_name,
    infer_midi_failure_modes,
    load_manifest,
    read_midi_notes,
    read_midi_track_info,
    build_mvp_readiness_report,
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
    quality_gate: dict[str, Any] | None = None
    logs: dict[str, str] = field(default_factory=dict)
    workspace_path: Path | None = None
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


QUALITY_GATE_THRESHOLDS: dict[str, float | int] = {
    "first_note_delay_sec_max": 15.0,
    "midi_coverage_ratio_min": 0.45,
    "note_recall_min": 0.05,
    "matched_notes_min": 10,
}


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

    if args.command == "doctor":
        readiness = build_mvp_readiness_report(deep_pitch=args.deep_pitch_check)
        _write_json(run_root / "readiness_report.json", readiness.to_dict())
        _write_summary_files(
            run_root=run_root,
            manifest=manifest,
            results=[],
            dataset_report=dataset_report.to_dict(),
            readiness_report=readiness.to_dict(),
        )
        print(f"readiness report written to {run_root / 'readiness_report.json'}")
        return 0 if readiness.status == "ok" and not dataset_report.errors else 2

    if args.command == "validate":
        _write_summary_files(run_root=run_root, manifest=manifest, results=[], dataset_report=dataset_report.to_dict())
        print(f"dataset report written to {run_root / 'dataset_report.json'}")
        return 0 if not dataset_report.errors else 2

    selected_samples = _select_samples(manifest, sample_ids=args.sample_id, limit=args.limit)
    if not selected_samples:
        print("No enabled samples selected.", file=sys.stderr)
        return 2

    projects_root = Path(args.projects_root) if args.projects_root else run_root / "projects"
    readiness = build_mvp_readiness_report(deep_pitch=args.deep_pitch_check)
    _write_json(run_root / "readiness_report.json", readiness.to_dict())
    if readiness.status != "ok" and not args.ignore_readiness:
        _write_summary_files(
            run_root=run_root,
            manifest=manifest,
            results=[],
            dataset_report=dataset_report.to_dict(),
            readiness_report=readiness.to_dict(),
        )
        print(f"readiness failed; report written to {run_root / 'readiness_report.json'}", file=sys.stderr)
        return 1
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
                metric_config=MidiMetricConfig(onset_tolerance_sec=args.onset_tolerance_ms / 1000.0),
            )
        )
        results.append(result)
        print(f"{sample.id}: {result.status}")

    _write_summary_files(
        run_root=run_root,
        manifest=manifest,
        results=results,
        dataset_report=dataset_report.to_dict(),
        readiness_report=readiness.to_dict(),
    )
    _write_quality_diagnostics(run_root=run_root, results=results)
    if any(result.status == "failed" for result in results):
        return 1
    if any(result.status == "quality_failed" for result in results):
        return 2
    return 0


async def _run_sample(
    *,
    sample: BenchmarkSample,
    manifest: BenchmarkManifest,
    run_root: Path,
    projects_root: Path,
    metric_config: MidiMetricConfig,
) -> SampleRunResult:
    sample_run_dir = run_root / sample.id
    sample_run_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = sample_run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logs = {
        "stdout": str(logs_dir / "stdout.log"),
        "stderr": str(logs_dir / "stderr.log"),
        "python_logging": str(logs_dir / "python_logging.log"),
    }
    with _sample_logging_context(logs=logs):
        return await _run_sample_logged(
            sample=sample,
            manifest=manifest,
            sample_run_dir=sample_run_dir,
            projects_root=projects_root,
            logs=logs,
            metric_config=metric_config,
        )


async def _run_sample_logged(
    *,
    sample: BenchmarkSample,
    manifest: BenchmarkManifest,
    sample_run_dir: Path,
    projects_root: Path,
    logs: dict[str, str],
    metric_config: MidiMetricConfig,
) -> SampleRunResult:
    stage_records: list[StageRecord] = []
    produced_midi_path: Path | None = None
    metrics_payload: dict[str, Any] | None = None
    quality_gate_payload: dict[str, Any] | None = None
    warnings: list[str] = []
    error_payload: dict[str, Any] | None = None
    project_id = _project_id_for_sample(sample.id)
    project_dir = projects_root / project_id
    status = "failed"

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
        outputs["workspace_path"] = str(project_dir)
        outputs["logs"] = logs
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
        quality_record, quality_gate_payload = _quality_gate_stage(metrics_payload=metrics_payload)
        stage_records.append(quality_record)
        _write_json(sample_run_dir / "quality_gate.json", quality_gate_payload)
        status = "success" if quality_record.status == "success" else "quality_failed"
    except Exception as exc:
        status = "failed"
        error_payload = _error_payload(exc)
        _write_json(sample_run_dir / "error.json", error_payload)
    finally:
        _write_json(
            sample_run_dir / "stage_status.json",
            {"stages": [record.to_dict() for record in stage_records], "logs": logs, "workspace_path": str(project_dir)},
        )

    return SampleRunResult(
        sample_id=sample.id,
        status=status,
        run_dir=sample_run_dir,
        produced_midi_path=sample_run_dir / "produced.mid" if (sample_run_dir / "produced.mid").exists() else produced_midi_path,
        metrics=metrics_payload,
        stage_records=stage_records,
        quality_gate=quality_gate_payload,
        logs=logs,
        workspace_path=project_dir,
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
        predicted_tracks = read_midi_track_info(produced_midi_path)
        predicted_lead_track = find_midi_track_index_by_name(produced_midi_path, "Lead Vocal")
        if predicted_lead_track is None:
            predicted_lead_track = next((track.index for track in predicted_tracks if track.note_count > 0), None)
        predicted_notes = read_midi_notes(produced_midi_path, track_index=predicted_lead_track)
        metrics = compute_midi_metrics(expected_notes, predicted_notes, config=metric_config)
        audibility = compute_midi_audibility_metrics(expected_notes, predicted_notes)
        alignment = compute_midi_alignment_diagnostics(expected_notes, predicted_notes, config=metric_config)
        diagnostics = build_midi_diagnostics(metrics, audibility, alignment)
        failure_modes = infer_midi_failure_modes(metrics, audibility, alignment)
        hook_track = next(
            (track for track in predicted_tracks if str(track.name or "").strip().lower() == "instrumental hook"),
            None,
        )
        payload = {
            "sample_id": sample.id,
            "expected_midi": str(sample.expected_midi),
            "expected_melody_track": sample.expected_melody_track,
            "produced_midi": str(produced_midi_path),
            "predicted_lead_track": predicted_lead_track,
            "instrumental_hook_note_count": hook_track.note_count if hook_track else 0,
            "config": asdict(metric_config),
            "expected_tracks": [track.to_dict() for track in read_midi_track_info(sample.expected_midi)],
            "predicted_tracks": [track.to_dict() for track in predicted_tracks],
            "metrics": metrics.to_dict(),
            "audibility": audibility.to_dict(),
            "alignment": alignment.to_dict(),
            "diagnostics": diagnostics,
            "suspected_failure_modes": failure_modes,
        }
        return (
            StageRecord(
                name="midi_metrics",
                status="success",
                started_at=started_at,
                duration_sec=time.perf_counter() - start,
                inputs={"expected_midi": str(sample.expected_midi), "produced_midi": str(produced_midi_path)},
                outputs={
                    "metrics": metrics.to_dict(),
                    "audibility": audibility.to_dict(),
                    "alignment": alignment.to_dict(),
                    "suspected_failure_modes": failure_modes,
                },
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


def _quality_gate_stage(*, metrics_payload: dict[str, Any]) -> tuple[StageRecord, dict[str, Any]]:
    started_at = _utc_now()
    start = time.perf_counter()
    metrics = metrics_payload.get("metrics") or {}
    audibility = metrics_payload.get("audibility") or {}
    checks = [
        _quality_check_max(
            name="first_note_delay_sec",
            actual=audibility.get("first_note_delay_sec"),
            threshold=QUALITY_GATE_THRESHOLDS["first_note_delay_sec_max"],
        ),
        _quality_check_min(
            name="midi_coverage_ratio",
            actual=audibility.get("midi_coverage_ratio"),
            threshold=QUALITY_GATE_THRESHOLDS["midi_coverage_ratio_min"],
        ),
        _quality_check_min(
            name="note_recall",
            actual=metrics.get("note_recall"),
            threshold=QUALITY_GATE_THRESHOLDS["note_recall_min"],
        ),
        _quality_check_min(
            name="matched_notes",
            actual=metrics.get("matched_note_count"),
            threshold=QUALITY_GATE_THRESHOLDS["matched_notes_min"],
        ),
    ]
    failed_checks = [check for check in checks if not check["passed"]]
    payload = {
        "status": "success" if not failed_checks else "quality_failed",
        "thresholds": QUALITY_GATE_THRESHOLDS,
        "checks": checks,
        "failed_checks": failed_checks,
        "diagnostic_only": {
            "note_f1": metrics.get("note_f1"),
            "note_precision": metrics.get("note_precision"),
            "pitch_accuracy": metrics.get("pitch_accuracy"),
            "octave_error_rate": metrics.get("octave_error_rate"),
        },
        "suspected_failure_modes": metrics_payload.get("suspected_failure_modes") or [],
    }
    return (
        StageRecord(
            name="quality_gate",
            status=payload["status"],
            started_at=started_at,
            duration_sec=time.perf_counter() - start,
            inputs={"metrics_json": metrics_payload.get("produced_midi")},
            outputs=payload,
            error={"failed_checks": failed_checks} if failed_checks else None,
        ),
        payload,
    )


def _quality_check_min(*, name: str, actual: Any, threshold: float | int) -> dict[str, Any]:
    value = _as_float(actual)
    return {
        "name": name,
        "operator": ">=",
        "actual": actual,
        "threshold": threshold,
        "passed": value is not None and value >= float(threshold),
    }


def _quality_check_max(*, name: str, actual: Any, threshold: float | int) -> dict[str, Any]:
    value = _as_float(actual)
    return {
        "name": name,
        "operator": "<=",
        "actual": actual,
        "threshold": threshold,
        "passed": value is not None and value <= float(threshold),
    }


def _write_summary_files(
    *,
    run_root: Path,
    manifest: BenchmarkManifest,
    results: list[SampleRunResult],
    dataset_report: dict[str, Any],
    readiness_report: dict[str, Any] | None = None,
) -> None:
    metric_payloads = [result.metrics for result in results if result.metrics]
    metrics_values = [payload["metrics"] for payload in metric_payloads if payload.get("metrics")]
    status_counts = {
        "success": sum(1 for result in results if result.status == "success"),
        "quality_failed": sum(1 for result in results if result.status == "quality_failed"),
        "failed": sum(1 for result in results if result.status == "failed"),
    }
    summary = {
        "run_root": str(run_root),
        "created_at": _utc_now(),
        "manifest": manifest.to_dict(),
        "dataset": dataset_report,
        "readiness": readiness_report,
        "status_counts": status_counts,
        "quality_gate_thresholds": QUALITY_GATE_THRESHOLDS,
        "results": [
            {
                "sample_id": result.sample_id,
                "status": result.status,
                "run_dir": str(result.run_dir),
                "produced_midi_path": str(result.produced_midi_path) if result.produced_midi_path else None,
                "metrics": result.metrics.get("metrics") if result.metrics else None,
                "audibility": result.metrics.get("audibility") if result.metrics else None,
                "alignment": result.metrics.get("alignment") if result.metrics else None,
                "diagnostics": result.metrics.get("diagnostics") if result.metrics else None,
                "suspected_failure_modes": result.metrics.get("suspected_failure_modes") if result.metrics else [],
                "quality_gate": result.quality_gate,
                "logs": result.logs,
                "workspace_path": str(result.workspace_path) if result.workspace_path else None,
                "error": result.error,
                "warnings": result.warnings,
            }
            for result in results
        ],
        "aggregate_metrics": _aggregate_metrics(metrics_values, metric_payloads=metric_payloads),
    }
    _write_json(run_root / "summary.json", summary)
    (run_root / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")


def _summary_markdown(summary: dict[str, Any]) -> str:
    results = summary.get("results") or []
    aggregate = summary.get("aggregate_metrics") or {}
    readiness = summary.get("readiness") or {}
    lines = [
        "# MP4->MIDI Benchmark Summary",
        "",
        f"- Created at: `{summary.get('created_at')}`",
        f"- Samples run: `{len(results)}`",
        f"- Success: `{(summary.get('status_counts') or {}).get('success', 0)}`",
        f"- Quality failed: `{(summary.get('status_counts') or {}).get('quality_failed', 0)}`",
        f"- Failed: `{(summary.get('status_counts') or {}).get('failed', 0)}`",
        f"- Mean note F1: `{aggregate.get('note_f1_mean')}`",
        f"- Mean pitch accuracy: `{aggregate.get('pitch_accuracy_mean')}`",
        f"- Mean MIDI coverage: `{aggregate.get('midi_coverage_ratio_mean')}`",
        f"- Mean first-note delay: `{aggregate.get('first_note_delay_sec_mean')}`",
        f"- Readiness: `{readiness.get('status', 'not_checked')}`",
        "",
        "| Sample | Status | Note F1 | Recall | Matched | Coverage | First Delay s | Best Oct Rec | Best Time Rec | Pitch Acc | Failure Modes | Error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for result in results:
        metrics = result.get("metrics") or {}
        audibility = result.get("audibility") or {}
        alignment = result.get("alignment") or {}
        error = result.get("error") or {}
        lines.append(
            "| {sample} | {status} | {f1} | {recall} | {matched} | {coverage} | {delay} | {best_oct} | {best_time} | {pitch} | {modes} | {error} |".format(
                sample=result.get("sample_id"),
                status=result.get("status"),
                f1=_fmt_metric(metrics.get("note_f1")),
                recall=_fmt_metric(metrics.get("note_recall")),
                matched=metrics.get("matched_note_count") if metrics else "",
                coverage=_fmt_metric(audibility.get("midi_coverage_ratio")),
                delay=_fmt_metric(audibility.get("first_note_delay_sec")),
                best_oct=_fmt_metric(alignment.get("best_octave_shift_note_recall")),
                best_time=_fmt_metric(alignment.get("best_time_shift_note_recall")),
                pitch=_fmt_metric(metrics.get("pitch_accuracy")),
                modes=", ".join(result.get("suspected_failure_modes") or []),
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
    if readiness:
        lines.extend(["", "## MVP Readiness", ""])
        for check in readiness.get("checks") or []:
            lines.append(
                "- `{name}`: `{status}` — {message}".format(
                    name=check.get("name"),
                    status=check.get("status"),
                    message=check.get("message"),
                )
            )
    return "\n".join(lines) + "\n"


def _aggregate_metrics(metrics_values: list[dict[str, Any]], *, metric_payloads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    keys = ["note_precision", "note_recall", "note_f1", "pitch_accuracy", "duration_overlap", "octave_error_rate"]
    aggregate: dict[str, Any] = {"metric_sample_count": len(metrics_values)}
    for key in keys:
        values = [float(metrics[key]) for metrics in metrics_values if metrics.get(key) is not None]
        aggregate[f"{key}_mean"] = (sum(values) / len(values)) if values else None
    onset_values = [float(metrics["onset_mae_ms"]) for metrics in metrics_values if metrics.get("onset_mae_ms") is not None]
    aggregate["onset_mae_ms_mean"] = (sum(onset_values) / len(onset_values)) if onset_values else None
    audibility_values = [payload.get("audibility") or {} for payload in metric_payloads or []]
    for key in ["midi_coverage_ratio", "first_note_delay_sec", "duration_ratio", "longest_silence_sec"]:
        values = [float(item[key]) for item in audibility_values if item.get(key) is not None]
        aggregate[f"{key}_mean"] = (sum(values) / len(values)) if values else None
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


class _TeeStream:
    def __init__(self, *streams: Any) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(bool(getattr(stream, "isatty", lambda: False)()) for stream in self._streams)


@contextlib.contextmanager
def _sample_logging_context(*, logs: dict[str, str]):
    stdout_path = Path(logs["stdout"])
    stderr_path = Path(logs["stderr"])
    logging_path = Path(logs["python_logging"])
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(logging_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    with stdout_path.open("a", encoding="utf-8", buffering=1) as stdout_file, stderr_path.open(
        "a", encoding="utf-8", buffering=1
    ) as stderr_file:
        with contextlib.redirect_stdout(_TeeStream(sys.__stdout__, stdout_file)), contextlib.redirect_stderr(
            _TeeStream(sys.__stderr__, stderr_file)
        ):
            try:
                yield
            finally:
                root_logger.removeHandler(handler)
                handler.close()


def _write_quality_diagnostics(*, run_root: Path, results: list[SampleRunResult]) -> None:
    samples: list[dict[str, Any]] = []
    for result in results:
        metrics = result.metrics.get("metrics") if result.metrics else None
        audibility = result.metrics.get("audibility") if result.metrics else None
        alignment = result.metrics.get("alignment") if result.metrics else None
        samples.append(
            {
                "sample_id": result.sample_id,
                "status": result.status,
                "run_dir": str(result.run_dir),
                "produced_midi_path": str(result.produced_midi_path) if result.produced_midi_path else None,
                "metrics_json": str(result.run_dir / "metrics.json") if result.metrics else None,
                "quality_gate_json": str(result.run_dir / "quality_gate.json") if result.quality_gate else None,
                "stage_status_json": str(result.run_dir / "stage_status.json"),
                "logs": result.logs,
                "workspace_path": str(result.workspace_path) if result.workspace_path else None,
                "metrics": metrics,
                "audibility": audibility,
                "alignment": alignment,
                "diagnostics": result.metrics.get("diagnostics") if result.metrics else None,
                "quality_gate": result.quality_gate,
                "suspected_failure_modes": result.metrics.get("suspected_failure_modes") if result.metrics else [],
                "error": result.error,
            }
        )
    payload = {
        "run_root": str(run_root),
        "created_at": _utc_now(),
        "quality_gate_thresholds": QUALITY_GATE_THRESHOLDS,
        "status_counts": {
            "success": sum(1 for result in results if result.status == "success"),
            "quality_failed": sum(1 for result in results if result.status == "quality_failed"),
            "failed": sum(1 for result in results if result.status == "failed"),
        },
        "samples": samples,
    }
    _write_json(run_root / "quality_diagnostics.json", payload)
    (run_root / "quality_diagnostics.md").write_text(_quality_diagnostics_markdown(payload), encoding="utf-8")


def _quality_diagnostics_markdown(payload: dict[str, Any]) -> str:
    samples = payload.get("samples") or []
    metric_samples = [sample for sample in samples if sample.get("metrics")]
    lines = [
        "# Benchmark Quality Diagnostics",
        "",
        f"- Run root: `{payload.get('run_root')}`",
        f"- Created at: `{payload.get('created_at')}`",
        f"- Success: `{(payload.get('status_counts') or {}).get('success', 0)}`",
        f"- Quality failed: `{(payload.get('status_counts') or {}).get('quality_failed', 0)}`",
        f"- Failed: `{(payload.get('status_counts') or {}).get('failed', 0)}`",
        "",
        "## Worst By Note F1",
        "",
        "| Sample | Status | F1 | Recall | Matched | Coverage | First Delay s | Best Oct Rec | Best Time Rec | Failure Modes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for sample in sorted(metric_samples, key=lambda item: _sort_float((item.get("metrics") or {}).get("note_f1")))[:20]:
        lines.append(_quality_table_row(sample))
    lines.extend(
        [
            "",
            "## Worst By MIDI Coverage",
            "",
            "| Sample | Status | F1 | Recall | Matched | Coverage | First Delay s | Best Oct Rec | Best Time Rec | Failure Modes |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for sample in sorted(metric_samples, key=lambda item: _sort_float((item.get("audibility") or {}).get("midi_coverage_ratio")))[:20]:
        lines.append(_quality_table_row(sample))
    lines.extend(
        [
            "",
            "## Worst By First-Note Delay",
            "",
            "| Sample | Status | F1 | Recall | Matched | Coverage | First Delay s | Best Oct Rec | Best Time Rec | Failure Modes |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for sample in sorted(
        metric_samples,
        key=lambda item: _sort_float((item.get("audibility") or {}).get("first_note_delay_sec")),
        reverse=True,
    )[:20]:
        lines.append(_quality_table_row(sample))
    lines.extend(["", "## Logs", ""])
    for sample in samples:
        logs = sample.get("logs") or {}
        if logs:
            lines.append(f"- `{sample.get('sample_id')}`: stdout `{logs.get('stdout')}`, stderr `{logs.get('stderr')}`, logging `{logs.get('python_logging')}`")
    return "\n".join(lines) + "\n"


def _quality_table_row(sample: dict[str, Any]) -> str:
    metrics = sample.get("metrics") or {}
    audibility = sample.get("audibility") or {}
    alignment = sample.get("alignment") or {}
    return "| {sample_id} | {status} | {f1} | {recall} | {matched} | {coverage} | {delay} | {best_oct} | {best_time} | {modes} |".format(
        sample_id=sample.get("sample_id"),
        status=sample.get("status"),
        f1=_fmt_metric(metrics.get("note_f1")),
        recall=_fmt_metric(metrics.get("note_recall")),
        matched=metrics.get("matched_note_count"),
        coverage=_fmt_metric(audibility.get("midi_coverage_ratio")),
        delay=_fmt_metric(audibility.get("first_note_delay_sec")),
        best_oct=_fmt_metric(alignment.get("best_octave_shift_note_recall")),
        best_time=_fmt_metric(alignment.get("best_time_shift_note_recall")),
        modes=", ".join(sample.get("suspected_failure_modes") or []),
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic MP4->lead-vocal MIDI benchmark.")
    parser.add_argument(
        "command",
        choices=["doctor", "validate", "run"],
        help="Check MVP readiness, validate the dataset, or run the full benchmark.",
    )
    parser.add_argument("--manifest", default="../samples/manifest.v1.json", help="Path to manifest JSON.")
    parser.add_argument("--output-root", default=None, help="Benchmark runs output directory.")
    parser.add_argument("--projects-root", default=None, help="Temporary ProjectWorkspace root for pipeline artifacts.")
    parser.add_argument("--run-id", default=None, help="Stable run id. Defaults to timestamp.")
    parser.add_argument("--sample-id", action="append", default=[], help="Run only selected sample id; can be repeated.")
    parser.add_argument("--limit", type=int, default=None, help="Run at most N enabled samples.")
    parser.add_argument("--onset-tolerance-ms", type=float, default=120.0, help="Onset tolerance for MIDI matching.")
    parser.add_argument("--skip-checksum", action="store_true", help="Do not validate manifest checksums.")
    parser.add_argument("--keep-project-workspaces", action="store_true", help="Keep per-sample pipeline workspaces.")
    parser.add_argument("--deep-pitch-check", action="store_true", help="Try loading the RMVPE model during readiness checks.")
    parser.add_argument(
        "--ignore-readiness",
        action="store_true",
        help="Run even if MVP readiness checks fail; intended only for failure diagnosis.",
    )
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
        "ignore_readiness": bool(args.ignore_readiness),
        "deep_pitch_check": bool(args.deep_pitch_check),
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


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sort_float(value: Any) -> float:
    parsed = _as_float(value)
    return parsed if parsed is not None else float("inf")


if __name__ == "__main__":
    raise SystemExit(main())
