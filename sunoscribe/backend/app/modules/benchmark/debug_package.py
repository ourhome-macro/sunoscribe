from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any

from .dataset import BenchmarkSample, load_manifest
from .midi_metrics import (
    MidiMetricConfig,
    NoteEvent,
    compute_midi_alignment_diagnostics,
    compute_midi_audibility_metrics,
    compute_midi_continuity_metrics,
    compute_midi_metrics,
    extract_reference_melody_notes,
    find_midi_track_index_by_name,
    read_midi_notes,
    read_midi_track_info,
)


DEBUG_PACKAGE_FILES = [
    "vocals.wav",
    "produced.mid",
    "expected_notes.json",
    "predicted_notes.json",
    "f0_track.json",
    "pitch_contours.json",
    "vocal_activity.json",
    "note_candidates.json",
    "rhythm_grid.json",
    "rhythm_debug.json",
    "rhythm_debug.md",
    "rhythm_grid_candidates.json",
    "rhythm_grid_candidates.md",
    "note_funnel_debug.json",
    "note_funnel_debug.md",
    "selected_melody.json",
    "quantized_notes.json",
    "score_ir.json",
    "match_debug.json",
    "alignment_debug.json",
    "derived_diagnostics.json",
    "mdx_diagnostics.json",
    "timeline_debug.png",
    "pitch_debug.md",
    "debug_summary.md",
]


@dataclass(slots=True)
class DebugPackageResult:
    sample_id: str
    run_root: str
    debug_dir: str
    found_files: list[str]
    missing_files: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def export_benchmark_debug_package(
    *,
    run_root: str | Path,
    manifest_path: str | Path,
    sample_id: str,
    metric_config: MidiMetricConfig | None = None,
) -> DebugPackageResult:
    run_root = Path(run_root).resolve(strict=False)
    manifest_path = Path(manifest_path).resolve(strict=False)
    manifest = load_manifest(manifest_path)
    sample = _find_sample(manifest.samples, sample_id)
    sample_metadata = _load_manifest_sample_metadata(manifest_path, sample_id)
    sample_run_dir = run_root / sample_id
    debug_dir = sample_run_dir / "debug_package"
    debug_dir.mkdir(parents=True, exist_ok=True)

    metric_config = metric_config or MidiMetricConfig()
    metrics_payload = _read_json(sample_run_dir / "metrics.json") or {}
    artifacts_payload = _read_json(sample_run_dir / "artifacts.json") or {}
    stage_payload = _read_json(sample_run_dir / "stage_status.json") or {}
    quality_payload = _read_json(sample_run_dir / "quality_gate.json") or {}
    summary_row = _load_summary_row(run_root, sample_id) or {}
    if not quality_payload and isinstance(summary_row.get("quality_gate"), dict):
        quality_payload = summary_row["quality_gate"]

    warnings: list[str] = []
    copied_files: set[str] = set()
    generated_files: set[str] = set()
    missing_files: set[str] = set()
    match_debug: dict[str, Any] | None = None
    alignment_debug: dict[str, Any] | None = None
    derived_diagnostics: dict[str, Any] | None = None
    note_funnel_debug: dict[str, Any] | None = None

    workspace_path = _resolve_workspace_path(
        artifacts_payload=artifacts_payload,
        stage_payload=stage_payload,
        run_root=run_root,
        sample_run_dir=sample_run_dir,
        manifest_root=manifest.root,
    )

    produced_source = _first_existing_path(
        [
            sample_run_dir / "produced.mid",
            metrics_payload.get("produced_midi"),
            summary_row.get("produced_midi_path"),
            artifacts_payload.get("midi_path"),
            workspace_path / "exports" / "final_score.mid" if workspace_path else None,
        ],
        run_root=run_root,
        sample_run_dir=sample_run_dir,
        manifest_root=manifest.root,
    )
    produced_debug_path = debug_dir / "produced.mid"
    if produced_source is not None:
        _copy_file(produced_source, produced_debug_path)
        copied_files.add("produced.mid")
    else:
        missing_files.add("produced.mid")

    for output_name, candidates in _copy_artifact_candidates(
        artifacts_payload=artifacts_payload,
        workspace_path=workspace_path,
        sample_run_dir=sample_run_dir,
    ).items():
        source = _first_existing_path(
            candidates,
            run_root=run_root,
            sample_run_dir=sample_run_dir,
            manifest_root=manifest.root,
        )
        if source is None:
            missing_files.add(output_name)
            continue
        _copy_file(source, debug_dir / output_name)
        copied_files.add(output_name)

    expected_notes: list[NoteEvent] = []
    predicted_notes: list[NoteEvent] = []
    reference_strategy = str(
        metrics_payload.get("expected_reference_strategy")
        or sample.expected_reference_strategy
        or "track"
    )
    reference_extraction_payload: dict[str, Any] | None = None
    predicted_lead_track: int | None = None

    try:
        expected_notes, reference_extraction = extract_reference_melody_notes(
            sample.expected_midi,
            track_index=sample.expected_melody_track,
            strategy=reference_strategy,
        )
        reference_strategy = reference_extraction.strategy
        reference_extraction_payload = reference_extraction.to_dict()
        _write_json(
            debug_dir / "expected_notes.json",
            {
                "sample_id": sample_id,
                "source_midi": str(sample.expected_midi),
                "reference_strategy": reference_strategy,
                "expected_melody_track": sample.expected_melody_track,
                "reference_extraction": reference_extraction_payload,
                "note_count": len(expected_notes),
                "notes": _notes_to_debug_dicts(expected_notes, prefix="exp"),
            },
        )
        generated_files.add("expected_notes.json")
    except Exception as exc:
        warnings.append(f"expected_notes export failed: {exc}")
        missing_files.add("expected_notes.json")

    if produced_debug_path.exists():
        try:
            predicted_lead_track = _predicted_lead_track(metrics_payload, produced_debug_path)
            predicted_notes = read_midi_notes(produced_debug_path, track_index=predicted_lead_track)
            _write_json(
                debug_dir / "predicted_notes.json",
                {
                    "sample_id": sample_id,
                    "source_midi": str(produced_debug_path),
                    "predicted_lead_track": predicted_lead_track,
                    "note_count": len(predicted_notes),
                    "notes": _notes_to_debug_dicts(predicted_notes, prefix="pred"),
                },
            )
            generated_files.add("predicted_notes.json")
        except Exception as exc:
            warnings.append(f"predicted_notes export failed: {exc}")
            missing_files.add("predicted_notes.json")
    else:
        missing_files.add("predicted_notes.json")

    rhythm_grid_path = debug_dir / "rhythm_grid.json"
    rhythm_debug = build_rhythm_debug(
        rhythm_grid_path=rhythm_grid_path if rhythm_grid_path.exists() else None,
        predicted_notes=predicted_notes,
    )
    _enrich_rhythm_grid_debug_copy(rhythm_grid_path, rhythm_debug)
    _write_json(debug_dir / "rhythm_debug.json", rhythm_debug)
    generated_files.add("rhythm_debug.json")
    (debug_dir / "rhythm_debug.md").write_text(
        build_rhythm_debug_markdown(
            sample_id=sample_id,
            sample_title=str(sample_metadata.get("title") or sample_id),
            rhythm_debug=rhythm_debug,
        ),
        encoding="utf-8",
    )
    generated_files.add("rhythm_debug.md")
    rhythm_candidates = build_rhythm_grid_candidates(
        rhythm_grid_path=rhythm_grid_path if rhythm_grid_path.exists() else None,
        predicted_notes=predicted_notes,
    )
    _write_json(debug_dir / "rhythm_grid_candidates.json", rhythm_candidates)
    generated_files.add("rhythm_grid_candidates.json")
    (debug_dir / "rhythm_grid_candidates.md").write_text(
        build_rhythm_grid_candidates_markdown(
            sample_id=sample_id,
            sample_title=str(sample_metadata.get("title") or sample_id),
            rhythm_candidates=rhythm_candidates,
        ),
        encoding="utf-8",
    )
    generated_files.add("rhythm_grid_candidates.md")

    note_funnel_debug = build_note_funnel_debug(
        expected_notes=expected_notes,
        predicted_notes=predicted_notes,
        f0_track_path=debug_dir / "f0_track.json" if (debug_dir / "f0_track.json").exists() else None,
        note_candidates_path=debug_dir / "note_candidates.json" if (debug_dir / "note_candidates.json").exists() else None,
        selected_melody_path=debug_dir / "selected_melody.json" if (debug_dir / "selected_melody.json").exists() else None,
        quantized_notes_path=debug_dir / "quantized_notes.json" if (debug_dir / "quantized_notes.json").exists() else None,
        score_ir_path=debug_dir / "score_ir.json" if (debug_dir / "score_ir.json").exists() else None,
    )
    _write_json(debug_dir / "note_funnel_debug.json", note_funnel_debug)
    generated_files.add("note_funnel_debug.json")
    (debug_dir / "note_funnel_debug.md").write_text(
        build_note_funnel_debug_markdown(
            sample_id=sample_id,
            sample_title=str(sample_metadata.get("title") or sample_id),
            note_funnel_debug=note_funnel_debug,
        ),
        encoding="utf-8",
    )
    generated_files.add("note_funnel_debug.md")

    if expected_notes and predicted_notes:
        if not metrics_payload.get("metrics"):
            metrics_payload = _computed_metrics_payload(
                sample=sample,
                produced_midi_path=produced_debug_path,
                expected_notes=expected_notes,
                predicted_notes=predicted_notes,
                reference_strategy=reference_strategy,
                reference_extraction_payload=reference_extraction_payload,
                predicted_lead_track=predicted_lead_track,
                metric_config=metric_config,
            )
        match_debug = build_match_debug(expected_notes, predicted_notes, config=metric_config)
        _write_json(debug_dir / "match_debug.json", match_debug)
        generated_files.add("match_debug.json")

        alignment_debug = build_alignment_debug(
            expected_notes,
            predicted_notes,
            metrics_payload=metrics_payload,
            config=metric_config,
        )
        _write_json(debug_dir / "alignment_debug.json", alignment_debug)
        generated_files.add("alignment_debug.json")

    derived_diagnostics = build_derived_diagnostics(
        expected_notes=expected_notes,
        predicted_notes=predicted_notes,
        f0_track_path=debug_dir / "f0_track.json" if (debug_dir / "f0_track.json").exists() else None,
        vocal_activity_path=debug_dir / "vocal_activity.json" if (debug_dir / "vocal_activity.json").exists() else None,
        note_candidates_path=debug_dir / "note_candidates.json" if (debug_dir / "note_candidates.json").exists() else None,
        pitch_contours_path=debug_dir / "pitch_contours.json" if (debug_dir / "pitch_contours.json").exists() else None,
        selected_melody_path=debug_dir / "selected_melody.json" if (debug_dir / "selected_melody.json").exists() else None,
        quantized_notes_path=debug_dir / "quantized_notes.json" if (debug_dir / "quantized_notes.json").exists() else None,
        score_ir_path=debug_dir / "score_ir.json" if (debug_dir / "score_ir.json").exists() else None,
        note_funnel_debug=note_funnel_debug,
        rhythm_debug_path=debug_dir / "rhythm_debug.json" if (debug_dir / "rhythm_debug.json").exists() else None,
        rhythm_candidates_path=debug_dir / "rhythm_grid_candidates.json" if (debug_dir / "rhythm_grid_candidates.json").exists() else None,
        match_debug=match_debug,
        alignment_debug=alignment_debug,
        metrics_payload=metrics_payload,
    )
    _write_json(debug_dir / "derived_diagnostics.json", derived_diagnostics)
    generated_files.add("derived_diagnostics.json")

    pitch_debug_markdown = build_pitch_debug_markdown(
        sample_id=sample_id,
        sample_title=str(sample_metadata.get("title") or sample_id),
        pitch_distribution=(
            derived_diagnostics.get("pitch_distribution") if isinstance(derived_diagnostics, dict) else None
        ),
    )
    (debug_dir / "pitch_debug.md").write_text(pitch_debug_markdown, encoding="utf-8")
    generated_files.add("pitch_debug.md")

    if expected_notes and predicted_notes and match_debug and alignment_debug:
        try:
            build_timeline_debug_png(
                output_path=debug_dir / "timeline_debug.png",
                expected_notes=expected_notes,
                predicted_notes=predicted_notes,
                f0_track_path=debug_dir / "f0_track.json" if (debug_dir / "f0_track.json").exists() else None,
                vocal_activity_path=debug_dir / "vocal_activity.json" if (debug_dir / "vocal_activity.json").exists() else None,
                match_debug=match_debug,
                alignment_debug=alignment_debug,
                metrics_payload=metrics_payload,
                sample_title=str(sample_metadata.get("title") or sample_id),
                derived_diagnostics=derived_diagnostics,
            )
            generated_files.add("timeline_debug.png")
        except Exception as exc:
            warnings.append(f"timeline_debug.png generation failed: {exc}")
            missing_files.add("timeline_debug.png")
    else:
        missing_files.update({"match_debug.json", "alignment_debug.json", "timeline_debug.png"})

    found_files = sorted(((copied_files | generated_files) & set(DEBUG_PACKAGE_FILES)) | {"debug_summary.md"})
    missing_files = (set(DEBUG_PACKAGE_FILES) - set(found_files)) | missing_files
    missing_files.discard("debug_summary.md")

    summary_markdown = build_debug_summary_markdown(
        sample=sample,
        sample_metadata=sample_metadata,
        run_root=run_root,
        sample_run_dir=sample_run_dir,
        metrics_payload=metrics_payload,
        summary_row=summary_row,
        quality_payload=quality_payload,
        expected_note_count=len(expected_notes),
        predicted_note_count=len(predicted_notes),
        reference_strategy=reference_strategy,
        found_files=found_files,
        missing_files=sorted(missing_files),
        warnings=warnings,
        derived_diagnostics=derived_diagnostics,
    )
    (debug_dir / "debug_summary.md").write_text(summary_markdown, encoding="utf-8")

    return DebugPackageResult(
        sample_id=sample_id,
        run_root=str(run_root),
        debug_dir=str(debug_dir),
        found_files=found_files,
        missing_files=sorted(missing_files),
        warnings=warnings,
    )


def build_match_debug(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig | None = None,
    predicted_time_shift_sec: float = 0.0,
) -> dict[str, Any]:
    config = config or MidiMetricConfig()
    shifted_predicted = _shift_debug_notes(predicted_notes, time_shift=predicted_time_shift_sec)
    metrics = compute_midi_metrics(expected_notes, shifted_predicted, config=config)
    predicted_pitch_shift = int(metrics.octave_shift_applied or 0)
    match_config = config
    if config.auto_octave_normalize:
        match_config = MidiMetricConfig(
            onset_tolerance_sec=config.onset_tolerance_sec,
            pitch_tolerance_semitones=config.pitch_tolerance_semitones,
            octave_tolerance_semitones=-1,
            auto_octave_normalize=False,
        )
    matches = _match_note_indices(
        expected_notes,
        predicted_notes,
        config=match_config,
        predicted_pitch_shift=predicted_pitch_shift,
        predicted_time_shift_sec=predicted_time_shift_sec,
    )
    matched_expected = {match[0] for match in matches}
    matched_predicted = {match[1] for match in matches}
    expected_debug = _notes_to_debug_dicts(expected_notes, prefix="exp")
    predicted_debug = _notes_to_debug_dicts(predicted_notes, prefix="pred")
    matched_pairs = []
    for expected_index, predicted_index in matches:
        expected_note = expected_notes[expected_index]
        predicted_note = predicted_notes[predicted_index]
        evaluated_predicted = _shift_debug_note(
            predicted_note,
            pitch_shift=predicted_pitch_shift,
            time_shift=predicted_time_shift_sec,
        )
        matched_pairs.append(
            {
                "expected_index": expected_index,
                "predicted_index": predicted_index,
                "expected_note": expected_debug[expected_index],
                "predicted_note": predicted_debug[predicted_index],
                "evaluated_predicted_note": _note_to_debug_dict(evaluated_predicted, f"pred_eval_{predicted_index:05d}"),
                "predicted_time_shift_sec": predicted_time_shift_sec,
                "predicted_pitch_shift_semitones": predicted_pitch_shift,
                "onset_delta_sec": round(evaluated_predicted.start - expected_note.start, 6),
                "abs_onset_delta_sec": round(abs(evaluated_predicted.start - expected_note.start), 6),
                "pitch_delta_semitones": int(evaluated_predicted.pitch - expected_note.pitch),
                "duration_iou": _duration_iou(expected_note, evaluated_predicted),
            }
        )

    return {
        "tolerances": {
            "onset_tolerance_sec": config.onset_tolerance_sec,
            "pitch_tolerance_semitones": config.pitch_tolerance_semitones,
            "octave_tolerance_semitones": config.octave_tolerance_semitones,
            "auto_octave_normalize": config.auto_octave_normalize,
        },
        "predicted_time_shift_sec": predicted_time_shift_sec,
        "predicted_pitch_shift_semitones": predicted_pitch_shift,
        "metrics": metrics.to_dict(),
        "matched_count": len(matches),
        "matched_pairs": matched_pairs,
        "unmatched_expected_notes": [
            expected_debug[index] for index in range(len(expected_debug)) if index not in matched_expected
        ],
        "unmatched_predicted_notes": [
            predicted_debug[index] for index in range(len(predicted_debug)) if index not in matched_predicted
        ],
    }


def build_alignment_debug(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    metrics_payload: dict[str, Any],
    config: MidiMetricConfig | None = None,
) -> dict[str, Any]:
    config = config or MidiMetricConfig()
    alignment_payload = metrics_payload.get("alignment") if isinstance(metrics_payload.get("alignment"), dict) else {}
    if not alignment_payload:
        alignment_payload = compute_midi_alignment_diagnostics(expected_notes, predicted_notes, config=config).to_dict()
    smart_payload = alignment_payload.get("smart_onset_alignment") if isinstance(alignment_payload.get("smart_onset_alignment"), dict) else {}
    shift = _as_float(_alignment_value(alignment_payload, smart_payload, "pred_to_exp_shift_sec")) or 0.0
    shift_corrected_matching = build_match_debug(
        expected_notes,
        predicted_notes,
        config=config,
        predicted_time_shift_sec=shift,
    )
    return {
        "pred_to_exp_shift_sec": shift,
        "shift_corrected_recall": _alignment_value(alignment_payload, smart_payload, "shift_corrected_recall"),
        "shift_corrected_f1": _alignment_value(alignment_payload, smart_payload, "shift_corrected_f1"),
        "shift_corrected_matched": _alignment_value(alignment_payload, smart_payload, "shift_corrected_matched"),
        "shift_corrected_coverage": _alignment_value(alignment_payload, smart_payload, "shift_corrected_coverage"),
        "shift_recall_gain": _alignment_value(alignment_payload, smart_payload, "shift_recall_gain"),
        "shift_f1_gain": _alignment_value(alignment_payload, smart_payload, "shift_f1_gain"),
        "shift_matched_gain": _alignment_value(alignment_payload, smart_payload, "shift_matched_gain"),
        "alignment_diagnosis": _alignment_value(alignment_payload, smart_payload, "alignment_diagnosis"),
        "raw_metrics_snapshot": {
            "metrics": metrics_payload.get("metrics") or {},
            "audibility": metrics_payload.get("audibility") or {},
            "diagnostics": metrics_payload.get("diagnostics") or {},
        },
        "alignment_snapshot": alignment_payload,
        "shift_corrected_matching_snapshot": shift_corrected_matching,
    }


def build_derived_diagnostics(
    *,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    f0_track_path: Path | None,
    vocal_activity_path: Path | None,
    note_candidates_path: Path | None,
    match_debug: dict[str, Any] | None,
    alignment_debug: dict[str, Any] | None,
    metrics_payload: dict[str, Any],
    pitch_contours_path: Path | None = None,
    selected_melody_path: Path | None = None,
    quantized_notes_path: Path | None = None,
    score_ir_path: Path | None = None,
    note_funnel_debug: dict[str, Any] | None = None,
    rhythm_debug_path: Path | None = None,
    rhythm_candidates_path: Path | None = None,
) -> dict[str, Any]:
    notes = _derive_note_diagnostics(expected_notes, predicted_notes)
    f0 = _derive_f0_diagnostics(f0_track_path)
    pitch_contours = _derive_pitch_contour_diagnostics(pitch_contours_path)
    vocal_activity = _derive_vocal_activity_diagnostics(vocal_activity_path)
    note_candidates = _derive_note_candidate_diagnostics(note_candidates_path, predicted_note_count=len(predicted_notes))
    selected_melody = _derive_selected_melody_diagnostics(selected_melody_path)
    quantized_notes = _derive_quantized_note_diagnostics(quantized_notes_path)
    rhythm = _derive_rhythm_diagnostics(rhythm_debug_path, rhythm_candidates_path=rhythm_candidates_path)
    short_note_diagnostics = _derive_short_note_diagnostics(
        expected_notes,
        predicted_notes,
        note_candidates_path=note_candidates_path,
        selected_melody_path=selected_melody_path,
        quantized_notes_path=quantized_notes_path,
    )
    note_funnel = note_funnel_debug or build_note_funnel_debug(
        expected_notes=expected_notes,
        predicted_notes=predicted_notes,
        f0_track_path=f0_track_path,
        note_candidates_path=note_candidates_path,
        selected_melody_path=selected_melody_path,
        quantized_notes_path=quantized_notes_path,
        score_ir_path=score_ir_path,
    )
    pitch_distribution = _derive_pitch_distribution_diagnostics(
        expected_notes=expected_notes,
        predicted_notes=predicted_notes,
        f0_track_path=f0_track_path,
        note_candidates_path=note_candidates_path,
    )
    match = _derive_match_diagnostics(
        match_debug=match_debug,
        alignment_debug=alignment_debug,
        expected_note_count=len(expected_notes),
        predicted_note_count=len(predicted_notes),
    )
    coverage = _coverage_from_metrics(metrics_payload)
    preliminary_failure_stage_v2 = _preliminary_failure_stage_v2(
        notes=notes,
        f0=f0,
        vocal_activity=vocal_activity,
        note_candidates=note_candidates,
        match=match,
        coverage=coverage,
        expected_available=bool(expected_notes),
        predicted_available=bool(predicted_notes),
        match_available=bool(match_debug),
    )
    return {
        "notes": notes,
        "continuity": compute_midi_continuity_metrics(predicted_notes).to_dict(),
        "f0": f0,
        "pitch_contours": pitch_contours,
        "vocal_activity": vocal_activity,
        "note_candidates": note_candidates,
        "selected_melody": selected_melody,
        "quantized_notes": quantized_notes,
        "rhythm": rhythm,
        "short_note_diagnostics": short_note_diagnostics,
        "note_funnel": note_funnel,
        "pitch_distribution": pitch_distribution,
        "match": match,
        "coverage": {
            "midi_coverage_ratio": coverage,
            "available": coverage is not None,
        },
        "preliminary_failure_stage_v2": preliminary_failure_stage_v2,
    }


def build_timeline_debug_png(
    *,
    output_path: Path,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    f0_track_path: Path | None,
    vocal_activity_path: Path | None,
    match_debug: dict[str, Any],
    alignment_debug: dict[str, Any],
    metrics_payload: dict[str, Any],
    sample_title: str,
    derived_diagnostics: dict[str, Any] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    output_path.parent.mkdir(parents=True, exist_ok=True)
    f0_points = _load_f0_points(f0_track_path)
    vocal_segments = _load_vocal_activity_segments(vocal_activity_path)

    fig, (pitch_ax, activity_ax) = plt.subplots(
        2,
        1,
        figsize=(18, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [5, 1]},
    )
    title = f"Benchmark Timeline Debug - {sample_title}"
    pitch_ax.set_title(title)
    pitch_ax.set_ylabel("MIDI pitch")
    activity_ax.set_ylabel("Vocal")
    activity_ax.set_xlabel("Time (sec)")

    _draw_vocal_activity_background(pitch_ax, vocal_segments)
    _draw_notes(pitch_ax, expected_notes, color="#1f77b4", y_offset=0.0, label="reference notes")
    _draw_notes(pitch_ax, predicted_notes, color="#ff7f0e", y_offset=0.18, label="predicted notes")
    if f0_points:
        pitch_ax.plot(
            [point[0] for point in f0_points],
            [point[1] for point in f0_points],
            color="#222222",
            linewidth=0.6,
            alpha=0.65,
            label="F0 contour",
        )

    _draw_match_markers(pitch_ax, match_debug, expected_notes, predicted_notes)
    _draw_shift_match_markers(pitch_ax, alignment_debug, predicted_notes)
    _draw_delay_and_shift_markers(pitch_ax, expected_notes, predicted_notes, metrics_payload, alignment_debug)
    _draw_derived_diagnostics_box(pitch_ax, derived_diagnostics)

    activity_ax.set_ylim(0, 1)
    activity_ax.set_yticks([0, 1])
    for start, end, active in vocal_segments:
        if active:
            activity_ax.axvspan(start, end, ymin=0.15, ymax=0.85, color="#2ca02c", alpha=0.45)
    activity_ax.grid(axis="x", alpha=0.25)
    pitch_ax.grid(alpha=0.25)
    pitch_ax.legend(loc="upper right", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=140)
    plt.close(fig)


def build_debug_summary_markdown(
    *,
    sample: BenchmarkSample,
    sample_metadata: dict[str, Any],
    run_root: Path,
    sample_run_dir: Path,
    metrics_payload: dict[str, Any],
    summary_row: dict[str, Any],
    quality_payload: dict[str, Any],
    expected_note_count: int,
    predicted_note_count: int,
    reference_strategy: str,
    found_files: list[str],
    missing_files: list[str],
    warnings: list[str],
    derived_diagnostics: dict[str, Any] | None = None,
) -> str:
    metrics = metrics_payload.get("metrics") if isinstance(metrics_payload.get("metrics"), dict) else {}
    audibility = metrics_payload.get("audibility") if isinstance(metrics_payload.get("audibility"), dict) else {}
    alignment = metrics_payload.get("alignment") if isinstance(metrics_payload.get("alignment"), dict) else {}
    smart = alignment.get("smart_onset_alignment") if isinstance(alignment.get("smart_onset_alignment"), dict) else {}
    dtw = alignment.get("dtw") if isinstance(alignment.get("dtw"), dict) else {}
    summary_metrics = summary_row.get("metrics") if isinstance(summary_row.get("metrics"), dict) else {}
    failed_checks = _failed_check_names(quality_payload, summary_row)
    status = str(summary_row.get("status") or quality_payload.get("status") or "unknown")
    title = str(sample_metadata.get("title") or sample_metadata.get("name") or sample.id)
    expected_duration = _duration_basis_from_notes_or_metrics(metrics_payload, expected_note_count, predicted_note_count)
    predicted_density = _safe_density(predicted_note_count, expected_duration)
    expected_density = _safe_density(expected_note_count, expected_duration)
    matched_density = _safe_density(_as_int(_metric_value(metrics, summary_metrics, "matched_note_count")) or 0, expected_duration)
    rhythm = derived_diagnostics.get("rhythm") if isinstance(derived_diagnostics, dict) and isinstance(derived_diagnostics.get("rhythm"), dict) else {}
    f0_available = "f0_track.json" in found_files
    vocal_activity_available = "vocal_activity.json" in found_files
    note_candidates_available = "note_candidates.json" in found_files
    possible_failure_stage = _possible_failure_stage(
        f0_available=f0_available,
        predicted_note_count=predicted_note_count,
        expected_note_count=expected_note_count,
        coverage=_as_float(_metric_value(audibility, summary_metrics, "midi_coverage_ratio")),
        raw_recall=_as_float(_metric_value(metrics, summary_metrics, "note_recall")),
        shift_recall=_as_float(_alignment_value(alignment, smart, "shift_corrected_recall")),
        dtw_recall=_as_float(dtw.get("dtw_pitch_match_recall_proxy")),
    )

    lines = [
        f"# Benchmark Debug Package: {title}",
        "",
        "## Sample",
        f"- sample title: {title}",
        f"- sample_id: {sample.id}",
        f"- run_id: {run_root.name}",
        f"- run_dir: {sample_run_dir}",
        f"- status: {status}",
        f"- failed checks: {', '.join(failed_checks) if failed_checks else 'none'}",
        f"- reference strategy: {reference_strategy}",
        f"- expected note count: {expected_note_count}",
        f"- predicted note count: {predicted_note_count}",
        "",
        "## Raw Metrics",
        f"- note_recall: {_fmt(_metric_value(metrics, summary_metrics, 'note_recall'))}",
        f"- note_f1: {_fmt(_metric_value(metrics, summary_metrics, 'note_f1'))}",
        f"- matched_note_count: {_fmt(_metric_value(metrics, summary_metrics, 'matched_note_count'))}",
        f"- midi_coverage_ratio: {_fmt(_metric_value(audibility, summary_metrics, 'midi_coverage_ratio'))}",
        f"- first_note_delay_sec: {_fmt(_metric_value(audibility, summary_metrics, 'first_note_delay_sec'))}",
        f"- pitch_accuracy: {_fmt(_metric_value(metrics, summary_metrics, 'pitch_accuracy'))}",
        "",
        "## Alignment Metrics",
        f"- pred_to_exp_shift_sec: {_fmt(_alignment_value(alignment, smart, 'pred_to_exp_shift_sec'))}",
        f"- shift_corrected_recall: {_fmt(_alignment_value(alignment, smart, 'shift_corrected_recall'))}",
        f"- shift_corrected_f1: {_fmt(_alignment_value(alignment, smart, 'shift_corrected_f1'))}",
        f"- shift_corrected_matched: {_fmt(_alignment_value(alignment, smart, 'shift_corrected_matched'))}",
        f"- shift_recall_gain: {_fmt(_alignment_value(alignment, smart, 'shift_recall_gain'))}",
        f"- shift_matched_gain: {_fmt(_alignment_value(alignment, smart, 'shift_matched_gain'))}",
        f"- alignment_diagnosis: {_fmt(_alignment_value(alignment, smart, 'alignment_diagnosis'))}",
        "",
        "## Rhythm Diagnostics",
        f"- tempo: {_fmt(rhythm.get('tempo_bpm'))} bpm",
        f"- tempo_stability: {_fmt(rhythm.get('tempo_stability'))}",
        f"- downbeat_confidence: {_fmt(rhythm.get('downbeat_confidence'))}",
        f"- off_grid_onset_ratio: {_fmt(rhythm.get('off_grid_onset_ratio'))}",
        f"- rhythm preliminary diagnosis: {_fmt(rhythm.get('preliminary_rhythm_diagnosis'))}",
        f"- current_candidate_rank: {_fmt(rhythm.get('current_candidate_rank'))}",
        f"- best_diagnostic_candidate_id: {_fmt(rhythm.get('best_diagnostic_candidate_id'))}",
        f"- current_vs_best_score_delta: {_fmt(rhythm.get('current_vs_best_score_delta'))}",
        f"- rhythm_candidate_warning: {_fmt(rhythm.get('rhythm_candidate_warning')) if rhythm.get('rhythm_candidate_warning') else 'none'}",
        "",
        "## Octave And DTW Metrics",
        f"- best octave shift: {_fmt(alignment.get('best_octave_shift_semitones'))}",
        f"- best octave recall: {_fmt(alignment.get('best_octave_shift_note_recall'))}",
        f"- dtw_recall: {_fmt(dtw.get('dtw_pitch_match_recall_proxy'))}",
        "",
        "## Artifact List",
        "- found files:",
    ]
    lines.extend(f"  - {file_name}" for file_name in found_files)
    lines.append("- missing files:")
    lines.extend(f"  - {file_name}" for file_name in missing_files)
    lines.extend(_derived_diagnostics_markdown_lines(derived_diagnostics))
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(
        [
            "",
            "## Preliminary Diagnosis Placeholders",
            f"- F0_available: {str(f0_available).lower()}",
            f"- vocal_activity_available: {str(vocal_activity_available).lower()}",
            f"- note_candidates_available: {str(note_candidates_available).lower()}",
            f"- predicted_note_density: {_fmt(predicted_density)} notes/sec",
            f"- expected_note_density: {_fmt(expected_density)} notes/sec",
            f"- matched_density: {_fmt(matched_density)} matches/sec",
            f"- possible_failure_stage: {possible_failure_stage}",
            "",
        ]
    )
    return "\n".join(lines)


def build_pitch_debug_markdown(
    *,
    sample_id: str,
    sample_title: str,
    pitch_distribution: dict[str, Any] | None,
) -> str:
    pitch_distribution = pitch_distribution if isinstance(pitch_distribution, dict) else {}
    sources = [
        ("expected", pitch_distribution.get("expected_notes") if isinstance(pitch_distribution.get("expected_notes"), dict) else {}),
        ("predicted", pitch_distribution.get("predicted_notes") if isinstance(pitch_distribution.get("predicted_notes"), dict) else {}),
        ("F0", pitch_distribution.get("f0_frames") if isinstance(pitch_distribution.get("f0_frames"), dict) else {}),
        ("note_candidates_all", pitch_distribution.get("note_candidates_all") if isinstance(pitch_distribution.get("note_candidates_all"), dict) else {}),
        ("note_candidates_selected", pitch_distribution.get("note_candidates_selected") if isinstance(pitch_distribution.get("note_candidates_selected"), dict) else {}),
        ("note_candidates_melody_raw", pitch_distribution.get("note_candidates_melody_raw") if isinstance(pitch_distribution.get("note_candidates_melody_raw"), dict) else {}),
    ]
    pairwise = pitch_distribution.get("pairwise") if isinstance(pitch_distribution.get("pairwise"), dict) else {}
    candidate_funnel = pitch_distribution.get("candidate_funnel") if isinstance(pitch_distribution.get("candidate_funnel"), dict) else {}
    flags = pitch_distribution.get("flags") if isinstance(pitch_distribution.get("flags"), dict) else {}
    triggered = [(name, flag) for name, flag in flags.items() if isinstance(flag, dict) and flag.get("triggered")]
    non_triggered = [name for name, flag in flags.items() if isinstance(flag, dict) and not flag.get("triggered")]
    warnings = pitch_distribution.get("warnings") if isinstance(pitch_distribution.get("warnings"), list) else []

    lines = [
        f"# Pitch Distribution Debug: {sample_title or sample_id}",
        "",
        "## Scope",
        "- diagnostic_only: true",
        "- no pitch shift or octave correction applied to produced MIDI",
        "- raw metrics and shift metrics are unchanged",
        "",
        "## Source Summary",
        "| source | available | events | duration_sec | median | p05-p95 | min-max | top bins |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for name, source in sources:
        if name.startswith("note_candidates_") and not source.get("available") and name != "note_candidates_all":
            continue
        pitch_range = source.get("pitch_range") if isinstance(source.get("pitch_range"), dict) else {}
        lines.append(
            "| {source} | {available} | {events} | {duration} | {median} | {robust} | {minmax} | {top} |".format(
                source=name,
                available=str(bool(source.get("available"))).lower(),
                events=_fmt(source.get("event_count")),
                duration=_fmt(source.get("duration_sec")),
                median=_pitch_label(source.get("median_pitch")),
                robust=f"{_pitch_label(pitch_range.get('p05'))}-{_pitch_label(pitch_range.get('p95'))}",
                minmax=f"{_pitch_label(pitch_range.get('min'))}-{_pitch_label(pitch_range.get('max'))}",
                top=_top_bins_text(source),
            )
        )

    lines.extend(
        [
            "",
            "## Pairwise Pitch Overlap",
            "| pair | raw_overlap | range_iou | median_delta | best_shift | shifted_overlap | gain |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, pair in pairwise.items():
        if not isinstance(pair, dict):
            continue
        lines.append(
            "| {pair} | {raw} | {range_iou} | {delta} | {shift} | {shifted} | {gain} |".format(
                pair=name,
                raw=_fmt(pair.get("raw_histogram_overlap")),
                range_iou=_fmt(pair.get("range_iou")),
                delta=_fmt(pair.get("median_delta_b_minus_a_semitones")),
                shift=_fmt(pair.get("best_octave_shift")),
                shifted=_fmt(pair.get("best_octave_shifted_overlap")),
                gain=_fmt(pair.get("octave_shift_overlap_gain")),
            )
        )

    lines.extend(
        [
            "",
            "## Candidate Funnel",
            f"- F0 voiced duration: {_fmt(candidate_funnel.get('f0_voiced_duration_sec'))}",
            f"- note_candidates_all count / duration: {_fmt(candidate_funnel.get('note_candidates_all_count'))} / {_fmt(candidate_funnel.get('note_candidates_all_duration_sec'))}",
            f"- note_candidates_selected count / duration: {_fmt(candidate_funnel.get('note_candidates_selected_count'))} / {_fmt(candidate_funnel.get('note_candidates_selected_duration_sec'))}",
            f"- predicted MIDI count / duration: {_fmt(candidate_funnel.get('predicted_midi_count'))} / {_fmt(candidate_funnel.get('predicted_midi_duration_sec'))}",
            f"- selected_to_all_count_ratio: {_fmt(candidate_funnel.get('selected_to_all_count_ratio'))}",
            f"- predicted_to_candidate_count_ratio: {_fmt(candidate_funnel.get('predicted_to_candidate_count_ratio'))}",
            "",
            "## Triggered Flags",
        ]
    )
    if triggered:
        for name, flag in triggered:
            lines.extend(
                [
                    f"### {name}",
                    f"- confidence: {_fmt(flag.get('confidence'))}",
                    f"- subtype: {_fmt(flag.get('subtype'))}",
                    "- evidence:",
                ]
            )
            lines.extend(f"  - {item}" for item in flag.get("evidence") or [])
            lines.append(f"- interpretation: {_pitch_flag_interpretation(name, flag)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Non-triggered Flags"])
    lines.extend(f"- {name}" for name in non_triggered)
    if not non_triggered:
        lines.append("- none")
    lines.extend(["", "## Warnings"])
    lines.extend(f"- {warning}" for warning in warnings if warning)
    if not warnings:
        lines.append("- none")
    return "\n".join(lines)


def build_rhythm_debug(
    *,
    rhythm_grid_path: Path | None,
    predicted_notes: list[NoteEvent] | None = None,
) -> dict[str, Any]:
    if rhythm_grid_path is None or not rhythm_grid_path.exists():
        return _unavailable("rhythm_grid.json missing")
    payload = _read_json(rhythm_grid_path)
    if not isinstance(payload, dict):
        return _unavailable("rhythm grid unavailable")

    beat_times = _float_list(payload.get("beat_times"))
    downbeat_times = _float_list(payload.get("downbeat_times"))
    analysis_info = payload.get("analysis_info") if isinstance(payload.get("analysis_info"), dict) else {}
    gaps = _positive_diffs(beat_times)
    tempo_bpm = _rhythm_tempo_bpm(payload, gaps)
    tempo_stability = _tempo_stability(payload, gaps)
    beat_gap_mean = _mean(gaps)
    beat_gap_p95 = _percentile(gaps, 95.0)
    beat_gap_max = max(gaps) if gaps else None
    downbeat_confidence = _first_float(
        analysis_info.get("downbeat_confidence"),
        payload.get("downbeat_confidence"),
    )
    if downbeat_confidence is None:
        downbeat_confidence = 0.0 if not downbeat_times else None
    bar_phase_confidence = _bar_phase_confidence(
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        beats_per_bar=max(2, _as_int(payload.get("beats_per_bar")) or 4),
        downbeat_confidence=downbeat_confidence,
    )
    off_grid = _off_grid_onsets(predicted_notes or [], beat_times, beat_gap_mean)
    pickup_likelihood = _pickup_likelihood(predicted_notes or [], beat_times, downbeat_times, beat_gap_mean)
    rubato_likelihood = _rubato_likelihood(gaps)
    uncertain_regions = _grid_uncertain_regions(
        beat_times=beat_times,
        beat_gap_mean=beat_gap_mean,
        beat_gap_p95=beat_gap_p95,
        downbeat_confidence=downbeat_confidence,
        bar_phase_confidence=bar_phase_confidence,
        off_grid_onsets=off_grid["onsets"],
    )
    diagnosis = _rhythm_preliminary_diagnosis(
        tempo_stability=tempo_stability,
        downbeat_confidence=downbeat_confidence,
        bar_phase_confidence=bar_phase_confidence,
        off_grid_onset_ratio=off_grid["ratio"],
        pickup_likelihood=pickup_likelihood,
        rubato_likelihood=rubato_likelihood,
    )
    flags = _rhythm_flags(
        diagnosis=diagnosis,
        tempo_stability=tempo_stability,
        downbeat_confidence=downbeat_confidence,
        bar_phase_confidence=bar_phase_confidence,
        off_grid_onset_ratio=off_grid["ratio"],
        pickup_likelihood=pickup_likelihood,
        rubato_likelihood=rubato_likelihood,
    )
    return {
        "available": True,
        "diagnostic_only": True,
        "tempo_bpm": _round_optional(tempo_bpm),
        "tempo_stability": _round_optional(tempo_stability),
        "beat_count": len(beat_times),
        "beat_gap_mean_sec": _round_optional(beat_gap_mean),
        "beat_gap_p95_sec": _round_optional(beat_gap_p95),
        "beat_gap_max_sec": _round_optional(beat_gap_max),
        "downbeat_count": len(downbeat_times),
        "downbeat_confidence": _round_optional(downbeat_confidence),
        "bar_phase_confidence": _round_optional(bar_phase_confidence),
        "off_grid_onset_ratio": _round_optional(off_grid["ratio"]),
        "pickup_likelihood": _round_optional(pickup_likelihood),
        "rubato_likelihood": _round_optional(rubato_likelihood),
        "grid_uncertain_region_count": len(uncertain_regions),
        "grid_uncertain_regions": uncertain_regions,
        "preliminary_rhythm_diagnosis": diagnosis,
        "rhythm_flags": flags,
        "off_grid_predicted_note_onsets": off_grid["onsets"][:50],
    }


def build_rhythm_debug_markdown(*, sample_id: str, sample_title: str, rhythm_debug: dict[str, Any] | None) -> str:
    rhythm_debug = rhythm_debug if isinstance(rhythm_debug, dict) else _unavailable("rhythm debug unavailable")
    regions = rhythm_debug.get("grid_uncertain_regions") if isinstance(rhythm_debug.get("grid_uncertain_regions"), list) else []
    flags = rhythm_debug.get("rhythm_flags") if isinstance(rhythm_debug.get("rhythm_flags"), list) else []
    lines = [
        f"# RhythmGrid Debug: {sample_title or sample_id}",
        "",
        "## Scope",
        "- diagnostic_only: true",
        "- quantizer behavior unchanged",
        "- benchmark status semantics unchanged",
        "",
        "## Rhythm Diagnostics",
        f"- available: {str(bool(rhythm_debug.get('available'))).lower()}",
        f"- tempo_bpm: {_fmt(rhythm_debug.get('tempo_bpm'))}",
        f"- tempo_stability: {_fmt(rhythm_debug.get('tempo_stability'))}",
        f"- beat_count: {_fmt(rhythm_debug.get('beat_count'))}",
        f"- beat_gap_mean_sec: {_fmt(rhythm_debug.get('beat_gap_mean_sec'))}",
        f"- beat_gap_p95_sec: {_fmt(rhythm_debug.get('beat_gap_p95_sec'))}",
        f"- beat_gap_max_sec: {_fmt(rhythm_debug.get('beat_gap_max_sec'))}",
        f"- downbeat_count: {_fmt(rhythm_debug.get('downbeat_count'))}",
        f"- downbeat_confidence: {_fmt(rhythm_debug.get('downbeat_confidence'))}",
        f"- bar_phase_confidence: {_fmt(rhythm_debug.get('bar_phase_confidence'))}",
        f"- off_grid_onset_ratio: {_fmt(rhythm_debug.get('off_grid_onset_ratio'))}",
        f"- pickup_likelihood: {_fmt(rhythm_debug.get('pickup_likelihood'))}",
        f"- rubato_likelihood: {_fmt(rhythm_debug.get('rubato_likelihood'))}",
        f"- grid_uncertain_region_count: {_fmt(rhythm_debug.get('grid_uncertain_region_count'))}",
        f"- preliminary_rhythm_diagnosis: {_fmt(rhythm_debug.get('preliminary_rhythm_diagnosis'))}",
        f"- rhythm_flags: {', '.join(str(flag) for flag in flags) if flags else 'none'}",
        f"- unavailable_reason: {_fmt(rhythm_debug.get('unavailable_reason')) if not rhythm_debug.get('available') else 'none'}",
        "",
        "## Grid Uncertain Regions",
    ]
    if regions:
        lines.extend(
            f"- {region.get('reason', 'unknown')}: {_fmt(region.get('start_sec'))}s - {_fmt(region.get('end_sec'))}s confidence={_fmt(region.get('confidence'))}"
            for region in regions[:25]
            if isinstance(region, dict)
        )
    else:
        lines.append("- none")
    return "\n".join(lines)


def build_rhythm_grid_candidates(
    *,
    rhythm_grid_path: Path | None,
    predicted_notes: list[NoteEvent] | None = None,
) -> dict[str, Any]:
    if rhythm_grid_path is None or not rhythm_grid_path.exists():
        return _unavailable("rhythm_grid.json missing")
    payload = _read_json(rhythm_grid_path)
    if not isinstance(payload, dict):
        return _unavailable("rhythm grid unavailable")
    beat_times = _float_list(payload.get("beat_times"))
    downbeat_times = _float_list(payload.get("downbeat_times"))
    if len(beat_times) < 2:
        unavailable = _unavailable("rhythm grid has fewer than 2 beats")
        unavailable["diagnostic_only"] = True
        return unavailable

    beats_per_bar = max(2, _as_int(payload.get("beats_per_bar")) or 4)
    analysis_info = payload.get("analysis_info") if isinstance(payload.get("analysis_info"), dict) else {}
    downbeat_confidence = _first_float(analysis_info.get("downbeat_confidence"), payload.get("downbeat_confidence"))
    if downbeat_confidence is None:
        downbeat_confidence = 0.0 if not downbeat_times else None
    base_tempo = _rhythm_tempo_bpm(payload, _positive_diffs(beat_times))
    candidates: list[dict[str, Any]] = []

    def add_candidate(candidate_id: str, source: str, candidate_beats: list[float], candidate_downbeats: list[float], tempo_bpm: float | None, warnings: list[str] | None = None) -> None:
        if any(candidate["candidate_id"] == candidate_id for candidate in candidates):
            return
        candidates.append(
            _build_rhythm_grid_candidate(
                candidate_id=candidate_id,
                source=source,
                beat_times=candidate_beats,
                downbeat_times=candidate_downbeats,
                tempo_bpm=tempo_bpm,
                beats_per_bar=beats_per_bar,
                downbeat_confidence=downbeat_confidence,
                predicted_notes=predicted_notes or [],
                warnings=warnings or [],
            )
        )

    add_candidate("current_grid", "current_rhythm_grid", beat_times, downbeat_times, base_tempo)
    half_beats = beat_times[::2]
    add_candidate("half_tempo_grid", "derived_from_current_every_other_beat", half_beats, _phase_downbeats(half_beats, beats_per_bar, 0), (base_tempo / 2.0) if base_tempo else None)
    double_beats = _double_tempo_beats(beat_times)
    add_candidate("double_tempo_grid", "derived_from_current_midpoint_beats", double_beats, _phase_downbeats(double_beats, beats_per_bar, 0), (base_tempo * 2.0) if base_tempo else None)
    for phase in range(4):
        add_candidate(
            f"downbeat_phase_shift_{phase}",
            "derived_from_current_downbeat_phase",
            beat_times,
            _phase_downbeats(beat_times, beats_per_bar, phase),
            base_tempo,
        )

    ioi_bpm = _first_float(analysis_info.get("ioi_median_bpm"), analysis_info.get("ioi_bpm"), payload.get("ioi_bpm"))
    if ioi_bpm is not None and ioi_bpm > 0 and base_tempo is not None and abs(ioi_bpm - base_tempo) > 0.5:
        add_candidate("ioi_median_grid", "beat_tracker_ioi_bpm_diagnostic", beat_times, downbeat_times, ioi_bpm, ["uses IOI BPM metadata only; beat positions unchanged"])
    raw_bpm = _first_float(analysis_info.get("raw_bpm"), analysis_info.get("raw_beat_tracker_bpm"), payload.get("raw_bpm"))
    if raw_bpm is not None and raw_bpm > 0 and base_tempo is not None and abs(raw_bpm - base_tempo) > 0.5:
        add_candidate("raw_beat_tracker_grid", "beat_tracker_raw_bpm_diagnostic", beat_times, downbeat_times, raw_bpm, ["uses raw beat tracker BPM metadata only; beat positions unchanged"])

    ranked = sorted(candidates, key=lambda candidate: candidate.get("candidate_score") or 0.0, reverse=True)
    rank_by_id = {candidate["candidate_id"]: index + 1 for index, candidate in enumerate(ranked)}
    for candidate in candidates:
        candidate["rank"] = rank_by_id.get(candidate["candidate_id"])
    best = ranked[0] if ranked else None
    current = next((candidate for candidate in candidates if candidate["candidate_id"] == "current_grid"), None)
    current_score = _as_float(current.get("candidate_score")) if current else None
    best_score = _as_float(best.get("candidate_score")) if best else None
    score_delta = None if current_score is None or best_score is None else max(0.0, best_score - current_score)
    return {
        "available": True,
        "diagnostic_only": True,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "best_diagnostic_candidate_id": best.get("candidate_id") if best else None,
        "current_candidate_rank": rank_by_id.get("current_grid"),
        "current_vs_best_score_delta": _round_optional(score_delta),
        "rhythm_candidate_warning": _rhythm_candidate_warning(current=current, best=best, score_delta=score_delta),
    }


def build_rhythm_grid_candidates_markdown(*, sample_id: str, sample_title: str, rhythm_candidates: dict[str, Any] | None) -> str:
    rhythm_candidates = rhythm_candidates if isinstance(rhythm_candidates, dict) else _unavailable("rhythm grid candidates unavailable")
    candidates = rhythm_candidates.get("candidates") if isinstance(rhythm_candidates.get("candidates"), list) else []
    warning = rhythm_candidates.get("rhythm_candidate_warning")
    lines = [
        f"# RhythmGrid Candidate Diagnostics: {sample_title or sample_id}",
        "",
        "## Scope",
        "- diagnostic_only: true",
        "- candidate scoring does not affect ScoreRevision",
        "- quantizer behavior unchanged",
        "- benchmark status semantics unchanged",
        "",
        "## Current Grid vs Best Diagnostic Grid",
        f"- best_diagnostic_candidate_id: {_fmt(rhythm_candidates.get('best_diagnostic_candidate_id'))}",
        f"- current_candidate_rank: {_fmt(rhythm_candidates.get('current_candidate_rank'))}",
        f"- current_vs_best_score_delta: {_fmt(rhythm_candidates.get('current_vs_best_score_delta'))}",
        f"- rhythm_candidate_warning: {_fmt(warning) if warning else 'none'}",
        "",
        "## Candidate Comparison",
        "| rank | candidate_id | source | tempo_bpm | beats | downbeats | stability | bar_phase | off_grid | score | warnings |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for candidate in sorted(candidates, key=lambda item: item.get("rank") or 9999):
        warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        lines.append(
            "| {rank} | {candidate_id} | {source} | {tempo} | {beats} | {downbeats} | {stability} | {bar_phase} | {off_grid} | {score} | {warnings} |".format(
                rank=_fmt(candidate.get("rank")),
                candidate_id=candidate.get("candidate_id"),
                source=candidate.get("source"),
                tempo=_fmt(candidate.get("tempo_bpm")),
                beats=_fmt(candidate.get("beat_count")),
                downbeats=_fmt(candidate.get("downbeat_count")),
                stability=_fmt(candidate.get("tempo_stability")),
                bar_phase=_fmt(candidate.get("bar_phase_confidence")),
                off_grid=_fmt(candidate.get("off_grid_onset_ratio")),
                score=_fmt(candidate.get("candidate_score")),
                warnings="; ".join(str(item) for item in warnings) if warnings else "none",
            )
        )
    suspicion = _candidate_suspicion_summary(candidates, rhythm_candidates)
    lines.extend(
        [
            "",
            "## Suspicion Summary",
            f"- possible half/double tempo suspicion: {suspicion['tempo']}",
            f"- possible downbeat phase issue: {suspicion['phase']}",
            f"- possible pickup issue: {suspicion['pickup']}",
        ]
    )
    return "\n".join(lines)


def _enrich_rhythm_grid_debug_copy(rhythm_grid_path: Path, rhythm_debug: dict[str, Any]) -> None:
    if not rhythm_grid_path.exists() or not rhythm_debug.get("available"):
        return
    payload = _read_json(rhythm_grid_path)
    if not isinstance(payload, dict):
        return
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    diagnostics.update(
        {
            "diagnostic_only": True,
            "tempo_stability": rhythm_debug.get("tempo_stability"),
            "beat_gap_mean_sec": rhythm_debug.get("beat_gap_mean_sec"),
            "beat_gap_p95_sec": rhythm_debug.get("beat_gap_p95_sec"),
            "beat_gap_max_sec": rhythm_debug.get("beat_gap_max_sec"),
            "bar_phase_confidence": rhythm_debug.get("bar_phase_confidence"),
            "off_grid_onset_ratio": rhythm_debug.get("off_grid_onset_ratio"),
            "pickup_likelihood": rhythm_debug.get("pickup_likelihood"),
            "rubato_likelihood": rhythm_debug.get("rubato_likelihood"),
            "grid_uncertain_region_count": rhythm_debug.get("grid_uncertain_region_count"),
            "preliminary_rhythm_diagnosis": rhythm_debug.get("preliminary_rhythm_diagnosis"),
            "rhythm_flags": rhythm_debug.get("rhythm_flags"),
        }
    )
    payload["diagnostics"] = diagnostics
    _write_json(rhythm_grid_path, payload)


def _build_rhythm_grid_candidate(
    *,
    candidate_id: str,
    source: str,
    beat_times: list[float],
    downbeat_times: list[float],
    tempo_bpm: float | None,
    beats_per_bar: int,
    downbeat_confidence: float | None,
    predicted_notes: list[NoteEvent],
    warnings: list[str],
) -> dict[str, Any]:
    beat_times = sorted(set(float(value) for value in beat_times))
    downbeat_times = sorted(set(float(value) for value in downbeat_times))
    gaps = _positive_diffs(beat_times)
    beat_gap_mean = _mean(gaps)
    beat_gap_p95 = _percentile(gaps, 95.0)
    beat_gap_max = max(gaps) if gaps else None
    stability_payload = {"tempo_bpm": tempo_bpm} if tempo_bpm is not None else {}
    tempo_stability = _tempo_stability(stability_payload, gaps)
    if tempo_stability is None:
        tempo_stability = 0.0
    bar_phase_confidence = _bar_phase_confidence(
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        beats_per_bar=beats_per_bar,
        downbeat_confidence=downbeat_confidence,
    )
    off_grid = _off_grid_onsets(predicted_notes, beat_times, beat_gap_mean)
    pickup_likelihood = _pickup_likelihood(predicted_notes, beat_times, downbeat_times, beat_gap_mean)
    rubato_likelihood = _rubato_likelihood(gaps)
    uncertain_regions = _grid_uncertain_regions(
        beat_times=beat_times,
        beat_gap_mean=beat_gap_mean,
        beat_gap_p95=beat_gap_p95,
        downbeat_confidence=downbeat_confidence,
        bar_phase_confidence=bar_phase_confidence,
        off_grid_onsets=off_grid["onsets"],
    )
    score_breakdown = _rhythm_candidate_score_breakdown(
        tempo_stability=tempo_stability,
        beat_gap_p95=beat_gap_p95,
        beat_gap_mean=beat_gap_mean,
        bar_phase_confidence=bar_phase_confidence,
        off_grid_onset_ratio=off_grid["ratio"],
        downbeat_confidence=downbeat_confidence,
    )
    candidate_warnings = list(warnings)
    if len(beat_times) < 2:
        candidate_warnings.append("candidate has fewer than 2 beats")
    if not downbeat_times:
        candidate_warnings.append("candidate has no downbeats")
    return {
        "candidate_id": candidate_id,
        "source": source,
        "diagnostic_only": True,
        "tempo_bpm": _round_optional(tempo_bpm),
        "beat_count": len(beat_times),
        "downbeat_count": len(downbeat_times),
        "beat_gap_mean_sec": _round_optional(beat_gap_mean),
        "beat_gap_p95_sec": _round_optional(beat_gap_p95),
        "beat_gap_max_sec": _round_optional(beat_gap_max),
        "tempo_stability": _round_optional(tempo_stability),
        "downbeat_confidence": _round_optional(downbeat_confidence),
        "bar_phase_confidence": _round_optional(bar_phase_confidence),
        "off_grid_onset_ratio": _round_optional(off_grid["ratio"]),
        "pickup_likelihood": _round_optional(pickup_likelihood),
        "rubato_likelihood": _round_optional(rubato_likelihood),
        "uncertain_region_count": len(uncertain_regions),
        "candidate_score": _round_optional(score_breakdown["total"]),
        "score_breakdown": score_breakdown,
        "warnings": candidate_warnings,
    }


def _rhythm_candidate_score_breakdown(
    *,
    tempo_stability: float | None,
    beat_gap_p95: float | None,
    beat_gap_mean: float | None,
    bar_phase_confidence: float | None,
    off_grid_onset_ratio: float | None,
    downbeat_confidence: float | None,
) -> dict[str, float]:
    tempo_component = _clamp01(tempo_stability)
    if beat_gap_p95 is None or beat_gap_mean is None or beat_gap_mean <= 0:
        beat_gap_component = 0.0
    else:
        beat_gap_component = _clamp01(1.0 - max(0.0, beat_gap_p95 - beat_gap_mean) / max(beat_gap_mean, 1e-6))
    bar_phase_component = _clamp01(bar_phase_confidence)
    off_grid_component = 0.0 if off_grid_onset_ratio is None else _clamp01(1.0 - off_grid_onset_ratio)
    downbeat_component = _clamp01(downbeat_confidence)
    total = (
        0.30 * tempo_component
        + 0.20 * beat_gap_component
        + 0.20 * bar_phase_component
        + 0.20 * off_grid_component
        + 0.10 * downbeat_component
    )
    return {
        "tempo_stability": _round_float(tempo_component),
        "beat_gap_p95": _round_float(beat_gap_component),
        "bar_phase_confidence": _round_float(bar_phase_component),
        "off_grid_onset_ratio": _round_float(off_grid_component),
        "downbeat_confidence": _round_float(downbeat_component),
        "total": _round_float(total),
    }


def _double_tempo_beats(beat_times: list[float]) -> list[float]:
    if len(beat_times) < 2:
        return list(beat_times)
    doubled: list[float] = []
    for index in range(1, len(beat_times)):
        previous = beat_times[index - 1]
        current = beat_times[index]
        if not doubled:
            doubled.append(previous)
        midpoint = previous + (current - previous) / 2.0
        doubled.extend([midpoint, current])
    return sorted(set(_round_float(value) for value in doubled))


def _phase_downbeats(beat_times: list[float], beats_per_bar: int, phase: int) -> list[float]:
    if not beat_times:
        return []
    return [float(value) for index, value in enumerate(beat_times) if index % max(2, beats_per_bar) == phase % max(2, beats_per_bar)]


def _rhythm_candidate_warning(current: dict[str, Any] | None, best: dict[str, Any] | None, score_delta: float | None) -> str | None:
    if not current or not best or best.get("candidate_id") == "current_grid" or score_delta is None:
        return None
    if score_delta < 0.12:
        return None
    best_id = str(best.get("candidate_id"))
    if best_id in {"half_tempo_grid", "double_tempo_grid"}:
        return "possible_half_or_double_tempo_grid"
    if best_id.startswith("downbeat_phase_shift_"):
        return "possible_downbeat_phase_issue"
    return "diagnostic_candidate_scores_much_better_than_current_grid"


def _candidate_suspicion_summary(candidates: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, str]:
    by_id = {str(candidate.get("candidate_id")): candidate for candidate in candidates if isinstance(candidate, dict)}
    current_score = _as_float(by_id.get("current_grid", {}).get("candidate_score"))
    best_id = payload.get("best_diagnostic_candidate_id")
    tempo = "none"
    for candidate_id in ("half_tempo_grid", "double_tempo_grid"):
        score = _as_float(by_id.get(candidate_id, {}).get("candidate_score"))
        if current_score is not None and score is not None and score - current_score >= 0.12:
            tempo = candidate_id
            break
    phase = "none"
    if isinstance(best_id, str) and best_id.startswith("downbeat_phase_shift_") and best_id != "downbeat_phase_shift_0":
        phase = best_id
    pickup = "possible" if any((_as_float(candidate.get("pickup_likelihood")) or 0.0) >= 0.7 for candidate in candidates) else "none"
    return {"tempo": tempo, "phase": phase, "pickup": pickup}


def _clamp01(value: Any) -> float:
    number = _as_float(value)
    if number is None:
        return 0.0
    return max(0.0, min(1.0, number))


def _pitch_label(value: Any) -> str:
    pitch = _as_float(value)
    if pitch is None:
        return "missing"
    rounded = int(round(pitch))
    return f"{_midi_pitch_name(rounded)} / {_fmt(pitch)}"


def _top_bins_text(source: dict[str, Any]) -> str:
    histogram = source.get("histogram") if isinstance(source.get("histogram"), dict) else {}
    top_bins = histogram.get("top_bins") if isinstance(histogram.get("top_bins"), list) else []
    values: list[str] = []
    for item in top_bins[:4]:
        if not isinstance(item, dict):
            continue
        pitch = _as_int(item.get("midi_pitch"))
        label = item.get("pitch_name") or (_midi_pitch_name(pitch) if pitch is not None else "?")
        values.append(f"{label} {_fmt(item.get('weight_ratio'))}")
    return ", ".join(values) if values else "missing"


def _pitch_flag_interpretation(name: str, flag: dict[str, Any]) -> str:
    subtype = str(flag.get("subtype") or "")
    if name == "possible_f0_octave_or_reference_pitch_mismatch":
        if subtype == "ambiguous_octave_or_reference":
            return "F0, candidates, or predicted notes may agree with each other while the reference sits an octave-like distance away."
        return "Expected and F0 pitch distributions improve under diagnostic-only octave shift."
    if name == "possible_f0_to_note_candidate_loss":
        return "F0 pitch evidence is present, but note candidates appear missing or pitch-distribution-disconnected."
    if name == "possible_melody_selector_or_filter_loss":
        return "Candidate pitches survive, but selected or exported predicted notes lose too much of that distribution."
    if name == "possible_reference_strategy_or_pitch_source_mismatch":
        return "Expected reference pitches disagree with the internally consistent F0/candidate/predicted pitch source."
    return "Review pitch-distribution evidence manually."


def _find_sample(samples: list[BenchmarkSample], sample_id: str) -> BenchmarkSample:
    for sample in samples:
        if sample.id == sample_id:
            return sample
    raise ValueError(f"sample_id not found in manifest: {sample_id}")


def _load_manifest_sample_metadata(manifest_path: Path, sample_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if not isinstance(samples, list):
        return {}
    for sample in samples:
        if isinstance(sample, dict) and sample.get("id") == sample_id:
            return sample
    return {}


def _load_summary_row(run_root: Path, sample_id: str) -> dict[str, Any] | None:
    summary = _read_json(run_root / "summary.json")
    if not isinstance(summary, dict):
        return None
    for row in summary.get("results") or []:
        if isinstance(row, dict) and row.get("sample_id") == sample_id:
            return row
    return None


def _read_json(path: Path) -> Any | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and source.resolve(strict=False) == destination.resolve(strict=False):
        return
    shutil.copy2(source, destination)


def _copy_artifact_candidates(
    *,
    artifacts_payload: dict[str, Any],
    workspace_path: Path | None,
    sample_run_dir: Path,
) -> dict[str, list[Any]]:
    stem_paths = artifacts_payload.get("stem_paths") if isinstance(artifacts_payload.get("stem_paths"), dict) else {}
    return {
        "vocals.wav": [
            artifacts_payload.get("vocals_path"),
            stem_paths.get("vocals"),
            workspace_path / "separation" / "vocals.wav" if workspace_path else None,
        ],
        "f0_track.json": [
            sample_run_dir / "f0_track.json",
            workspace_path / "pitch" / "f0_track.json" if workspace_path else None,
        ],
        "pitch_contours.json": [
            sample_run_dir / "pitch_contours.json",
            workspace_path / "pitch" / "pitch_contours.json" if workspace_path else None,
        ],
        "vocal_activity.json": [
            sample_run_dir / "vocal_activity.json",
            workspace_path / "pitch" / "vocal_activity.json" if workspace_path else None,
        ],
        "note_candidates.json": [
            sample_run_dir / "note_candidates.json",
            workspace_path / "pitch" / "note_candidates.json" if workspace_path else None,
        ],
        "rhythm_grid.json": [
            sample_run_dir / "rhythm_grid.json",
            workspace_path / "pitch" / "rhythm_grid.json" if workspace_path else None,
            workspace_path / "rhythm" / "rhythm_grid.json" if workspace_path else None,
            workspace_path / "quantization" / "rhythm_grid.json" if workspace_path else None,
        ],
        "selected_melody.json": [
            sample_run_dir / "selected_melody.json",
            workspace_path / "pitch" / "selected_melody.json" if workspace_path else None,
        ],
        "quantized_notes.json": [
            sample_run_dir / "quantized_notes.json",
            workspace_path / "pitch" / "quantized_notes.json" if workspace_path else None,
            workspace_path / "quantization" / "quantized_notes.json" if workspace_path else None,
            workspace_path / "score" / "quantized_notes.json" if workspace_path else None,
        ],
        "score_ir.json": [
            sample_run_dir / "score_ir.json",
            workspace_path / "score" / "score_ir.json" if workspace_path else None,
        ],
        "mdx_diagnostics.json": [
            sample_run_dir / "mdx_diagnostics.json",
            workspace_path / "separation" / "mdx_diagnostics.json" if workspace_path else None,
        ],
    }


def _resolve_workspace_path(
    *,
    artifacts_payload: dict[str, Any],
    stage_payload: dict[str, Any],
    run_root: Path,
    sample_run_dir: Path,
    manifest_root: Path,
) -> Path | None:
    return _first_existing_path(
        [artifacts_payload.get("workspace_path"), stage_payload.get("workspace_path")],
        run_root=run_root,
        sample_run_dir=sample_run_dir,
        manifest_root=manifest_root,
    )


def _first_existing_path(
    values: list[Any],
    *,
    run_root: Path,
    sample_run_dir: Path,
    manifest_root: Path,
) -> Path | None:
    for value in values:
        resolved = _resolve_existing_path(value, run_root=run_root, sample_run_dir=sample_run_dir, manifest_root=manifest_root)
        if resolved is not None:
            return resolved
    return None


def _resolve_existing_path(value: Any, *, run_root: Path, sample_run_dir: Path, manifest_root: Path) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(
            [
                Path.cwd() / path,
                run_root / path,
                sample_run_dir / path,
                run_root.parent / path,
                run_root.parent.parent / path,
                manifest_root / path,
            ]
        )
        reconstructed = _reconstruct_under_run_root(path, run_root)
        if reconstructed is not None:
            candidates.insert(0, reconstructed)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve(strict=False)
    return None


def _reconstruct_under_run_root(path: Path, run_root: Path) -> Path | None:
    parts = list(path.parts)
    if run_root.name not in parts:
        return None
    index = parts.index(run_root.name)
    suffix = parts[index + 1 :]
    return run_root.joinpath(*suffix) if suffix else run_root


def _predicted_lead_track(metrics_payload: dict[str, Any], produced_midi_path: Path) -> int | None:
    track = metrics_payload.get("predicted_lead_track")
    if track is not None:
        try:
            return int(track)
        except Exception:
            pass
    lead_track = find_midi_track_index_by_name(produced_midi_path, "Lead Vocal")
    if lead_track is not None:
        return lead_track
    tracks = read_midi_track_info(produced_midi_path)
    return next((track_info.index for track_info in tracks if track_info.note_count > 0), None)


def _computed_metrics_payload(
    *,
    sample: BenchmarkSample,
    produced_midi_path: Path,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    reference_strategy: str,
    reference_extraction_payload: dict[str, Any] | None,
    predicted_lead_track: int | None,
    metric_config: MidiMetricConfig,
) -> dict[str, Any]:
    metrics = compute_midi_metrics(expected_notes, predicted_notes, config=metric_config)
    audibility = compute_midi_audibility_metrics(expected_notes, predicted_notes)
    continuity = compute_midi_continuity_metrics(predicted_notes)
    alignment = compute_midi_alignment_diagnostics(expected_notes, predicted_notes, config=metric_config)
    return {
        "sample_id": sample.id,
        "expected_midi": str(sample.expected_midi),
        "expected_melody_track": sample.expected_melody_track,
        "expected_reference_strategy": reference_strategy,
        "expected_reference_extraction": reference_extraction_payload or {},
        "produced_midi": str(produced_midi_path),
        "predicted_lead_track": predicted_lead_track,
        "config": asdict(metric_config),
        "metrics": metrics.to_dict(),
        "audibility": audibility.to_dict(),
        "continuity": continuity.to_dict(),
        "alignment": alignment.to_dict(),
    }


def _notes_to_debug_dicts(notes: list[NoteEvent], *, prefix: str) -> list[dict[str, Any]]:
    return [_note_to_debug_dict(note, f"{prefix}_{index:05d}") for index, note in enumerate(notes)]


def _note_to_debug_dict(note: NoteEvent, note_id: str) -> dict[str, Any]:
    return {
        "id": note_id,
        "onset_sec": round(float(note.start), 6),
        "offset_sec": round(float(note.end), 6),
        "duration_sec": round(float(note.duration), 6),
        "pitch": int(note.pitch),
        "midi_pitch": int(note.pitch),
        "pitch_name": _midi_pitch_name(int(note.pitch)),
        "velocity": int(note.velocity),
        "track_index": note.track_index,
        "channel": note.channel,
        "program": note.program,
    }


def _midi_pitch_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = int(pitch) // 12 - 1
    return f"{names[int(pitch) % 12]}{octave}"


def _derive_note_diagnostics(expected_notes: list[NoteEvent], predicted_notes: list[NoteEvent]) -> dict[str, Any]:
    expected_stats = _note_collection_stats(expected_notes)
    predicted_stats = _note_collection_stats(predicted_notes)
    predicted_continuity = compute_midi_continuity_metrics(predicted_notes).to_dict()
    expected_span = expected_stats["time_span_sec"]
    predicted_span = predicted_stats["time_span_sec"]
    expected_median_pitch = expected_stats["median_pitch"]
    predicted_median_pitch = predicted_stats["median_pitch"]
    median_pitch_delta = None
    if expected_median_pitch is not None and predicted_median_pitch is not None:
        median_pitch_delta = predicted_median_pitch - expected_median_pitch
    return {
        "available": bool(expected_notes or predicted_notes),
        "expected_note_count": len(expected_notes),
        "predicted_note_count": len(predicted_notes),
        "expected_notes_per_second": _safe_divide(len(expected_notes), expected_span),
        "predicted_notes_per_second": _safe_divide(len(predicted_notes), predicted_span),
        "expected_median_duration_sec": expected_stats["median_duration_sec"],
        "predicted_median_duration_sec": predicted_stats["median_duration_sec"],
        "expected_short_note_ratio": expected_stats["short_note_ratio"],
        "predicted_short_note_ratio": predicted_stats["short_note_ratio"],
        "pred_exp_note_count_ratio": _safe_divide(len(predicted_notes), len(expected_notes)),
        "expected_time_span_sec": expected_span,
        "predicted_time_span_sec": predicted_span,
        "expected_predicted_time_overlap_ratio": _time_overlap_ratio(
            expected_stats["start_sec"],
            expected_stats["end_sec"],
            predicted_stats["start_sec"],
            predicted_stats["end_sec"],
        ),
        "expected_pitch_range": expected_stats["pitch_range"],
        "predicted_pitch_range": predicted_stats["pitch_range"],
        "pitch_range_overlap_ratio": _pitch_range_overlap_ratio(expected_stats["pitch_range"], predicted_stats["pitch_range"]),
        "expected_median_pitch": expected_median_pitch,
        "predicted_median_pitch": predicted_median_pitch,
        "median_pitch_delta": median_pitch_delta,
        "predicted_gap50_ratio": predicted_continuity["gap50_ratio"],
        "predicted_gap50_count": predicted_continuity["gap50_count"],
        "predicted_big_gap_count": predicted_continuity["big_gap_count"],
        "predicted_big_gap_ratio": predicted_continuity["big_gap_ratio"],
        "predicted_longest_inter_note_gap_sec": predicted_continuity["longest_inter_note_gap_sec"],
        "predicted_mean_inter_note_gap_sec": predicted_continuity["mean_inter_note_gap_sec"],
        "predicted_large_jump_count": predicted_continuity["large_jump_count"],
        "predicted_large_jump_ratio": predicted_continuity["large_jump_ratio"],
        "predicted_max_abs_pitch_jump_semitones": predicted_continuity["max_abs_pitch_jump_semitones"],
    }


def _note_collection_stats(notes: list[NoteEvent]) -> dict[str, Any]:
    starts = [float(note.start) for note in notes]
    ends = [float(note.end) for note in notes]
    durations = [float(note.duration) for note in notes]
    pitches = [int(note.pitch) for note in notes]
    start = min(starts) if starts else None
    end = max(ends) if ends else None
    span = (end - start) if start is not None and end is not None and end >= start else None
    return {
        "start_sec": start,
        "end_sec": end,
        "time_span_sec": span,
        "median_duration_sec": _median(durations),
        "short_note_ratio": _safe_divide(sum(1 for duration in durations if duration < 0.25), len(durations)),
        "pitch_range": [min(pitches), max(pitches)] if pitches else None,
        "median_pitch": _median(pitches),
    }


def _derive_f0_diagnostics(f0_track_path: Path | None) -> dict[str, Any]:
    if f0_track_path is None or not f0_track_path.exists():
        return _unavailable("f0_track.json missing")
    payload = _read_json(f0_track_path)
    frames = payload.get("frames") if isinstance(payload, dict) else payload
    if not isinstance(frames, list):
        return _unavailable("f0 frames unavailable")
    times: list[float] = []
    voiced_pitches: list[float] = []
    confidences: list[float] = []
    voiced_count = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        time_sec = _as_float(_first_present(frame, "time_sec", "time", "t", "timestamp"))
        if time_sec is not None:
            times.append(time_sec)
        confidence = _as_float(_first_present(frame, "confidence", "probability", "prob", "score", "voicing_confidence"))
        if confidence is not None:
            confidences.append(confidence)
        voiced = _frame_is_voiced(frame)
        pitch_midi = _frame_pitch_midi(frame)
        if voiced:
            voiced_count += 1
            if pitch_midi is not None:
                voiced_pitches.append(pitch_midi)
    return {
        "available": True,
        "f0_frame_count": len(frames),
        "f0_voiced_frame_count": voiced_count,
        "f0_voiced_ratio": _safe_divide(voiced_count, len(frames)),
        "f0_median_confidence": _median(confidences),
        "f0_pitch_range": [min(voiced_pitches), max(voiced_pitches)] if voiced_pitches else None,
        "f0_time_span_sec": (max(times) - min(times)) if times else None,
        "f0_voiced_duration_sec": _round_optional(voiced_count * _median(_positive_diffs(sorted(times))) if voiced_count and len(times) >= 2 else None),
    }


def _derive_vocal_activity_diagnostics(vocal_activity_path: Path | None) -> dict[str, Any]:
    if vocal_activity_path is None or not vocal_activity_path.exists():
        return _unavailable("vocal_activity.json missing")
    segments = _load_vocal_activity_segments(vocal_activity_path)
    if not segments:
        return _unavailable("vocal activity segments unavailable")
    start = min(segment[0] for segment in segments)
    end = max(segment[1] for segment in segments)
    span = end - start if end >= start else None
    active_duration = sum(max(0.0, segment[1] - segment[0]) for segment in segments if segment[2])
    return {
        "available": True,
        "vocal_activity_active_ratio": _safe_divide(active_duration, span),
        "vocal_activity_segment_count": len(segments),
        "vocal_activity_time_span_sec": span,
        "active_duration_sec": active_duration,
    }


def _derive_note_candidate_diagnostics(note_candidates_path: Path | None, *, predicted_note_count: int) -> dict[str, Any]:
    if note_candidates_path is None or not note_candidates_path.exists():
        return _unavailable("note_candidates.json missing")
    payload = _read_json(note_candidates_path)
    candidates = _extract_candidate_notes(payload)
    if not candidates:
        return _unavailable("note candidates unavailable")
    durations = [duration for _, duration, _ in candidates if duration is not None]
    pitches = [pitch for _, _, pitch in candidates if pitch is not None]
    return {
        "available": True,
        "note_candidate_count": len(candidates),
        "candidate_to_predicted_ratio": _safe_divide(len(candidates), predicted_note_count),
        "candidate_median_duration_sec": _median(durations),
        "candidate_short_note_ratio": _safe_divide(sum(1 for duration in durations if duration < 0.25), len(durations)),
        "candidate_pitch_range": [min(pitches), max(pitches)] if pitches else None,
    }


def _derive_pitch_contour_diagnostics(pitch_contours_path: Path | None) -> dict[str, Any]:
    if pitch_contours_path is None or not pitch_contours_path.exists():
        return _unavailable("pitch_contours.json missing")
    payload = _read_json(pitch_contours_path)
    contours = payload.get("contours") if isinstance(payload, dict) else None
    if not isinstance(contours, list):
        return _unavailable("pitch contours unavailable")
    durations = [_as_float(item.get("duration_sec")) for item in contours if isinstance(item, dict)]
    durations = [value for value in durations if value is not None]
    return {
        "available": True,
        "contour_count": len(contours),
        "low_confidence_contour_count": sum(1 for item in contours if isinstance(item, dict) and "low_confidence" in (item.get("reason_codes") or [])),
        "median_contour_duration_sec": _median(durations),
        "suspected_vibrato_contour_count": sum(1 for item in contours if isinstance(item, dict) and item.get("has_vibrato")),
        "suspected_glide_contour_count": sum(1 for item in contours if isinstance(item, dict) and item.get("has_glide")),
    }


def _derive_selected_melody_diagnostics(selected_melody_path: Path | None) -> dict[str, Any]:
    if selected_melody_path is None or not selected_melody_path.exists():
        return _unavailable("selected_melody.json missing")
    payload = _read_json(selected_melody_path)
    if not isinstance(payload, dict):
        return _unavailable("selected melody unavailable")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "available": True,
        "input_candidate_count": summary.get("input_candidate_count", 0),
        "selected_count": summary.get("selected_count", 0),
        "rejected_count": summary.get("rejected_count", 0),
        "rejection_reason_counts": summary.get("rejection_reason_counts") if isinstance(summary.get("rejection_reason_counts"), dict) else {},
        "mean_selected_confidence": summary.get("mean_selected_confidence"),
        "mean_rejected_confidence": summary.get("mean_rejected_confidence"),
    }


def _derive_quantized_note_diagnostics(quantized_notes_path: Path | None) -> dict[str, Any]:
    if quantized_notes_path is None or not quantized_notes_path.exists():
        return _unavailable("quantized_notes.json missing")
    payload = _read_json(quantized_notes_path)
    if not isinstance(payload, dict):
        return _unavailable("quantized notes unavailable")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    fragmentation = summary.get("fragmentation") if isinstance(summary.get("fragmentation"), dict) else {}
    if not fragmentation:
        fragmentation = diagnostics.get("fragmentation") if isinstance(diagnostics.get("fragmentation"), dict) else {}
    overmerge = summary.get("overmerge") if isinstance(summary.get("overmerge"), dict) else {}
    if not overmerge:
        overmerge = diagnostics.get("overmerge") if isinstance(diagnostics.get("overmerge"), dict) else {}
    return {
        "available": True,
        "quantizer_backend": payload.get("quantizer_backend"),
        "requested_quantizer_backend": payload.get("requested_quantizer_backend"),
        "fallback_used": bool(payload.get("fallback_used") or summary.get("fallback_used")),
        "fallback_reason": payload.get("fallback_reason") or summary.get("fallback_reason"),
        "note_count": summary.get("note_count", 0),
        "mean_quantize_error_sec": summary.get("mean_quantize_error_sec"),
        "p95_quantize_error_sec": summary.get("p95_quantize_error_sec"),
        "max_quantize_error_sec": summary.get("max_quantize_error_sec"),
        "uncertain_count": summary.get("uncertain_count", 0),
        "fragmentation": fragmentation,
        "overmerge": overmerge,
    }


def build_note_funnel_debug(
    *,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    f0_track_path: Path | None,
    note_candidates_path: Path | None,
    selected_melody_path: Path | None,
    quantized_notes_path: Path | None,
    score_ir_path: Path | None,
) -> dict[str, Any]:
    f0_summary = _note_funnel_f0_summary(f0_track_path)
    expected_layer = _note_funnel_layer_from_notes("expected", expected_notes)
    candidate_events = _load_artifact_note_events(note_candidates_path, kind="note_candidates")
    selected_events = _load_artifact_note_events(selected_melody_path, kind="selected_melody")
    quantized_events = _load_artifact_note_events(quantized_notes_path, kind="quantized_notes")
    score_ir_events = _load_artifact_note_events(score_ir_path, kind="score_ir")

    layers = {
        "expected": expected_layer,
        "note_candidates": _note_funnel_layer_from_artifact(
            "note_candidates",
            candidate_events,
            note_candidates_path,
            "note_candidates.json missing",
        ),
        "selected_melody": _note_funnel_layer_from_artifact(
            "selected_melody",
            selected_events,
            selected_melody_path,
            "selected_melody.json missing",
        ),
        "quantized_notes": _note_funnel_layer_from_artifact(
            "quantized_notes",
            quantized_events,
            quantized_notes_path,
            "quantized_notes.json missing",
        ),
        "score_ir": _note_funnel_layer_from_artifact(
            "score_ir",
            score_ir_events,
            score_ir_path,
            "score_ir.json missing",
        ),
        "predicted_midi": _note_funnel_layer_from_notes("predicted_midi", predicted_notes),
    }
    retention = _note_funnel_retention(layers)
    loss_attribution = _note_funnel_loss_attribution(layers, retention)
    available_layers = [name for name, layer in layers.items() if layer.get("available")]
    return {
        "available": True,
        "diagnostic_only": True,
        "f0_voiced_frame_count": f0_summary.get("f0_voiced_frame_count"),
        "f0_voiced_duration_sec": f0_summary.get("f0_voiced_duration_sec"),
        "note_candidate_count": layers["note_candidates"].get("count"),
        "selected_note_count": layers["selected_melody"].get("count"),
        "quantized_note_count": layers["quantized_notes"].get("count"),
        "score_ir_note_count": layers["score_ir"].get("count"),
        "predicted_midi_note_count": layers["predicted_midi"].get("count"),
        "expected_note_count": layers["expected"].get("count"),
        "f0": f0_summary,
        "layers": layers,
        "retention": retention,
        "loss_attribution": loss_attribution,
        "available_layers": available_layers,
        "missing_layers": [name for name, layer in layers.items() if not layer.get("available")],
    }


def build_note_funnel_debug_markdown(
    *,
    sample_id: str,
    sample_title: str,
    note_funnel_debug: dict[str, Any],
) -> str:
    layers = note_funnel_debug.get("layers") if isinstance(note_funnel_debug.get("layers"), dict) else {}
    retention = note_funnel_debug.get("retention") if isinstance(note_funnel_debug.get("retention"), dict) else {}
    loss = note_funnel_debug.get("loss_attribution") if isinstance(note_funnel_debug.get("loss_attribution"), dict) else {}
    flags = loss.get("flags") if isinstance(loss.get("flags"), dict) else {}
    triggered = loss.get("triggered_flags") if isinstance(loss.get("triggered_flags"), list) else []
    lines = [
        f"# Note Funnel Debug: {sample_title}",
        "",
        f"- sample_id: {sample_id}",
        "- diagnostic_only: true",
        f"- f0_voiced_frame_count: {_fmt(note_funnel_debug.get('f0_voiced_frame_count'))}",
        f"- f0_voiced_duration_sec: {_fmt(note_funnel_debug.get('f0_voiced_duration_sec'))}",
        "",
        "## Layer Summary",
        "| Layer | Available | Count | Notes/sec | Median duration | Short ratio | Very short ratio | Median pitch | Pitch range | Total note duration | Missing reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for layer_name in ["expected", "note_candidates", "selected_melody", "quantized_notes", "score_ir", "predicted_midi"]:
        layer = layers.get(layer_name) if isinstance(layers.get(layer_name), dict) else {}
        pitch_range = layer.get("pitch_range")
        pitch_range_text = "missing"
        if isinstance(pitch_range, list) and len(pitch_range) >= 2:
            pitch_range_text = f"{_fmt(pitch_range[0])}-{_fmt(pitch_range[1])}"
        lines.append(
            "| "
            + " | ".join(
                [
                    layer_name,
                    str(bool(layer.get("available"))).lower(),
                    _fmt(layer.get("count")),
                    _fmt(layer.get("notes_per_second")),
                    _fmt(layer.get("median_duration_sec")),
                    _fmt(layer.get("short_note_ratio")),
                    _fmt(layer.get("very_short_note_ratio")),
                    _fmt(layer.get("median_pitch")),
                    pitch_range_text,
                    _fmt(layer.get("total_note_duration_sec")),
                    _fmt(layer.get("unavailable_reason")) if not layer.get("available") else "none",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Retention",
            f"- candidate_to_selected_count_ratio: {_fmt(retention.get('candidate_to_selected_count_ratio'))}",
            f"- selected_to_quantized_count_ratio: {_fmt(retention.get('selected_to_quantized_count_ratio'))}",
            f"- quantized_to_score_ir_count_ratio: {_fmt(retention.get('quantized_to_score_ir_count_ratio'))}",
            f"- score_ir_to_predicted_count_ratio: {_fmt(retention.get('score_ir_to_predicted_count_ratio'))}",
            f"- candidate_to_predicted_count_ratio: {_fmt(retention.get('candidate_to_predicted_count_ratio'))}",
            "",
            "## Loss Attribution",
            f"- triggered_flags: {', '.join(str(flag) for flag in triggered) if triggered else 'none'}",
            f"- primary_attribution: {_fmt(loss.get('primary_attribution'))}",
        ]
    )
    for key in [
        "possible_candidate_extraction_loss",
        "possible_melody_selection_loss",
        "possible_quantization_overmerge",
        "possible_score_build_loss",
        "possible_export_loss",
        "possible_short_note_loss",
        "possible_overmerge",
        "possible_fragmentation",
    ]:
        flag = flags.get(key) if isinstance(flags, dict) else None
        if isinstance(flag, dict):
            lines.append(
                f"- {key}: {str(bool(flag.get('triggered'))).lower()}"
                f" (evidence: {_fmt(flag.get('evidence'))})"
            )
    return "\n".join(lines)


def _note_funnel_f0_summary(f0_track_path: Path | None) -> dict[str, Any]:
    if f0_track_path is None or not f0_track_path.exists():
        return _unavailable("f0_track.json missing")
    payload = _read_json(f0_track_path)
    frames = payload.get("frames") if isinstance(payload, dict) else payload
    if not isinstance(frames, list):
        return _unavailable("f0 frames unavailable")
    frame_hop = None
    if isinstance(payload, dict):
        analysis_info = payload.get("analysis_info") if isinstance(payload.get("analysis_info"), dict) else {}
        frame_hop = _as_float(_first_present(analysis_info, "frame_hop_sec", "hop_sec", "hop_length_sec"))
    times: list[float] = []
    voiced_times: list[float] = []
    voiced_count = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        time_sec = _as_float(_first_present(frame, "time_sec", "time", "t", "timestamp"))
        if time_sec is not None:
            times.append(time_sec)
        if _frame_is_voiced(frame):
            voiced_count += 1
            if time_sec is not None:
                voiced_times.append(time_sec)
    if frame_hop is None:
        diffs = _positive_diffs(sorted(times))
        frame_hop = _median(diffs)
    voiced_duration = voiced_count * frame_hop if frame_hop is not None else None
    if voiced_duration is None and len(voiced_times) >= 2:
        voiced_duration = max(voiced_times) - min(voiced_times)
    return {
        "available": True,
        "f0_frame_count": len(frames),
        "f0_voiced_frame_count": voiced_count,
        "f0_voiced_duration_sec": _round_optional(voiced_duration),
        "frame_hop_sec": _round_optional(frame_hop),
    }


def _note_funnel_layer_from_notes(layer_name: str, notes: list[NoteEvent]) -> dict[str, Any]:
    return _note_funnel_layer_stats(layer_name, notes, available=True)


def _note_funnel_layer_from_artifact(
    layer_name: str,
    events: list[NoteEvent] | None,
    path: Path | None,
    missing_reason: str,
) -> dict[str, Any]:
    if path is None or not path.exists():
        return _note_funnel_unavailable_layer(layer_name, missing_reason)
    if events is None:
        return _note_funnel_unavailable_layer(layer_name, f"{path.name} unreadable")
    return _note_funnel_layer_stats(layer_name, events, available=True)


def _note_funnel_unavailable_layer(layer_name: str, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "layer": layer_name,
        "unavailable_reason": reason,
        "count": "unavailable",
        "notes_per_second": "unavailable",
        "median_duration_sec": "unavailable",
        "short_note_ratio": "unavailable",
        "very_short_note_ratio": "unavailable",
        "median_pitch": "unavailable",
        "pitch_range": "unavailable",
        "total_note_duration_sec": "unavailable",
    }


def _note_funnel_layer_stats(layer_name: str, notes: list[NoteEvent], *, available: bool) -> dict[str, Any]:
    stats = _note_collection_stats(notes)
    durations = [float(note.duration) for note in notes]
    total_duration = sum(durations)
    return {
        "available": available,
        "layer": layer_name,
        "count": len(notes),
        "notes_per_second": _round_optional(_safe_divide(len(notes), stats.get("time_span_sec"))),
        "median_duration_sec": _round_optional(stats.get("median_duration_sec")),
        "short_note_ratio": _round_optional(stats.get("short_note_ratio")),
        "very_short_note_ratio": _round_optional(_safe_divide(sum(1 for duration in durations if duration < 0.125), len(durations))),
        "median_pitch": _round_optional(stats.get("median_pitch")),
        "pitch_range": stats.get("pitch_range"),
        "total_note_duration_sec": _round_float(total_duration),
        "time_span_sec": _round_optional(stats.get("time_span_sec")),
    }


def _note_funnel_retention(layers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_to_selected_count_ratio": _round_optional(_layer_count_ratio(layers, "selected_melody", "note_candidates")),
        "selected_to_quantized_count_ratio": _round_optional(_layer_count_ratio(layers, "quantized_notes", "selected_melody")),
        "quantized_to_score_ir_count_ratio": _round_optional(_layer_count_ratio(layers, "score_ir", "quantized_notes")),
        "score_ir_to_predicted_count_ratio": _round_optional(_layer_count_ratio(layers, "predicted_midi", "score_ir")),
        "candidate_to_predicted_count_ratio": _round_optional(_layer_count_ratio(layers, "predicted_midi", "note_candidates")),
    }


def _layer_count_ratio(layers: dict[str, dict[str, Any]], numerator_layer: str, denominator_layer: str) -> float | None:
    numerator = _layer_count(layers, numerator_layer)
    denominator = _layer_count(layers, denominator_layer)
    return _safe_divide(numerator, denominator)


def _layer_count(layers: dict[str, dict[str, Any]], layer_name: str) -> int | None:
    layer = layers.get(layer_name) if isinstance(layers.get(layer_name), dict) else {}
    count = layer.get("count")
    return _as_int(count)


def _layer_float(layers: dict[str, dict[str, Any]], layer_name: str, key: str) -> float | None:
    layer = layers.get(layer_name) if isinstance(layers.get(layer_name), dict) else {}
    return _as_float(layer.get(key))


def _note_funnel_loss_attribution(layers: dict[str, dict[str, Any]], retention: dict[str, Any]) -> dict[str, Any]:
    expected_count = _layer_count(layers, "expected") or 0
    candidate_count = _layer_count(layers, "note_candidates")
    selected_count = _layer_count(layers, "selected_melody")
    quantized_count = _layer_count(layers, "quantized_notes")
    score_ir_count = _layer_count(layers, "score_ir")
    predicted_count = _layer_count(layers, "predicted_midi") or 0
    expected_short_ratio = _layer_float(layers, "expected", "short_note_ratio")
    predicted_short_ratio = _layer_float(layers, "predicted_midi", "short_note_ratio")
    expected_median_duration = _layer_float(layers, "expected", "median_duration_sec")
    candidate_median_duration = _layer_float(layers, "note_candidates", "median_duration_sec")
    predicted_median_duration = _layer_float(layers, "predicted_midi", "median_duration_sec")
    short_note_ratio_delta = (
        expected_short_ratio - predicted_short_ratio
        if expected_short_ratio is not None and predicted_short_ratio is not None
        else None
    )
    overmerge_reference_duration = max(
        [value for value in [candidate_median_duration, expected_median_duration] if value is not None],
        default=None,
    )

    flags = {
        "possible_candidate_extraction_loss": _flag(
            candidate_count is not None
            and expected_count > 0
            and candidate_count < max(10, int(expected_count * 0.35)),
            {
                "expected_note_count": expected_count,
                "note_candidate_count": candidate_count,
                "candidate_expected_ratio": _round_optional(_safe_divide(candidate_count, expected_count)),
            },
        ),
        "possible_melody_selection_loss": _flag(
            candidate_count is not None
            and selected_count is not None
            and candidate_count >= max(10, int(expected_count * 0.35))
            and selected_count < candidate_count * 0.55,
            {
                "note_candidate_count": candidate_count,
                "selected_note_count": selected_count,
                "candidate_to_selected_count_ratio": retention.get("candidate_to_selected_count_ratio"),
            },
        ),
        "possible_quantization_overmerge": _flag(
            selected_count is not None
            and quantized_count is not None
            and selected_count >= 10
            and quantized_count < selected_count * 0.70,
            {
                "selected_note_count": selected_count,
                "quantized_note_count": quantized_count,
                "selected_to_quantized_count_ratio": retention.get("selected_to_quantized_count_ratio"),
            },
        ),
        "possible_score_build_loss": _flag(
            quantized_count is not None
            and score_ir_count is not None
            and quantized_count >= 10
            and score_ir_count < quantized_count * 0.85,
            {
                "quantized_note_count": quantized_count,
                "score_ir_note_count": score_ir_count,
                "quantized_to_score_ir_count_ratio": retention.get("quantized_to_score_ir_count_ratio"),
            },
        ),
        "possible_export_loss": _flag(
            score_ir_count is not None
            and score_ir_count >= 10
            and predicted_count < score_ir_count * 0.85,
            {
                "score_ir_note_count": score_ir_count,
                "predicted_midi_note_count": predicted_count,
                "score_ir_to_predicted_count_ratio": retention.get("score_ir_to_predicted_count_ratio"),
            },
        ),
        "possible_short_note_loss": _flag(
            expected_short_ratio is not None
            and predicted_short_ratio is not None
            and expected_short_ratio >= 0.45
            and predicted_short_ratio <= expected_short_ratio - 0.25,
            {
                "expected_short_note_ratio": _round_optional(expected_short_ratio),
                "predicted_short_note_ratio": _round_optional(predicted_short_ratio),
                "short_note_ratio_delta": _round_optional(short_note_ratio_delta),
            },
        ),
        "possible_overmerge": _flag(
            candidate_count is not None
            and predicted_count > 0
            and candidate_count >= predicted_count * 1.25
            and predicted_median_duration is not None
            and overmerge_reference_duration is not None
            and predicted_median_duration >= overmerge_reference_duration * 1.25,
            {
                "note_candidate_count": candidate_count,
                "predicted_midi_note_count": predicted_count,
                "candidate_to_predicted_count_ratio": retention.get("candidate_to_predicted_count_ratio"),
                "candidate_median_duration_sec": _round_optional(candidate_median_duration),
                "expected_median_duration_sec": _round_optional(expected_median_duration),
                "predicted_median_duration_sec": _round_optional(predicted_median_duration),
            },
        ),
        "possible_fragmentation": _flag(
            expected_count > 0
            and predicted_count >= expected_count * 1.35
            and predicted_median_duration is not None
            and predicted_median_duration < 0.20,
            {
                "expected_note_count": expected_count,
                "predicted_midi_note_count": predicted_count,
                "predicted_expected_count_ratio": _round_optional(_safe_divide(predicted_count, expected_count)),
                "predicted_median_duration_sec": _round_optional(predicted_median_duration),
            },
        ),
    }
    triggered = [name for name, payload in flags.items() if payload.get("triggered")]
    return {
        "available": True,
        "flags": flags,
        "triggered_flags": triggered,
        "primary_attribution": triggered[0] if triggered else "none",
    }


def _flag(triggered: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"triggered": bool(triggered), "evidence": evidence}


def _derive_rhythm_diagnostics(rhythm_debug_path: Path | None, *, rhythm_candidates_path: Path | None = None) -> dict[str, Any]:
    if rhythm_debug_path is None or not rhythm_debug_path.exists():
        diagnostics = _unavailable("rhythm_debug.json missing")
        _attach_rhythm_candidate_summary(diagnostics, rhythm_candidates_path)
        return diagnostics
    payload = _read_json(rhythm_debug_path)
    if not isinstance(payload, dict):
        diagnostics = _unavailable("rhythm diagnostics unavailable")
        _attach_rhythm_candidate_summary(diagnostics, rhythm_candidates_path)
        return diagnostics
    if not payload.get("available"):
        _attach_rhythm_candidate_summary(payload, rhythm_candidates_path)
        return payload
    fields = [
        "available",
        "diagnostic_only",
        "tempo_bpm",
        "tempo_stability",
        "beat_count",
        "beat_gap_mean_sec",
        "beat_gap_p95_sec",
        "beat_gap_max_sec",
        "downbeat_count",
        "downbeat_confidence",
        "bar_phase_confidence",
        "off_grid_onset_ratio",
        "pickup_likelihood",
        "rubato_likelihood",
        "grid_uncertain_region_count",
        "grid_uncertain_regions",
        "preliminary_rhythm_diagnosis",
        "rhythm_flags",
    ]
    diagnostics = {field: payload.get(field) for field in fields}
    _attach_rhythm_candidate_summary(diagnostics, rhythm_candidates_path)
    return diagnostics


def _attach_rhythm_candidate_summary(diagnostics: dict[str, Any], rhythm_candidates_path: Path | None) -> None:
    candidates_payload = _read_json(rhythm_candidates_path) if rhythm_candidates_path is not None and rhythm_candidates_path.exists() else None
    if not isinstance(candidates_payload, dict):
        diagnostics.update(
            {
                "candidates": [],
                "best_diagnostic_candidate_id": None,
                "current_candidate_rank": None,
                "current_vs_best_score_delta": None,
                "rhythm_candidate_warning": None,
            }
        )
        return
    candidates = candidates_payload.get("candidates") if isinstance(candidates_payload.get("candidates"), list) else []
    diagnostics.update(
        {
            "candidates": candidates,
            "best_diagnostic_candidate_id": candidates_payload.get("best_diagnostic_candidate_id"),
            "current_candidate_rank": candidates_payload.get("current_candidate_rank"),
            "current_vs_best_score_delta": candidates_payload.get("current_vs_best_score_delta"),
            "rhythm_candidate_warning": candidates_payload.get("rhythm_candidate_warning"),
        }
    )


def _derive_short_note_diagnostics(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    duration_threshold_sec: float = 0.25,
    note_candidates_path: Path | None = None,
    selected_melody_path: Path | None = None,
    quantized_notes_path: Path | None = None,
) -> dict[str, Any]:
    if not expected_notes:
        return _unavailable("reference notes unavailable")
    expected_short = [note for note in expected_notes if note.duration < duration_threshold_sec]
    predicted_short = [note for note in predicted_notes if note.duration < duration_threshold_sec]
    matched_expected, matched_predicted = _match_short_note_sets(expected_short, predicted_short)
    missed_expected = [note for index, note in enumerate(expected_short) if index not in matched_expected]
    loss_attribution = _attribute_short_note_loss(
        missed_expected,
        note_candidates_path=note_candidates_path,
        selected_melody_path=selected_melody_path,
        quantized_notes_path=quantized_notes_path,
        duration_threshold_sec=duration_threshold_sec,
    )
    return {
        "available": True,
        "duration_threshold_sec": duration_threshold_sec,
        "expected_short_note_count": len(expected_short),
        "predicted_short_note_count": len(predicted_short),
        "matched_short_note_count": len(matched_expected),
        "missed_short_note_count": max(0, len(expected_short) - len(matched_expected)),
        "false_positive_short_note_count": max(0, len(predicted_short) - len(matched_predicted)),
        "short_note_recall": _safe_divide(len(matched_expected), len(expected_short)),
        "short_note_precision": _safe_divide(len(matched_predicted), len(predicted_short)),
        "loss_attribution": loss_attribution,
    }


def _attribute_short_note_loss(
    missed_expected_short_notes: list[NoteEvent],
    *,
    note_candidates_path: Path | None,
    selected_melody_path: Path | None,
    quantized_notes_path: Path | None,
    duration_threshold_sec: float,
) -> dict[str, Any]:
    stage_counts = {"candidate": 0, "selector": 0, "quantizer": 0, "export": 0, "unknown": 0}
    if not missed_expected_short_notes:
        return {
            "available": True,
            "likely_loss_stage": "none",
            "stage_counts": stage_counts,
            "examples": [],
        }

    candidate_events = _load_artifact_note_events(note_candidates_path, kind="note_candidates")
    selected_events = _load_artifact_note_events(selected_melody_path, kind="selected_melody")
    quantized_events = _load_artifact_note_events(quantized_notes_path, kind="quantized_notes")
    examples: list[dict[str, Any]] = []
    for note in missed_expected_short_notes:
        if candidate_events is None:
            stage = "unknown"
        elif not _has_matching_artifact_event(note, candidate_events, duration_threshold_sec=duration_threshold_sec):
            stage = "candidate"
        elif selected_events is None:
            stage = "unknown"
        elif not _has_matching_artifact_event(note, selected_events, duration_threshold_sec=duration_threshold_sec):
            stage = "selector"
        elif quantized_events is None:
            stage = "unknown"
        elif not _has_matching_artifact_event(note, quantized_events, duration_threshold_sec=duration_threshold_sec):
            stage = "quantizer"
        else:
            stage = "export"
        stage_counts[stage] += 1
        if len(examples) < 20:
            examples.append(
                {
                    "start_sec": _round_float(note.start),
                    "duration_sec": _round_float(note.duration),
                    "pitch": int(note.pitch),
                    "likely_loss_stage": stage,
                }
            )
    likely_stage = max(stage_counts, key=lambda key: stage_counts[key])
    if stage_counts[likely_stage] == 0:
        likely_stage = "none"
    return {
        "available": True,
        "likely_loss_stage": likely_stage,
        "stage_counts": stage_counts,
        "artifact_availability": {
            "note_candidates": candidate_events is not None,
            "selected_melody": selected_events is not None,
            "quantized_notes": quantized_events is not None,
        },
        "examples": examples,
    }


def _match_short_note_sets(expected: list[NoteEvent], predicted: list[NoteEvent]) -> tuple[set[int], set[int]]:
    matched_expected: set[int] = set()
    matched_predicted: set[int] = set()
    for expected_index, expected_note in enumerate(expected):
        best_index: int | None = None
        best_delta: float | None = None
        for predicted_index, predicted_note in enumerate(predicted):
            if predicted_index in matched_predicted or int(predicted_note.pitch) != int(expected_note.pitch):
                continue
            delta = abs(float(predicted_note.start) - float(expected_note.start))
            if delta <= 0.08 and (best_delta is None or delta < best_delta):
                best_delta = delta
                best_index = predicted_index
        if best_index is not None:
            matched_expected.add(expected_index)
            matched_predicted.add(best_index)
    return matched_expected, matched_predicted


def _load_artifact_note_events(path: Path | None, *, kind: str) -> list[NoteEvent] | None:
    if path is None or not path.exists():
        return None
    payload = _read_json(path)
    if payload is None:
        return None
    if kind == "selected_melody" and isinstance(payload, dict):
        items = payload.get("selected_notes") if isinstance(payload.get("selected_notes"), list) else []
    elif kind in {"quantized_notes", "score_ir"} and isinstance(payload, dict):
        items = payload.get("notes") if isinstance(payload.get("notes"), list) else []
    else:
        items = _walk_note_like_items(_preferred_candidate_note_payload(payload))
    events: list[NoteEvent] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        event = _artifact_item_to_note_event(item)
        if event is not None:
            events.append(event)
    return events


def _artifact_item_to_note_event(item: dict[str, Any]) -> NoteEvent | None:
    start = _as_float(
        _first_present(
            item,
            "quantized_start_time_sec",
            "start_time_sec",
            "start_time",
            "onset_sec",
            "start_sec",
            "start",
            "time_sec",
        )
    )
    end = _as_float(
        _first_present(item, "quantized_end_time_sec", "end_time_sec", "end_time", "offset_sec", "end_sec", "end")
    )
    duration = _as_float(_first_present(item, "quantized_duration_sec", "duration_sec", "duration"))
    if duration is None:
        duration_beats = _as_float(item.get("duration_beats"))
        tempo_bpm = _as_float(item.get("tempo_bpm"))
        if duration_beats is not None and tempo_bpm is not None and tempo_bpm > 0:
            duration = duration_beats * (60.0 / tempo_bpm)
    if end is None and start is not None and duration is not None:
        end = start + duration
    if duration is None and start is not None and end is not None:
        duration = max(0.0, end - start)
    pitch = _candidate_pitch_midi(item)
    if start is None or pitch is None:
        return None
    if end is None:
        end = start + max(0.0, duration or 0.0)
    return NoteEvent(start=float(start), end=float(end), pitch=int(round(pitch)))


def _has_matching_artifact_event(
    expected: NoteEvent,
    events: list[NoteEvent],
    *,
    duration_threshold_sec: float,
) -> bool:
    for event in events:
        if int(event.pitch) != int(expected.pitch):
            continue
        onset_delta = abs(float(event.start) - float(expected.start))
        if onset_delta > 0.10:
            continue
        if expected.duration < duration_threshold_sec and event.duration <= duration_threshold_sec * 1.5:
            return True
        if _duration_iou(expected, event) >= 0.35:
            return True
    return False


def _derive_pitch_distribution_diagnostics(
    *,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    f0_track_path: Path | None,
    note_candidates_path: Path | None,
) -> dict[str, Any]:
    expected = _build_pitch_source_distribution(
        _note_events_to_pitch_events(expected_notes),
        source_kind="expected_notes",
        source_file="expected_notes.json",
        preferred_weight_type="duration_sec",
    )
    predicted = _build_pitch_source_distribution(
        _note_events_to_pitch_events(predicted_notes),
        source_kind="predicted_notes",
        source_file="predicted_notes.json",
        preferred_weight_type="duration_sec",
    )
    f0_events, f0_warnings = _extract_f0_pitch_events(f0_track_path)
    f0 = _build_pitch_source_distribution(
        f0_events,
        source_kind="f0_frames",
        source_file="f0_track.json",
        preferred_weight_type="frame_time_sec",
        extra_warnings=f0_warnings,
    )
    candidate_sources, candidate_warnings = _extract_note_candidate_pitch_sources(note_candidates_path)
    note_candidates_all = _build_pitch_source_distribution(
        candidate_sources.get("all", []),
        source_kind="note_candidates_all",
        source_file="note_candidates.json",
        preferred_weight_type="duration_sec",
        extra_warnings=candidate_warnings.get("all", []),
    )
    note_candidates_selected = _build_pitch_source_distribution(
        candidate_sources.get("selected", []),
        source_kind="note_candidates_selected",
        source_file="note_candidates.json",
        preferred_weight_type="duration_sec",
        extra_warnings=candidate_warnings.get("selected", []),
    )
    note_candidates_melody_raw = _build_pitch_source_distribution(
        candidate_sources.get("melody_raw", []),
        source_kind="note_candidates_melody_raw",
        source_file="note_candidates.json",
        preferred_weight_type="duration_sec",
        extra_warnings=candidate_warnings.get("melody_raw", []),
    )
    sources = {
        "expected_notes": expected,
        "predicted_notes": predicted,
        "f0_frames": f0,
        "note_candidates_all": note_candidates_all,
        "note_candidates_selected": note_candidates_selected,
        "note_candidates_melody_raw": note_candidates_melody_raw,
    }
    pairwise = {
        "expected_vs_predicted": _pitch_pairwise_overlap(expected, predicted),
        "expected_vs_f0": _pitch_pairwise_overlap(expected, f0),
        "expected_vs_note_candidates": _pitch_pairwise_overlap(expected, note_candidates_all),
        "f0_vs_note_candidates": _pitch_pairwise_overlap(f0, note_candidates_all),
        "f0_vs_predicted": _pitch_pairwise_overlap(f0, predicted),
        "note_candidates_vs_predicted": _pitch_pairwise_overlap(note_candidates_all, predicted),
        "note_candidates_all_vs_selected": _pitch_pairwise_overlap(note_candidates_all, note_candidates_selected),
        "note_candidates_selected_vs_predicted": _pitch_pairwise_overlap(note_candidates_selected, predicted),
    }
    candidate_funnel = _pitch_candidate_funnel(
        f0=f0,
        all_candidates=note_candidates_all,
        selected_candidates=note_candidates_selected,
        predicted=predicted,
    )
    flags = _derive_pitch_distribution_flags(
        sources=sources,
        pairwise=pairwise,
        candidate_funnel=candidate_funnel,
    )
    triggered = [name for name, flag in flags.items() if isinstance(flag, dict) and flag.get("triggered")]
    preliminary = triggered[0] if triggered else "no_pitch_distribution_flag_triggered"
    warnings = _collect_pitch_distribution_warnings(sources=sources, pairwise=pairwise, flags=flags)
    return {
        "available": any(source.get("available") for source in sources.values()),
        "diagnostic_only": True,
        "pitch_unit": "midi_semitones",
        "expected_notes": expected,
        "predicted_notes": predicted,
        "f0_frames": f0,
        "note_candidates_all": note_candidates_all,
        "note_candidates_selected": note_candidates_selected,
        "note_candidates_melody_raw": note_candidates_melody_raw,
        "pairwise": pairwise,
        "candidate_funnel": candidate_funnel,
        "flags": flags,
        "triggered_pitch_flags": triggered,
        "preliminary_pitch_diagnosis": preliminary,
        "warnings": warnings,
    }


def _build_pitch_source_distribution(
    events: list[dict[str, Any]],
    *,
    source_kind: str,
    source_file: str,
    preferred_weight_type: str,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings = list(extra_warnings or [])
    event_count = len(events)
    valid_events = [event for event in events if _as_float(event.get("pitch")) is not None]
    valid_pitch_count = len(valid_events)
    invalid_pitch_count = max(0, event_count - valid_pitch_count)
    weight_key = preferred_weight_type
    if valid_events and not all((_as_float(event.get(weight_key)) or 0.0) > 0.0 for event in valid_events):
        weight_key = "count"
        warnings.append(f"{source_kind}: missing {preferred_weight_type}; using count weights")
    weights: list[float] = []
    pitches: list[float] = []
    for event in valid_events:
        pitch = _as_float(event.get("pitch"))
        if pitch is None:
            continue
        weight = 1.0 if weight_key == "count" else (_as_float(event.get(weight_key)) or 0.0)
        if weight <= 0.0:
            weight = 1.0
        pitches.append(pitch)
        weights.append(weight)
    duration_values = [
        _as_float(event.get("duration_sec"))
        for event in valid_events
        if _as_float(event.get("duration_sec")) is not None and (_as_float(event.get("duration_sec")) or 0.0) > 0.0
    ]
    frame_values = [
        _as_float(event.get("frame_time_sec"))
        for event in valid_events
        if _as_float(event.get("frame_time_sec")) is not None and (_as_float(event.get("frame_time_sec")) or 0.0) > 0.0
    ]
    duration_sec = sum(duration_values) if duration_values else (sum(frame_values) if frame_values else None)
    histogram = _weighted_pitch_histogram(pitches, weights)
    pitch_range = _pitch_range_payload(pitches, weights)
    mean_pitch = _weighted_mean(pitches, weights)
    median_pitch = pitch_range.get("p50")
    if event_count == 0:
        warnings.append(f"{source_kind}: no events")
    elif valid_pitch_count == 0:
        warnings.append(f"{source_kind}: no valid pitches")
    return {
        "available": valid_pitch_count > 0,
        "source_kind": source_kind,
        "source_file": source_file,
        "pitch_unit": "midi_semitones",
        "event_count": event_count,
        "valid_pitch_count": valid_pitch_count,
        "invalid_pitch_count": invalid_pitch_count,
        "duration_sec": _round_optional(duration_sec),
        "weight_type": weight_key,
        "median_pitch": _round_optional(median_pitch),
        "mean_pitch": _round_optional(mean_pitch),
        "pitch_range": pitch_range,
        "histogram": histogram,
        "warnings": warnings,
    }


def _note_events_to_pitch_events(notes: list[NoteEvent]) -> list[dict[str, Any]]:
    return [
        {
            "pitch": float(note.pitch),
            "duration_sec": float(note.duration),
        }
        for note in notes
    ]


def _extract_f0_pitch_events(f0_track_path: Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    if f0_track_path is None or not f0_track_path.exists():
        return [], ["f0_track.json missing"]
    payload = _read_json(f0_track_path)
    frames = payload.get("frames") if isinstance(payload, dict) else payload
    if not isinstance(frames, list):
        return [], ["f0_track.json frames unavailable"]
    analysis_info = payload.get("analysis_info") if isinstance(payload, dict) and isinstance(payload.get("analysis_info"), dict) else {}
    frame_hop_sec = _as_float(_first_present(analysis_info, "frame_hop_sec", "hop_sec", "hop_length_sec"))
    events: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            events.append({"pitch": None, "frame_time_sec": frame_hop_sec})
            continue
        time_sec = _as_float(_first_present(frame, "time_sec", "time", "t", "timestamp"))
        voiced = _frame_is_voiced(frame)
        pitch = _frame_pitch_midi(frame) if voiced else None
        events.append({"pitch": pitch, "time_sec": time_sec, "frame_time_sec": frame_hop_sec})
    if frame_hop_sec is None or frame_hop_sec <= 0.0:
        _infer_frame_time_weights(events)
    return events, []


def _infer_frame_time_weights(events: list[dict[str, Any]]) -> None:
    timed = [(index, _as_float(event.get("time_sec"))) for index, event in enumerate(events)]
    timed = [(index, time_sec) for index, time_sec in timed if time_sec is not None]
    deltas: list[float] = []
    for (_, current), (_, next_time) in zip(timed, timed[1:]):
        delta = next_time - current
        if delta > 0.0:
            deltas.append(delta)
    fallback = _median(deltas) if deltas else None
    for position, (index, time_sec) in enumerate(timed):
        next_time = timed[position + 1][1] if position + 1 < len(timed) else None
        duration = (next_time - time_sec) if next_time is not None and next_time > time_sec else fallback
        if duration is not None and duration > 0.0:
            events[index]["frame_time_sec"] = duration


def _extract_note_candidate_pitch_sources(note_candidates_path: Path | None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    empty_sources = {"all": [], "selected": [], "melody_raw": []}
    empty_warnings = {
        "all": ["note_candidates.json missing"],
        "selected": ["note_candidates.json missing"],
        "melody_raw": ["note_candidates.json missing"],
    }
    if note_candidates_path is None or not note_candidates_path.exists():
        return empty_sources, empty_warnings
    payload = _read_json(note_candidates_path)
    if payload is None:
        return empty_sources, {
            "all": ["note_candidates.json unreadable"],
            "selected": ["note_candidates.json unreadable"],
            "melody_raw": ["note_candidates.json unreadable"],
        }
    selected_payload = None
    melody_raw_payload = None
    all_payload = None
    if isinstance(payload, dict):
        melody = payload.get("melody_candidates")
        if isinstance(melody, dict):
            melody_raw_payload = melody.get("notes") if isinstance(melody.get("notes"), list) else None
            selected_payload = melody.get("selected_notes") if isinstance(melody.get("selected_notes"), list) else None
        if all_payload is None and isinstance(payload.get("notes"), list):
            all_payload = payload.get("notes")
        if selected_payload is None and isinstance(payload.get("selected_notes"), list):
            selected_payload = payload.get("selected_notes")
    all_payload = melody_raw_payload if melody_raw_payload is not None else all_payload
    if all_payload is None:
        all_payload = selected_payload if selected_payload is not None else _preferred_candidate_note_payload(payload)
    sources = {
        "all": _candidate_tuples_to_pitch_events(_extract_candidate_notes_from_payload(all_payload)),
        "selected": _candidate_tuples_to_pitch_events(_extract_candidate_notes_from_payload(selected_payload)) if selected_payload is not None else [],
        "melody_raw": _candidate_tuples_to_pitch_events(_extract_candidate_notes_from_payload(melody_raw_payload)) if melody_raw_payload is not None else [],
    }
    warnings = {"all": [], "selected": [], "melody_raw": []}
    if selected_payload is None:
        warnings["selected"].append("note_candidates selected_notes unavailable")
    if melody_raw_payload is None:
        warnings["melody_raw"].append("note_candidates melody raw notes unavailable")
    return sources, warnings


def _extract_candidate_notes_from_payload(payload: Any) -> list[tuple[float | None, float | None, float | None]]:
    candidates: list[tuple[float | None, float | None, float | None]] = []
    for item in _walk_note_like_items(payload):
        start = _as_float(_first_present(item, "start_time", "onset_sec", "start_sec", "start", "time_sec"))
        end = _as_float(_first_present(item, "end_time", "offset_sec", "end_sec", "end"))
        duration = _as_float(_first_present(item, "duration_sec", "duration"))
        if duration is None and start is not None and end is not None:
            duration = max(0.0, end - start)
        pitch = _candidate_pitch_midi(item)
        if start is not None or duration is not None or pitch is not None:
            candidates.append((start, duration, pitch))
    return candidates


def _candidate_tuples_to_pitch_events(candidates: list[tuple[float | None, float | None, float | None]]) -> list[dict[str, Any]]:
    return [{"pitch": pitch, "duration_sec": duration} for _, duration, pitch in candidates]


def _weighted_pitch_histogram(pitches: list[float], weights: list[float]) -> dict[str, Any]:
    count_by_midi: dict[str, int] = {}
    weight_by_midi_raw: dict[str, float] = {}
    for pitch, weight in zip(pitches, weights):
        bin_pitch = int(round(pitch))
        key = str(bin_pitch)
        count_by_midi[key] = count_by_midi.get(key, 0) + 1
        weight_by_midi_raw[key] = weight_by_midi_raw.get(key, 0.0) + float(weight)
    total_weight = sum(weight_by_midi_raw.values())
    weight_by_midi = {key: _round_float(value) for key, value in sorted(weight_by_midi_raw.items(), key=lambda item: int(item[0]))}
    weight_ratio_by_midi = {
        key: _round_float(value / total_weight) if total_weight > 0.0 else 0.0
        for key, value in sorted(weight_by_midi_raw.items(), key=lambda item: int(item[0]))
    }
    top_bins = sorted(
        [
            {
                "midi_pitch": int(key),
                "pitch_name": _midi_pitch_name(int(key)),
                "count": count_by_midi.get(key, 0),
                "weight": _round_float(value),
                "weight_ratio": _round_float(value / total_weight) if total_weight > 0.0 else 0.0,
            }
            for key, value in weight_by_midi_raw.items()
        ],
        key=lambda item: (-float(item["weight"]), int(item["midi_pitch"])),
    )[:8]
    return {
        "bin_size_semitones": 1,
        "count_by_midi": {key: count_by_midi[key] for key in sorted(count_by_midi, key=lambda value: int(value))},
        "weight_by_midi": weight_by_midi,
        "weight_ratio_by_midi": weight_ratio_by_midi,
        "top_bins": top_bins,
    }


def _pitch_range_payload(pitches: list[float], weights: list[float]) -> dict[str, Any]:
    if not pitches:
        return {"min": None, "max": None, "span": None, "p05": None, "p50": None, "p95": None, "robust_span": None}
    min_pitch = min(pitches)
    max_pitch = max(pitches)
    p05 = _weighted_percentile(pitches, weights, 0.05)
    p50 = _weighted_percentile(pitches, weights, 0.50)
    p95 = _weighted_percentile(pitches, weights, 0.95)
    return {
        "min": _round_optional(min_pitch),
        "max": _round_optional(max_pitch),
        "span": _round_optional(max_pitch - min_pitch),
        "p05": _round_optional(p05),
        "p50": _round_optional(p50),
        "p95": _round_optional(p95),
        "robust_span": _round_optional((p95 - p05) if p05 is not None and p95 is not None else None),
    }


def _weighted_percentile(values: list[float], weights: list[float], percentile: float) -> float | None:
    pairs = sorted(
        [(float(value), max(0.0, float(weight))) for value, weight in zip(values, weights)],
        key=lambda pair: pair[0],
    )
    if not pairs:
        return None
    total = sum(weight for _, weight in pairs)
    if total <= 0.0:
        return pairs[min(len(pairs) - 1, max(0, int(round(percentile * (len(pairs) - 1)))))][0]
    threshold = total * percentile
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _weighted_mean(values: list[float], weights: list[float]) -> float | None:
    total = sum(weights)
    if not values or total <= 0.0:
        return None
    return sum(value * weight for value, weight in zip(values, weights)) / total


def _pitch_pairwise_overlap(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    if not first.get("available"):
        warnings.append(f"{first.get('source_kind', 'first')}: unavailable")
    if not second.get("available"):
        warnings.append(f"{second.get('source_kind', 'second')}: unavailable")
    first_hist = (((first.get("histogram") or {}).get("weight_ratio_by_midi")) or {}) if isinstance(first, dict) else {}
    second_hist = (((second.get("histogram") or {}).get("weight_ratio_by_midi")) or {}) if isinstance(second, dict) else {}
    raw_overlap = _pitch_histogram_overlap(first_hist, second_hist)
    first_range = first.get("pitch_range") if isinstance(first.get("pitch_range"), dict) else {}
    second_range = second.get("pitch_range") if isinstance(second.get("pitch_range"), dict) else {}
    range_iou = _robust_range_iou(first_range, second_range)
    first_median = _as_float(first.get("median_pitch"))
    second_median = _as_float(second.get("median_pitch"))
    median_delta = None if first_median is None or second_median is None else second_median - first_median
    best_shift = None
    best_overlap = raw_overlap
    for shift in [-24, -12, 0, 12, 24]:
        shifted = _shift_pitch_histogram(second_hist, shift)
        overlap = _pitch_histogram_overlap(first_hist, shifted)
        if overlap is None:
            continue
        if best_overlap is None or overlap > best_overlap:
            best_overlap = overlap
            best_shift = shift
    if best_shift is None and raw_overlap is not None:
        best_shift = 0
    gain = None if raw_overlap is None or best_overlap is None else best_overlap - raw_overlap
    return {
        "raw_histogram_overlap": _round_optional(raw_overlap),
        "range_iou": _round_optional(range_iou),
        "median_delta_b_minus_a_semitones": _round_optional(median_delta),
        "best_octave_shift": best_shift,
        "best_octave_shifted_overlap": _round_optional(best_overlap),
        "octave_shift_overlap_gain": _round_optional(gain),
        "warnings": warnings,
    }


def _pitch_histogram_overlap(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    if not first or not second:
        return None
    keys = set(first) | set(second)
    if not keys:
        return None
    return sum(min(_as_float(first.get(key)) or 0.0, _as_float(second.get(key)) or 0.0) for key in keys)


def _shift_pitch_histogram(histogram: dict[str, Any], shift: int) -> dict[str, float]:
    shifted: dict[str, float] = {}
    for key, value in histogram.items():
        try:
            shifted_key = str(int(key) + shift)
        except ValueError:
            continue
        shifted[shifted_key] = shifted.get(shifted_key, 0.0) + (_as_float(value) or 0.0)
    return shifted


def _robust_range_iou(first_range: dict[str, Any], second_range: dict[str, Any]) -> float | None:
    first_min = _as_float(first_range.get("p05"))
    first_max = _as_float(first_range.get("p95"))
    second_min = _as_float(second_range.get("p05"))
    second_max = _as_float(second_range.get("p95"))
    if first_min is None or first_max is None or second_min is None or second_max is None:
        return None
    if first_max <= first_min:
        first_min -= 0.5
        first_max += 0.5
    if second_max <= second_min:
        second_min -= 0.5
        second_max += 0.5
    intersection = max(0.0, min(first_max, second_max) - max(first_min, second_min))
    union = max(first_max, second_max) - min(first_min, second_min)
    return _safe_divide(intersection, union)


def _pitch_candidate_funnel(
    *,
    f0: dict[str, Any],
    all_candidates: dict[str, Any],
    selected_candidates: dict[str, Any],
    predicted: dict[str, Any],
) -> dict[str, Any]:
    all_count = _as_int(all_candidates.get("valid_pitch_count")) or 0
    selected_count = _as_int(selected_candidates.get("valid_pitch_count")) or 0
    predicted_count = _as_int(predicted.get("valid_pitch_count")) or 0
    all_duration = _as_float(all_candidates.get("duration_sec"))
    selected_duration = _as_float(selected_candidates.get("duration_sec"))
    predicted_duration = _as_float(predicted.get("duration_sec"))
    return {
        "f0_voiced_duration_sec": f0.get("duration_sec"),
        "note_candidates_all_count": all_count,
        "note_candidates_all_duration_sec": all_candidates.get("duration_sec"),
        "note_candidates_selected_count": selected_count if selected_candidates.get("available") else None,
        "note_candidates_selected_duration_sec": selected_candidates.get("duration_sec") if selected_candidates.get("available") else None,
        "predicted_midi_count": predicted_count,
        "predicted_midi_duration_sec": predicted.get("duration_sec"),
        "selected_to_all_count_ratio": _safe_divide(selected_count, all_count) if selected_candidates.get("available") else None,
        "selected_to_all_duration_ratio": _safe_divide(selected_duration, all_duration) if selected_candidates.get("available") else None,
        "predicted_to_candidate_count_ratio": _safe_divide(predicted_count, all_count),
        "predicted_to_candidate_duration_ratio": _safe_divide(predicted_duration, all_duration),
    }


def _derive_pitch_distribution_flags(
    *,
    sources: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
    candidate_funnel: dict[str, Any],
) -> dict[str, Any]:
    thresholds = {
        "low_overlap": 0.25,
        "medium_overlap": 0.45,
        "high_overlap": 0.55,
        "octave_gain": 0.25,
        "near_octave_tolerance": 1.5,
        "low_retention_ratio": 0.35,
        "min_f0_voiced_duration_sec": 1.0,
        "min_expected_notes": 5,
    }
    flags = {
        "possible_f0_octave_or_reference_pitch_mismatch": _pitch_flag_f0_octave_or_reference(sources, pairwise, thresholds),
        "possible_f0_to_note_candidate_loss": _pitch_flag_f0_to_candidate_loss(sources, pairwise, candidate_funnel, thresholds),
        "possible_melody_selector_or_filter_loss": _pitch_flag_melody_selector_or_filter_loss(sources, pairwise, candidate_funnel, thresholds),
        "possible_reference_strategy_or_pitch_source_mismatch": _pitch_flag_reference_strategy_or_pitch_source_mismatch(sources, pairwise, thresholds),
    }
    return flags


def _pitch_flag(triggered: bool, confidence: str, subtype: str, evidence: list[str], warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "triggered": bool(triggered),
        "confidence": confidence,
        "subtype": subtype,
        "evidence": evidence,
        "warnings": list(warnings or []),
    }


def _pitch_flag_f0_octave_or_reference(
    sources: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    expected = sources.get("expected_notes", {})
    f0 = sources.get("f0_frames", {})
    pair = pairwise.get("expected_vs_f0", {})
    warnings: list[str] = []
    if (_as_int(expected.get("valid_pitch_count")) or 0) < int(thresholds["min_expected_notes"]):
        warnings.append("expected note count below threshold")
    if not f0.get("available"):
        warnings.append("F0 unavailable")
    raw = _as_float(pair.get("raw_histogram_overlap"))
    gain = _as_float(pair.get("octave_shift_overlap_gain"))
    shift = _as_int(pair.get("best_octave_shift"))
    median_delta = _as_float(pair.get("median_delta_b_minus_a_semitones"))
    near_octave = _median_delta_near_octave(median_delta, thresholds["near_octave_tolerance"])
    shifted_high = gain is not None and gain >= thresholds["octave_gain"] and shift in {-24, -12, 12, 24}
    triggered = (
        not warnings
        and raw is not None
        and raw < thresholds["low_overlap"]
        and (shifted_high or near_octave)
    )
    f0_predicted = _as_float((pairwise.get("f0_vs_predicted") or {}).get("raw_histogram_overlap"))
    f0_candidates = _as_float((pairwise.get("f0_vs_note_candidates") or {}).get("raw_histogram_overlap"))
    f0_predicted = f0_predicted if f0_predicted is not None else _as_float((pairwise.get("note_candidates_vs_predicted") or {}).get("raw_histogram_overlap"))
    subtype = "octave_shift_suspected"
    if triggered and ((f0_candidates is not None and f0_candidates >= thresholds["high_overlap"]) or (f0_predicted is not None and f0_predicted >= thresholds["high_overlap"])):
        subtype = "ambiguous_octave_or_reference"
    evidence = [
        f"expected_vs_f0 raw_overlap={_fmt(raw)}",
        f"expected_vs_f0 median_delta={_fmt(median_delta)} semitones",
        f"best_octave_shift={_fmt(shift)} overlap={_fmt(pair.get('best_octave_shifted_overlap'))} gain={_fmt(gain)}",
    ]
    return _pitch_flag(triggered, "medium" if triggered else "low", subtype if triggered else "not_triggered", evidence, warnings)


def _pitch_flag_f0_to_candidate_loss(
    sources: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
    candidate_funnel: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    f0 = sources.get("f0_frames", {})
    candidates = sources.get("note_candidates_all", {})
    f0_duration = _as_float(candidate_funnel.get("f0_voiced_duration_sec"))
    expected_f0 = pairwise.get("expected_vs_f0", {})
    f0_candidates = pairwise.get("f0_vs_note_candidates", {})
    expected_f0_overlap = _best_pitch_overlap(expected_f0)
    f0_candidates_overlap = _as_float(f0_candidates.get("raw_histogram_overlap"))
    candidate_count = _as_int(candidates.get("valid_pitch_count")) or 0
    warnings: list[str] = []
    if not f0.get("available") or f0_duration is None or f0_duration < thresholds["min_f0_voiced_duration_sec"]:
        warnings.append("F0 voiced duration below threshold or unavailable")
    f0_reasonable = expected_f0_overlap is not None and expected_f0_overlap >= thresholds["medium_overlap"]
    candidate_missing_or_low = (not candidates.get("available")) or candidate_count < 3 or (f0_candidates_overlap is not None and f0_candidates_overlap < thresholds["low_overlap"])
    triggered = not warnings and f0_reasonable and candidate_missing_or_low
    evidence = [
        f"f0_voiced_duration_sec={_fmt(f0_duration)}",
        f"expected_vs_f0 best_overlap={_fmt(expected_f0_overlap)}",
        f"candidate_count={candidate_count}",
        f"f0_vs_note_candidates raw_overlap={_fmt(f0_candidates_overlap)}",
    ]
    subtype = "candidate_extraction_loss" if triggered else "not_triggered"
    return _pitch_flag(triggered, "medium" if triggered else "low", subtype, evidence, warnings)


def _pitch_flag_melody_selector_or_filter_loss(
    sources: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
    candidate_funnel: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    candidates = sources.get("note_candidates_all", {})
    predicted = sources.get("predicted_notes", {})
    selected = sources.get("note_candidates_selected", {})
    expected_candidates = pairwise.get("expected_vs_note_candidates", {})
    f0_candidates = pairwise.get("f0_vs_note_candidates", {})
    candidates_predicted = pairwise.get("note_candidates_vs_predicted", {})
    candidate_alignment = max(
        value for value in [
            _best_pitch_overlap(expected_candidates),
            _as_float(f0_candidates.get("raw_histogram_overlap")),
        ] if value is not None
    ) if any(value is not None for value in [_best_pitch_overlap(expected_candidates), _as_float(f0_candidates.get("raw_histogram_overlap"))]) else None
    selected_ratio = _as_float(candidate_funnel.get("selected_to_all_count_ratio"))
    predicted_ratio = _as_float(candidate_funnel.get("predicted_to_candidate_count_ratio"))
    cand_pred_overlap = _as_float(candidates_predicted.get("raw_histogram_overlap"))
    warnings: list[str] = []
    if not candidates.get("available"):
        warnings.append("note candidates unavailable")
    if not predicted.get("available"):
        warnings.append("predicted notes unavailable")
    aligned = candidate_alignment is not None and candidate_alignment >= thresholds["medium_overlap"]
    selected_loss = selected.get("available") and selected_ratio is not None and selected_ratio < thresholds["low_retention_ratio"]
    predicted_loss = predicted_ratio is not None and predicted_ratio < thresholds["low_retention_ratio"]
    overlap_loss = cand_pred_overlap is not None and cand_pred_overlap < thresholds["low_overlap"]
    triggered = not warnings and aligned and (selected_loss or predicted_loss or overlap_loss)
    subtype = "unknown_filter_loss"
    if selected_loss:
        subtype = "melody_selector_loss"
    elif predicted_loss or overlap_loss:
        subtype = "post_selector_quantizer_or_export_loss"
    evidence = [
        f"candidate_alignment_overlap={_fmt(candidate_alignment)}",
        f"selected_to_all_count_ratio={_fmt(selected_ratio)}",
        f"predicted_to_candidate_count_ratio={_fmt(predicted_ratio)}",
        f"note_candidates_vs_predicted raw_overlap={_fmt(cand_pred_overlap)}",
    ]
    return _pitch_flag(triggered, "medium" if triggered else "low", subtype if triggered else "not_triggered", evidence, warnings)


def _pitch_flag_reference_strategy_or_pitch_source_mismatch(
    sources: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    expected = sources.get("expected_notes", {})
    warnings: list[str] = []
    if (_as_int(expected.get("valid_pitch_count")) or 0) < int(thresholds["min_expected_notes"]):
        warnings.append("expected note count below threshold")
    expected_pairs = [
        pairwise.get("expected_vs_predicted", {}),
        pairwise.get("expected_vs_f0", {}),
        pairwise.get("expected_vs_note_candidates", {}),
    ]
    expected_overlaps = [_as_float(pair.get("raw_histogram_overlap")) for pair in expected_pairs]
    expected_low = [value for value in expected_overlaps if value is not None]
    not_simple_octave = all((_as_float(pair.get("octave_shift_overlap_gain")) or 0.0) < thresholds["octave_gain"] for pair in expected_pairs)
    internal_overlaps = [
        _as_float((pairwise.get("f0_vs_note_candidates") or {}).get("raw_histogram_overlap")),
        _as_float((pairwise.get("note_candidates_vs_predicted") or {}).get("raw_histogram_overlap")),
    ]
    internal_values = [value for value in internal_overlaps if value is not None]
    triggered = (
        not warnings
        and bool(expected_low)
        and all(value < thresholds["low_overlap"] for value in expected_low)
        and not_simple_octave
        and bool(internal_values)
        and all(value >= thresholds["medium_overlap"] for value in internal_values)
    )
    evidence = [
        f"expected raw overlaps={[_round_optional(value) for value in expected_overlaps]}",
        f"internal overlaps={[_round_optional(value) for value in internal_overlaps]}",
        f"not_simple_octave={str(not_simple_octave).lower()}",
    ]
    return _pitch_flag(triggered, "medium" if triggered else "low", "reference_strategy_or_pitch_source_mismatch" if triggered else "not_triggered", evidence, warnings)


def _median_delta_near_octave(delta: float | None, tolerance: float) -> bool:
    if delta is None:
        return False
    return any(abs(abs(delta) - octave) <= tolerance for octave in [12.0, 24.0])


def _best_pitch_overlap(pair: dict[str, Any]) -> float | None:
    values = [
        _as_float(pair.get("raw_histogram_overlap")),
        _as_float(pair.get("best_octave_shifted_overlap")),
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _collect_pitch_distribution_warnings(
    *,
    sources: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
    flags: dict[str, dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    for source in sources.values():
        warnings.extend(str(warning) for warning in source.get("warnings") or [])
    for pair in pairwise.values():
        warnings.extend(str(warning) for warning in pair.get("warnings") or [])
    for flag in flags.values():
        warnings.extend(str(warning) for warning in flag.get("warnings") or [])
    seen: set[str] = set()
    unique: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            unique.append(warning)
    return unique


def _derive_match_diagnostics(
    *,
    match_debug: dict[str, Any] | None,
    alignment_debug: dict[str, Any] | None,
    expected_note_count: int,
    predicted_note_count: int,
) -> dict[str, Any]:
    raw_matched = _as_int((match_debug or {}).get("matched_count"))
    if raw_matched is None:
        raw_matched = _as_int(((match_debug or {}).get("metrics") or {}).get("matched_note_count"))
    shift_snapshot = (alignment_debug or {}).get("shift_corrected_matching_snapshot")
    shift_matched = None
    if isinstance(shift_snapshot, dict):
        shift_matched = _as_int(shift_snapshot.get("matched_count"))
        if shift_matched is None:
            shift_matched = _as_int((shift_snapshot.get("metrics") or {}).get("matched_note_count"))
    if shift_matched is None:
        shift_matched = _as_int((alignment_debug or {}).get("shift_corrected_matched"))
    unmatched_expected = None if raw_matched is None else max(0, expected_note_count - raw_matched)
    unmatched_predicted = None if raw_matched is None else max(0, predicted_note_count - raw_matched)
    return {
        "available": match_debug is not None,
        "raw_matched_count": raw_matched,
        "shift_matched_count": shift_matched,
        "unmatched_expected_count": unmatched_expected,
        "unmatched_predicted_count": unmatched_predicted,
        "raw_match_rate_vs_expected": _safe_divide(raw_matched, expected_note_count),
        "raw_match_rate_vs_predicted": _safe_divide(raw_matched, predicted_note_count),
        "shift_match_rate_vs_expected": _safe_divide(shift_matched, expected_note_count),
        "shift_match_rate_vs_predicted": _safe_divide(shift_matched, predicted_note_count),
    }


def _match_note_indices(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig,
    predicted_pitch_shift: int = 0,
    predicted_time_shift_sec: float = 0.0,
) -> list[tuple[int, int]]:
    candidate_edges: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(expected_notes):
        for predicted_index, predicted in enumerate(predicted_notes):
            evaluated_predicted = _shift_debug_note(
                predicted,
                pitch_shift=predicted_pitch_shift,
                time_shift=predicted_time_shift_sec,
            )
            onset_delta = abs(expected.start - evaluated_predicted.start)
            if onset_delta > config.onset_tolerance_sec:
                continue
            pitch_delta = abs(expected.pitch - evaluated_predicted.pitch)
            if pitch_delta <= config.pitch_tolerance_semitones:
                pitch_cost = pitch_delta
            elif pitch_delta in {1, config.octave_tolerance_semitones}:
                pitch_cost = pitch_delta + 100
            else:
                continue
            duration_cost = 1.0 - _duration_iou(expected, evaluated_predicted)
            candidate_edges.append((onset_delta + pitch_cost + duration_cost * 0.01, expected_index, predicted_index))
    candidate_edges.sort(key=lambda edge: edge[0])
    used_expected: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[tuple[int, int]] = []
    for _, expected_index, predicted_index in candidate_edges:
        if expected_index in used_expected or predicted_index in used_predicted:
            continue
        used_expected.add(expected_index)
        used_predicted.add(predicted_index)
        matches.append((expected_index, predicted_index))
    matches.sort(key=lambda pair: (expected_notes[pair[0]].start, predicted_notes[pair[1]].start, expected_notes[pair[0]].pitch))
    return matches


def _shift_debug_notes(notes: list[NoteEvent], *, pitch_shift: int = 0, time_shift: float = 0.0) -> list[NoteEvent]:
    return [_shift_debug_note(note, pitch_shift=pitch_shift, time_shift=time_shift) for note in notes]


def _shift_debug_note(note: NoteEvent, *, pitch_shift: int = 0, time_shift: float = 0.0) -> NoteEvent:
    return NoteEvent(
        start=float(note.start) + float(time_shift),
        end=float(note.end) + float(time_shift),
        pitch=int(note.pitch) + int(pitch_shift),
        velocity=int(note.velocity),
        track_index=note.track_index,
        channel=note.channel,
        program=note.program,
    )


def _duration_iou(expected: NoteEvent, predicted: NoteEvent) -> float:
    intersection = max(0.0, min(expected.end, predicted.end) - max(expected.start, predicted.start))
    union = max(expected.end, predicted.end) - min(expected.start, predicted.start)
    if union <= 0 or math.isclose(union, 0.0):
        return 0.0
    return intersection / union


def _alignment_value(alignment: dict[str, Any], smart: dict[str, Any], key: str) -> Any:
    if key in alignment:
        return alignment.get(key)
    return smart.get(key)


def _load_f0_points(f0_track_path: Path | None) -> list[tuple[float, float]]:
    if f0_track_path is None or not f0_track_path.exists():
        return []
    payload = _read_json(f0_track_path)
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, list):
        return []
    points: list[tuple[float, float]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        if frame.get("voiced") is False:
            continue
        time_sec = _as_float(_first_present(frame, "time_sec", "time", "t"))
        pitch_midi = _as_float(_first_present(frame, "pitch_midi", "midi_pitch"))
        if pitch_midi is None:
            frequency_hz = _as_float(_first_present(frame, "frequency_hz", "f0_hz", "frequency"))
            pitch_midi = _hz_to_midi(frequency_hz) if frequency_hz and frequency_hz > 0 else None
        if time_sec is not None and pitch_midi is not None:
            points.append((time_sec, pitch_midi))
    return points


def _load_vocal_activity_segments(vocal_activity_path: Path | None) -> list[tuple[float, float, bool]]:
    if vocal_activity_path is None or not vocal_activity_path.exists():
        return []
    payload = _read_json(vocal_activity_path)
    segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(segments, list):
        return []
    parsed: list[tuple[float, float, bool]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _as_float(_first_present(segment, "start_time", "start_sec", "start"))
        end = _as_float(_first_present(segment, "end_time", "end_sec", "end"))
        state = str(segment.get("state") or segment.get("label") or "").lower()
        active = bool(segment.get("active")) or state in {"active", "voiced", "vocal", "speech", "singing"}
        if start is not None and end is not None and end > start:
            parsed.append((start, end, active))
    return parsed


def _draw_vocal_activity_background(axis: Any, vocal_segments: list[tuple[float, float, bool]]) -> None:
    for start, end, active in vocal_segments:
        if active:
            axis.axvspan(start, end, color="#2ca02c", alpha=0.08)


def _draw_notes(axis: Any, notes: list[NoteEvent], *, color: str, y_offset: float, label: str) -> None:
    for index, note in enumerate(notes):
        axis.hlines(
            y=float(note.pitch) + y_offset,
            xmin=float(note.start),
            xmax=float(note.end),
            color=color,
            linewidth=1.2,
            alpha=0.7,
            label=label if index == 0 else None,
        )


def _draw_match_markers(axis: Any, match_debug: dict[str, Any], expected_notes: list[NoteEvent], predicted_notes: list[NoteEvent]) -> None:
    matched_expected = {int(pair["expected_index"]) for pair in match_debug.get("matched_pairs") or [] if isinstance(pair, dict)}
    matched_predicted = {int(pair["predicted_index"]) for pair in match_debug.get("matched_pairs") or [] if isinstance(pair, dict)}
    if matched_expected:
        axis.scatter(
            [expected_notes[index].start for index in matched_expected if index < len(expected_notes)],
            [expected_notes[index].pitch + 0.35 for index in matched_expected if index < len(expected_notes)],
            marker="o",
            s=18,
            color="#2ca02c",
            label="raw matched reference",
            zorder=4,
        )
    unmatched_expected = [index for index in range(len(expected_notes)) if index not in matched_expected]
    if unmatched_expected:
        axis.scatter(
            [expected_notes[index].start for index in unmatched_expected],
            [expected_notes[index].pitch - 0.35 for index in unmatched_expected],
            marker="x",
            s=14,
            color="#d62728",
            label="raw unmatched reference",
            zorder=4,
        )
    unmatched_predicted = [index for index in range(len(predicted_notes)) if index not in matched_predicted]
    if unmatched_predicted:
        axis.scatter(
            [predicted_notes[index].start for index in unmatched_predicted],
            [predicted_notes[index].pitch + 0.55 for index in unmatched_predicted],
            marker="x",
            s=14,
            color="#ff7f0e",
            label="raw unmatched predicted",
            zorder=4,
        )


def _draw_shift_match_markers(axis: Any, alignment_debug: dict[str, Any], predicted_notes: list[NoteEvent]) -> None:
    snapshot = alignment_debug.get("shift_corrected_matching_snapshot")
    if not isinstance(snapshot, dict):
        return
    shift = _as_float(snapshot.get("predicted_time_shift_sec")) or 0.0
    pitch_shift = _as_int(snapshot.get("predicted_pitch_shift_semitones")) or 0
    matched_predicted = {
        int(pair["predicted_index"])
        for pair in snapshot.get("matched_pairs") or []
        if isinstance(pair, dict) and "predicted_index" in pair
    }
    if not matched_predicted:
        return
    axis.scatter(
        [predicted_notes[index].start + shift for index in matched_predicted if index < len(predicted_notes)],
        [predicted_notes[index].pitch + pitch_shift + 0.8 for index in matched_predicted if index < len(predicted_notes)],
        marker="^",
        s=24,
        color="#9467bd",
        label="shift-corrected matched predicted",
        zorder=5,
    )


def _draw_delay_and_shift_markers(
    axis: Any,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    metrics_payload: dict[str, Any],
    alignment_debug: dict[str, Any],
) -> None:
    if expected_notes:
        expected_first = min(note.start for note in expected_notes)
        axis.axvline(expected_first, color="#1f77b4", linestyle="--", linewidth=1.0, alpha=0.75)
    else:
        expected_first = None
    if predicted_notes:
        predicted_first = min(note.start for note in predicted_notes)
        axis.axvline(predicted_first, color="#ff7f0e", linestyle="--", linewidth=1.0, alpha=0.75)
    else:
        predicted_first = None
    audibility = metrics_payload.get("audibility") if isinstance(metrics_payload.get("audibility"), dict) else {}
    first_note_delay = _as_float(audibility.get("first_note_delay_sec"))
    shift = _as_float(alignment_debug.get("pred_to_exp_shift_sec"))
    text_parts = []
    if first_note_delay is not None:
        text_parts.append(f"first_note_delay={first_note_delay:.3f}s")
    elif expected_first is not None and predicted_first is not None:
        text_parts.append(f"first_note_delay={predicted_first - expected_first:.3f}s")
    if shift is not None:
        text_parts.append(f"pred_to_exp_shift={shift:.3f}s")
    if text_parts:
        axis.text(
            0.01,
            0.98,
            "\n".join(text_parts),
            transform=axis.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "#bbbbbb"},
        )


def _draw_derived_diagnostics_box(axis: Any, derived_diagnostics: dict[str, Any] | None) -> None:
    if not isinstance(derived_diagnostics, dict):
        return
    notes = derived_diagnostics.get("notes") if isinstance(derived_diagnostics.get("notes"), dict) else {}
    match = derived_diagnostics.get("match") if isinstance(derived_diagnostics.get("match"), dict) else {}
    continuity = derived_diagnostics.get("continuity") if isinstance(derived_diagnostics.get("continuity"), dict) else {}
    pitch_distribution = derived_diagnostics.get("pitch_distribution") if isinstance(derived_diagnostics.get("pitch_distribution"), dict) else {}
    pairwise = pitch_distribution.get("pairwise") if isinstance(pitch_distribution.get("pairwise"), dict) else {}
    expected_vs_predicted = pairwise.get("expected_vs_predicted") if isinstance(pairwise.get("expected_vs_predicted"), dict) else {}
    stage = derived_diagnostics.get("preliminary_failure_stage_v2")
    text = "\n".join(
        [
            f"expected={_fmt(notes.get('expected_note_count'))}",
            f"predicted={_fmt(notes.get('predicted_note_count'))}",
            f"gap50={_fmt(continuity.get('gap50_ratio'))}",
            f"short={_fmt(continuity.get('short_note_ratio'))}",
            f"jump={_fmt(continuity.get('large_jump_ratio'))}",
            f"raw_matched={_fmt(match.get('raw_matched_count'))}",
            f"shift_matched={_fmt(match.get('shift_matched_count'))}",
            f"exp_med={_fmt((pitch_distribution.get('expected_notes') or {}).get('median_pitch'))}",
            f"pred_med={_fmt((pitch_distribution.get('predicted_notes') or {}).get('median_pitch'))}",
            f"f0_med={_fmt((pitch_distribution.get('f0_frames') or {}).get('median_pitch'))}",
            f"dist_delta={_fmt(expected_vs_predicted.get('median_delta_b_minus_a_semitones'))}",
            f"pitch_diag={_fmt(pitch_distribution.get('preliminary_pitch_diagnosis'))}",
            f"stage_v2={_fmt(stage)}",
        ]
    )
    axis.text(
        0.99,
        0.02,
        text,
        transform=axis.transAxes,
        va="bottom",
        ha="right",
        fontsize=8,
        bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "#bbbbbb"},
    )


def _hz_to_midi(frequency_hz: float | None) -> float | None:
    if frequency_hz is None or frequency_hz <= 0:
        return None
    return 69.0 + 12.0 * math.log2(frequency_hz / 440.0)


def _frame_is_voiced(frame: dict[str, Any]) -> bool:
    voiced = _first_present(frame, "voiced", "is_voiced")
    if voiced is not None:
        return bool(voiced)
    state = str(_first_present(frame, "state", "label") or "").lower()
    if state in {"voiced", "active", "vocal", "singing"}:
        return True
    pitch = _frame_pitch_midi(frame)
    frequency = _as_float(_first_present(frame, "frequency_hz", "f0_hz", "frequency", "f0"))
    return pitch is not None or (frequency is not None and frequency > 0)


def _frame_pitch_midi(frame: dict[str, Any]) -> float | None:
    pitch_midi = _as_float(_first_present(frame, "pitch_midi", "midi_pitch"))
    if pitch_midi is not None:
        return pitch_midi
    frequency_hz = _as_float(_first_present(frame, "frequency_hz", "f0_hz", "frequency", "f0"))
    return _hz_to_midi(frequency_hz) if frequency_hz is not None and frequency_hz > 0 else None


def _extract_candidate_notes(payload: Any) -> list[tuple[float | None, float | None, float | None]]:
    payload = _preferred_candidate_note_payload(payload)
    candidates: list[tuple[float | None, float | None, float | None]] = []
    for item in _walk_note_like_items(payload):
        start = _as_float(_first_present(item, "start_time", "onset_sec", "start_sec", "start", "time_sec"))
        end = _as_float(_first_present(item, "end_time", "offset_sec", "end_sec", "end"))
        duration = _as_float(_first_present(item, "duration_sec", "duration"))
        if duration is None and start is not None and end is not None:
            duration = max(0.0, end - start)
        pitch = _candidate_pitch_midi(item)
        if start is not None or duration is not None or pitch is not None:
            candidates.append((start, duration, pitch))
    return candidates


def _preferred_candidate_note_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    melody = payload.get("melody_candidates")
    if isinstance(melody, dict):
        notes = melody.get("notes")
        if isinstance(notes, list):
            return notes
        selected_notes = melody.get("selected_notes")
        if isinstance(selected_notes, list):
            return selected_notes
    notes = payload.get("notes")
    if isinstance(notes, list):
        return notes
    selected_notes = payload.get("selected_notes")
    if isinstance(selected_notes, list):
        return selected_notes
    return payload


def _walk_note_like_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if _dict_looks_like_note(payload):
            items.append(payload)
        for value in payload.values():
            items.extend(_walk_note_like_items(value))
    elif isinstance(payload, list):
        for value in payload:
            items.extend(_walk_note_like_items(value))
    return items


def _dict_looks_like_note(payload: dict[str, Any]) -> bool:
    has_time = any(key in payload for key in ["start_time", "start_time_sec", "onset_sec", "start_sec", "start", "time_sec"])
    has_pitch = any(
        key in payload
        for key in ["pitch", "midi_pitch", "pitch_midi", "pitch_midi_float", "pitch_center_midi", "midi_float", "frequency_hz", "f0_hz"]
    )
    return has_time and has_pitch


def _candidate_pitch_midi(payload: dict[str, Any]) -> float | None:
    direct = _as_float(_first_present(payload, "midi_pitch", "pitch_midi", "pitch_midi_float", "pitch_center_midi", "midi_float"))
    if direct is not None:
        return direct
    pitch_value = _first_present(payload, "pitch", "note")
    numeric = _as_float(pitch_value)
    if numeric is not None:
        return numeric
    if isinstance(pitch_value, str):
        parsed = _pitch_name_to_midi(pitch_value)
        if parsed is not None:
            return parsed
    frequency = _as_float(_first_present(payload, "frequency_hz", "f0_hz", "frequency"))
    return _hz_to_midi(frequency) if frequency is not None and frequency > 0 else None


def _pitch_name_to_midi(value: str) -> float | None:
    match = re.match(r"^\s*([A-Ga-g])([#b]?)(-?\d+)\s*$", value)
    if not match:
        return None
    note_name, accidental, octave_text = match.groups()
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[note_name.upper()]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1
    return float((int(octave_text) + 1) * 12 + semitone)


def _preliminary_failure_stage_v2(
    *,
    notes: dict[str, Any],
    f0: dict[str, Any],
    vocal_activity: dict[str, Any],
    note_candidates: dict[str, Any],
    match: dict[str, Any],
    coverage: float | None,
    expected_available: bool,
    predicted_available: bool,
    match_available: bool,
) -> str:
    if not expected_available or not predicted_available or not match_available:
        return "missing_core_artifacts"
    time_overlap = _as_float(notes.get("expected_predicted_time_overlap_ratio"))
    if time_overlap is not None and time_overlap < 0.35:
        return "possible_reference_or_version_mismatch"
    active_ratio = _as_float(vocal_activity.get("vocal_activity_active_ratio"))
    if (coverage is not None and coverage < 0.20) or (active_ratio is not None and active_ratio < 0.12):
        return "possible_vocal_activity_or_separation"
    f0_voiced_ratio = _as_float(f0.get("f0_voiced_ratio"))
    f0_confidence = _as_float(f0.get("f0_median_confidence"))
    if (f0_voiced_ratio is not None and f0_voiced_ratio < 0.10) or (f0_confidence is not None and f0_confidence < 0.10):
        return "possible_f0_extraction_failure"
    candidate_to_pred = _as_float(note_candidates.get("candidate_to_predicted_ratio"))
    pred_exp_ratio = _as_float(notes.get("pred_exp_note_count_ratio"))
    if candidate_to_pred is not None and candidate_to_pred >= 2.0 and (pred_exp_ratio is None or pred_exp_ratio < 0.50):
        return "possible_note_segmentation_filtering"
    expected_short = _as_float(notes.get("expected_short_note_ratio"))
    predicted_short = _as_float(notes.get("predicted_short_note_ratio"))
    if expected_short is not None and predicted_short is not None and expected_short >= 0.30 and predicted_short <= expected_short * 0.50:
        return "possible_short_note_loss"
    pitch_overlap = _as_float(notes.get("pitch_range_overlap_ratio"))
    raw_match_expected = _as_float(match.get("raw_match_rate_vs_expected"))
    if (
        time_overlap is not None
        and time_overlap >= 0.35
        and ((pitch_overlap is not None and pitch_overlap < 0.35) or (raw_match_expected is not None and raw_match_expected < 0.05))
    ):
        return "possible_pitch_or_melody_selector"
    return "mixed_issue_needs_manual_review"


def _coverage_from_metrics(metrics_payload: dict[str, Any]) -> float | None:
    audibility = metrics_payload.get("audibility") if isinstance(metrics_payload.get("audibility"), dict) else {}
    diagnostics = metrics_payload.get("diagnostics") if isinstance(metrics_payload.get("diagnostics"), dict) else {}
    return _as_float(audibility.get("midi_coverage_ratio") if "midi_coverage_ratio" in audibility else diagnostics.get("midi_coverage_ratio"))


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "unavailable_reason": reason}


def _failed_check_names(quality_payload: dict[str, Any], summary_row: dict[str, Any]) -> list[str]:
    failed = quality_payload.get("failed_checks") if isinstance(quality_payload, dict) else None
    if not failed and isinstance(summary_row.get("quality_gate"), dict):
        failed = summary_row["quality_gate"].get("failed_checks")
    names: list[str] = []
    for item in failed or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _derived_diagnostics_markdown_lines(derived_diagnostics: dict[str, Any] | None) -> list[str]:
    if not isinstance(derived_diagnostics, dict):
        return ["", "## Derived Diagnostics", "- available: false"]
    notes = derived_diagnostics.get("notes") if isinstance(derived_diagnostics.get("notes"), dict) else {}
    f0 = derived_diagnostics.get("f0") if isinstance(derived_diagnostics.get("f0"), dict) else {}
    pitch_contours = derived_diagnostics.get("pitch_contours") if isinstance(derived_diagnostics.get("pitch_contours"), dict) else {}
    vocal_activity = derived_diagnostics.get("vocal_activity") if isinstance(derived_diagnostics.get("vocal_activity"), dict) else {}
    note_candidates = derived_diagnostics.get("note_candidates") if isinstance(derived_diagnostics.get("note_candidates"), dict) else {}
    selected_melody = derived_diagnostics.get("selected_melody") if isinstance(derived_diagnostics.get("selected_melody"), dict) else {}
    quantized_notes = derived_diagnostics.get("quantized_notes") if isinstance(derived_diagnostics.get("quantized_notes"), dict) else {}
    rhythm = derived_diagnostics.get("rhythm") if isinstance(derived_diagnostics.get("rhythm"), dict) else {}
    continuity = derived_diagnostics.get("continuity") if isinstance(derived_diagnostics.get("continuity"), dict) else {}
    short_note_diagnostics = derived_diagnostics.get("short_note_diagnostics") if isinstance(derived_diagnostics.get("short_note_diagnostics"), dict) else {}
    note_funnel = derived_diagnostics.get("note_funnel") if isinstance(derived_diagnostics.get("note_funnel"), dict) else {}
    note_funnel_layers = note_funnel.get("layers") if isinstance(note_funnel.get("layers"), dict) else {}
    note_funnel_retention = note_funnel.get("retention") if isinstance(note_funnel.get("retention"), dict) else {}
    note_funnel_loss = note_funnel.get("loss_attribution") if isinstance(note_funnel.get("loss_attribution"), dict) else {}
    note_funnel_flags = note_funnel_loss.get("triggered_flags") if isinstance(note_funnel_loss.get("triggered_flags"), list) else []
    quant_fragmentation = quantized_notes.get("fragmentation") if isinstance(quantized_notes.get("fragmentation"), dict) else {}
    quant_overmerge = quantized_notes.get("overmerge") if isinstance(quantized_notes.get("overmerge"), dict) else {}
    short_loss_attribution = short_note_diagnostics.get("loss_attribution") if isinstance(short_note_diagnostics.get("loss_attribution"), dict) else {}
    match = derived_diagnostics.get("match") if isinstance(derived_diagnostics.get("match"), dict) else {}
    pitch_distribution = derived_diagnostics.get("pitch_distribution") if isinstance(derived_diagnostics.get("pitch_distribution"), dict) else {}
    pairwise = pitch_distribution.get("pairwise") if isinstance(pitch_distribution.get("pairwise"), dict) else {}
    pitch_flags = pitch_distribution.get("triggered_pitch_flags") if isinstance(pitch_distribution.get("triggered_pitch_flags"), list) else []
    expected_vs_predicted = pairwise.get("expected_vs_predicted") if isinstance(pairwise.get("expected_vs_predicted"), dict) else {}
    expected_vs_f0 = pairwise.get("expected_vs_f0") if isinstance(pairwise.get("expected_vs_f0"), dict) else {}
    expected_vs_candidates = pairwise.get("expected_vs_note_candidates") if isinstance(pairwise.get("expected_vs_note_candidates"), dict) else {}
    return [
        "",
        "## Derived Diagnostics",
        "### Notes Density / Duration",
        f"- expected_note_count: {_fmt(notes.get('expected_note_count'))}",
        f"- predicted_note_count: {_fmt(notes.get('predicted_note_count'))}",
        f"- expected_notes_per_second: {_fmt(notes.get('expected_notes_per_second'))}",
        f"- predicted_notes_per_second: {_fmt(notes.get('predicted_notes_per_second'))}",
        f"- expected_median_duration_sec: {_fmt(notes.get('expected_median_duration_sec'))}",
        f"- predicted_median_duration_sec: {_fmt(notes.get('predicted_median_duration_sec'))}",
        f"- expected_short_note_ratio: {_fmt(notes.get('expected_short_note_ratio'))}",
        f"- predicted_short_note_ratio: {_fmt(notes.get('predicted_short_note_ratio'))}",
        f"- pred_exp_note_count_ratio: {_fmt(notes.get('pred_exp_note_count_ratio'))}",
        "### Continuity Diagnostics",
        f"- gap50_ratio: {_fmt(continuity.get('gap50_ratio'))}",
        f"- gap50_count: {_fmt(continuity.get('gap50_count'))}",
        f"- big_gap_count: {_fmt(continuity.get('big_gap_count'))}",
        f"- big_gap_ratio: {_fmt(continuity.get('big_gap_ratio'))}",
        f"- longest_inter_note_gap_sec: {_fmt(continuity.get('longest_inter_note_gap_sec'))}",
        f"- short_note_ratio: {_fmt(continuity.get('short_note_ratio'))}",
        f"- large_jump_count: {_fmt(continuity.get('large_jump_count'))}",
        f"- large_jump_ratio: {_fmt(continuity.get('large_jump_ratio'))}",
        f"- max_abs_pitch_jump_semitones: {_fmt(continuity.get('max_abs_pitch_jump_semitones'))}",
        "### Time Overlap",
        f"- expected_time_span_sec: {_fmt(notes.get('expected_time_span_sec'))}",
        f"- predicted_time_span_sec: {_fmt(notes.get('predicted_time_span_sec'))}",
        f"- expected_predicted_time_overlap_ratio: {_fmt(notes.get('expected_predicted_time_overlap_ratio'))}",
        "### Pitch Overlap",
        f"- expected_pitch_range: {_fmt(notes.get('expected_pitch_range'))}",
        f"- predicted_pitch_range: {_fmt(notes.get('predicted_pitch_range'))}",
        f"- pitch_range_overlap_ratio: {_fmt(notes.get('pitch_range_overlap_ratio'))}",
        f"- expected_median_pitch: {_fmt(notes.get('expected_median_pitch'))}",
        f"- predicted_median_pitch: {_fmt(notes.get('predicted_median_pitch'))}",
        f"- median_pitch_delta: {_fmt(notes.get('median_pitch_delta'))}",
        "### F0 Diagnostics",
        f"- available: {str(bool(f0.get('available'))).lower()}",
        f"- f0_frame_count: {_fmt(f0.get('f0_frame_count'))}",
        f"- f0_voiced_frame_count: {_fmt(f0.get('f0_voiced_frame_count'))}",
        f"- f0_voiced_ratio: {_fmt(f0.get('f0_voiced_ratio'))}",
        f"- f0_median_confidence: {_fmt(f0.get('f0_median_confidence'))}",
        f"- f0_pitch_range: {_fmt(f0.get('f0_pitch_range'))}",
        f"- f0_time_span_sec: {_fmt(f0.get('f0_time_span_sec'))}",
        f"- unavailable_reason: {_fmt(f0.get('unavailable_reason')) if not f0.get('available') else 'none'}",
        "### Pitch Contour Diagnostics",
        f"- available: {str(bool(pitch_contours.get('available'))).lower()}",
        f"- contour_count: {_fmt(pitch_contours.get('contour_count'))}",
        f"- low_confidence_contour_count: {_fmt(pitch_contours.get('low_confidence_contour_count'))}",
        f"- median_contour_duration_sec: {_fmt(pitch_contours.get('median_contour_duration_sec'))}",
        f"- suspected_vibrato_contour_count: {_fmt(pitch_contours.get('suspected_vibrato_contour_count'))}",
        f"- suspected_glide_contour_count: {_fmt(pitch_contours.get('suspected_glide_contour_count'))}",
        f"- unavailable_reason: {_fmt(pitch_contours.get('unavailable_reason')) if not pitch_contours.get('available') else 'none'}",
        "### Vocal Activity Diagnostics",
        f"- available: {str(bool(vocal_activity.get('available'))).lower()}",
        f"- vocal_activity_active_ratio: {_fmt(vocal_activity.get('vocal_activity_active_ratio'))}",
        f"- vocal_activity_segment_count: {_fmt(vocal_activity.get('vocal_activity_segment_count'))}",
        f"- vocal_activity_time_span_sec: {_fmt(vocal_activity.get('vocal_activity_time_span_sec'))}",
        f"- active_duration_sec: {_fmt(vocal_activity.get('active_duration_sec'))}",
        f"- unavailable_reason: {_fmt(vocal_activity.get('unavailable_reason')) if not vocal_activity.get('available') else 'none'}",
        "### Note Candidate Diagnostics",
        f"- available: {str(bool(note_candidates.get('available'))).lower()}",
        f"- note_candidate_count: {_fmt(note_candidates.get('note_candidate_count'))}",
        f"- candidate_to_predicted_ratio: {_fmt(note_candidates.get('candidate_to_predicted_ratio'))}",
        f"- candidate_median_duration_sec: {_fmt(note_candidates.get('candidate_median_duration_sec'))}",
        f"- candidate_short_note_ratio: {_fmt(note_candidates.get('candidate_short_note_ratio'))}",
        f"- candidate_pitch_range: {_fmt(note_candidates.get('candidate_pitch_range'))}",
        f"- unavailable_reason: {_fmt(note_candidates.get('unavailable_reason')) if not note_candidates.get('available') else 'none'}",
        "### Selected Melody Diagnostics",
        f"- available: {str(bool(selected_melody.get('available'))).lower()}",
        f"- input_candidate_count: {_fmt(selected_melody.get('input_candidate_count'))}",
        f"- selected_count: {_fmt(selected_melody.get('selected_count'))}",
        f"- rejected_count: {_fmt(selected_melody.get('rejected_count'))}",
        f"- rejection_reason_counts: {_fmt(selected_melody.get('rejection_reason_counts'))}",
        f"- mean_selected_confidence: {_fmt(selected_melody.get('mean_selected_confidence'))}",
        f"- mean_rejected_confidence: {_fmt(selected_melody.get('mean_rejected_confidence'))}",
        f"- unavailable_reason: {_fmt(selected_melody.get('unavailable_reason')) if not selected_melody.get('available') else 'none'}",
        "### Quantization Diagnostics",
        f"- available: {str(bool(quantized_notes.get('available'))).lower()}",
        f"- quantizer_backend: {_fmt(quantized_notes.get('quantizer_backend'))}",
        f"- requested_quantizer_backend: {_fmt(quantized_notes.get('requested_quantizer_backend'))}",
        f"- fallback_used: {str(bool(quantized_notes.get('fallback_used'))).lower()}",
        f"- fallback_reason: {_fmt(quantized_notes.get('fallback_reason'))}",
        f"- note_count: {_fmt(quantized_notes.get('note_count'))}",
        f"- mean_quantize_error_sec: {_fmt(quantized_notes.get('mean_quantize_error_sec'))}",
        f"- p95_quantize_error_sec: {_fmt(quantized_notes.get('p95_quantize_error_sec'))}",
        f"- max_quantize_error_sec: {_fmt(quantized_notes.get('max_quantize_error_sec'))}",
        f"- uncertain_count: {_fmt(quantized_notes.get('uncertain_count'))}",
        f"- possible_fragment_pair_count: {_fmt(quant_fragmentation.get('possible_fragment_pair_count'))}",
        f"- fragmentation_risk_score: {_fmt(quant_fragmentation.get('risk_score'))}",
        f"- possible_overmerge_note_count: {_fmt(quant_overmerge.get('possible_overmerge_note_count'))}",
        f"- overmerge_overlap_pair_count: {_fmt(quant_overmerge.get('overlap_pair_count'))}",
        f"- overmerge_risk_score: {_fmt(quant_overmerge.get('risk_score'))}",
        f"- unavailable_reason: {_fmt(quantized_notes.get('unavailable_reason')) if not quantized_notes.get('available') else 'none'}",
        "### Rhythm Diagnostics",
        f"- available: {str(bool(rhythm.get('available'))).lower()}",
        f"- tempo_bpm: {_fmt(rhythm.get('tempo_bpm'))}",
        f"- tempo_stability: {_fmt(rhythm.get('tempo_stability'))}",
        f"- beat_count: {_fmt(rhythm.get('beat_count'))}",
        f"- beat_gap_mean_sec: {_fmt(rhythm.get('beat_gap_mean_sec'))}",
        f"- beat_gap_p95_sec: {_fmt(rhythm.get('beat_gap_p95_sec'))}",
        f"- beat_gap_max_sec: {_fmt(rhythm.get('beat_gap_max_sec'))}",
        f"- downbeat_count: {_fmt(rhythm.get('downbeat_count'))}",
        f"- downbeat_confidence: {_fmt(rhythm.get('downbeat_confidence'))}",
        f"- bar_phase_confidence: {_fmt(rhythm.get('bar_phase_confidence'))}",
        f"- off_grid_onset_ratio: {_fmt(rhythm.get('off_grid_onset_ratio'))}",
        f"- pickup_likelihood: {_fmt(rhythm.get('pickup_likelihood'))}",
        f"- rubato_likelihood: {_fmt(rhythm.get('rubato_likelihood'))}",
        f"- grid_uncertain_region_count: {_fmt(rhythm.get('grid_uncertain_region_count'))}",
        f"- preliminary_rhythm_diagnosis: {_fmt(rhythm.get('preliminary_rhythm_diagnosis'))}",
        f"- rhythm_flags: {', '.join(str(flag) for flag in rhythm.get('rhythm_flags') or []) if isinstance(rhythm.get('rhythm_flags'), list) else 'none'}",
        f"- rhythm_candidate_count: {_fmt(len(rhythm.get('candidates') or [])) if isinstance(rhythm.get('candidates'), list) else 'missing'}",
        f"- best_diagnostic_candidate_id: {_fmt(rhythm.get('best_diagnostic_candidate_id'))}",
        f"- current_candidate_rank: {_fmt(rhythm.get('current_candidate_rank'))}",
        f"- current_vs_best_score_delta: {_fmt(rhythm.get('current_vs_best_score_delta'))}",
        f"- rhythm_candidate_warning: {_fmt(rhythm.get('rhythm_candidate_warning')) if rhythm.get('rhythm_candidate_warning') else 'none'}",
        f"- unavailable_reason: {_fmt(rhythm.get('unavailable_reason')) if not rhythm.get('available') else 'none'}",
        "### Note Funnel",
        f"- f0_voiced_frame_count: {_fmt(note_funnel.get('f0_voiced_frame_count'))}",
        f"- f0_voiced_duration_sec: {_fmt(note_funnel.get('f0_voiced_duration_sec'))}",
        f"- note_candidate_count: {_fmt(note_funnel.get('note_candidate_count'))}",
        f"- selected_note_count: {_fmt(note_funnel.get('selected_note_count'))}",
        f"- quantized_note_count: {_fmt(note_funnel.get('quantized_note_count'))}",
        f"- score_ir_note_count: {_fmt(note_funnel.get('score_ir_note_count'))}",
        f"- predicted_midi_note_count: {_fmt(note_funnel.get('predicted_midi_note_count'))}",
        f"- expected_note_count: {_fmt(note_funnel.get('expected_note_count'))}",
        f"- candidate_to_selected_count_ratio: {_fmt(note_funnel_retention.get('candidate_to_selected_count_ratio'))}",
        f"- selected_to_quantized_count_ratio: {_fmt(note_funnel_retention.get('selected_to_quantized_count_ratio'))}",
        f"- quantized_to_score_ir_count_ratio: {_fmt(note_funnel_retention.get('quantized_to_score_ir_count_ratio'))}",
        f"- score_ir_to_predicted_count_ratio: {_fmt(note_funnel_retention.get('score_ir_to_predicted_count_ratio'))}",
        f"- candidate_to_predicted_count_ratio: {_fmt(note_funnel_retention.get('candidate_to_predicted_count_ratio'))}",
        f"- triggered_funnel_flags: {', '.join(str(flag) for flag in note_funnel_flags) if note_funnel_flags else 'none'}",
        f"- primary_attribution: {_fmt(note_funnel_loss.get('primary_attribution'))}",
        f"- missing_layers: {', '.join(str(layer) for layer in note_funnel.get('missing_layers') or []) if isinstance(note_funnel.get('missing_layers'), list) and note_funnel.get('missing_layers') else 'none'}",
        "### Short Note Diagnostics",
        f"- available: {str(bool(short_note_diagnostics.get('available'))).lower()}",
        f"- expected_short_note_count: {_fmt(short_note_diagnostics.get('expected_short_note_count'))}",
        f"- predicted_short_note_count: {_fmt(short_note_diagnostics.get('predicted_short_note_count'))}",
        f"- matched_short_note_count: {_fmt(short_note_diagnostics.get('matched_short_note_count'))}",
        f"- missed_short_note_count: {_fmt(short_note_diagnostics.get('missed_short_note_count'))}",
        f"- false_positive_short_note_count: {_fmt(short_note_diagnostics.get('false_positive_short_note_count'))}",
        f"- short_note_recall: {_fmt(short_note_diagnostics.get('short_note_recall'))}",
        f"- short_note_precision: {_fmt(short_note_diagnostics.get('short_note_precision'))}",
        f"- likely_loss_stage: {_fmt(short_loss_attribution.get('likely_loss_stage'))}",
        f"- loss_stage_counts: {_fmt(short_loss_attribution.get('stage_counts'))}",
        f"- unavailable_reason: {_fmt(short_note_diagnostics.get('unavailable_reason')) if not short_note_diagnostics.get('available') else 'none'}",
        "### Match Diagnostics",
        f"- raw_matched_count: {_fmt(match.get('raw_matched_count'))}",
        f"- shift_matched_count: {_fmt(match.get('shift_matched_count'))}",
        f"- unmatched_expected_count: {_fmt(match.get('unmatched_expected_count'))}",
        f"- unmatched_predicted_count: {_fmt(match.get('unmatched_predicted_count'))}",
        f"- raw_match_rate_vs_expected: {_fmt(match.get('raw_match_rate_vs_expected'))}",
        f"- raw_match_rate_vs_predicted: {_fmt(match.get('raw_match_rate_vs_predicted'))}",
        f"- shift_match_rate_vs_expected: {_fmt(match.get('shift_match_rate_vs_expected'))}",
        f"- shift_match_rate_vs_predicted: {_fmt(match.get('shift_match_rate_vs_predicted'))}",
        "### Pitch Distribution Summary",
        f"- preliminary_pitch_diagnosis: {_fmt(pitch_distribution.get('preliminary_pitch_diagnosis'))}",
        f"- triggered_pitch_flags: {', '.join(str(flag) for flag in pitch_flags) if pitch_flags else 'none'}",
        f"- expected_vs_predicted_pitch_overlap: {_fmt(expected_vs_predicted.get('raw_histogram_overlap'))}",
        f"- expected_vs_f0_pitch_overlap: {_fmt(expected_vs_f0.get('raw_histogram_overlap'))}",
        f"- expected_vs_candidates_pitch_overlap: {_fmt(expected_vs_candidates.get('raw_histogram_overlap'))}",
        f"- best_octave_shift evidence: expected_vs_f0 shift={_fmt(expected_vs_f0.get('best_octave_shift'))} overlap={_fmt(expected_vs_f0.get('best_octave_shifted_overlap'))} gain={_fmt(expected_vs_f0.get('octave_shift_overlap_gain'))}",
        "### Rule-Based Stage",
        f"- preliminary_failure_stage_v2: {_fmt(derived_diagnostics.get('preliminary_failure_stage_v2'))}",
    ]


def _metric_value(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> Any:
    if key in primary:
        return primary.get(key)
    return fallback.get(key)


def _duration_basis_from_notes_or_metrics(metrics_payload: dict[str, Any], expected_count: int, predicted_count: int) -> float:
    audibility = metrics_payload.get("audibility") if isinstance(metrics_payload.get("audibility"), dict) else {}
    expected_duration = _as_float(audibility.get("expected_duration_sec")) or 0.0
    predicted_duration = _as_float(audibility.get("predicted_duration_sec")) or 0.0
    duration = max(expected_duration, predicted_duration)
    if duration > 0:
        return duration
    return float(max(expected_count, predicted_count, 1))


def _safe_density(count: int, duration_sec: float) -> float | None:
    if duration_sec <= 0:
        return None
    return float(count) / duration_sec


def _safe_divide(numerator: Any, denominator: Any) -> float | None:
    numerator_float = _as_float(numerator)
    denominator_float = _as_float(denominator)
    if numerator_float is None or denominator_float is None or denominator_float == 0:
        return None
    return numerator_float / denominator_float


def _median(values: list[float | int]) -> float | None:
    cleaned = sorted(float(value) for value in values if value is not None)
    if not cleaned:
        return None
    midpoint = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[midpoint]
    return (cleaned[midpoint - 1] + cleaned[midpoint]) / 2.0


def _time_overlap_ratio(
    first_start: float | None,
    first_end: float | None,
    second_start: float | None,
    second_end: float | None,
) -> float | None:
    if first_start is None or first_end is None or second_start is None or second_end is None:
        return None
    intersection = max(0.0, min(first_end, second_end) - max(first_start, second_start))
    union = max(first_end, second_end) - min(first_start, second_start)
    return _safe_divide(intersection, union)


def _pitch_range_overlap_ratio(first_range: list[Any] | None, second_range: list[Any] | None) -> float | None:
    if not first_range or not second_range or len(first_range) < 2 or len(second_range) < 2:
        return None
    first_min = _as_float(first_range[0])
    first_max = _as_float(first_range[1])
    second_min = _as_float(second_range[0])
    second_max = _as_float(second_range[1])
    if first_min is None or first_max is None or second_min is None or second_max is None:
        return None
    intersection = max(0.0, min(first_max, second_max) - max(first_min, second_min))
    union = max(first_max, second_max) - min(first_min, second_min)
    return _safe_divide(intersection, union)


def _possible_failure_stage(
    *,
    f0_available: bool,
    predicted_note_count: int,
    expected_note_count: int,
    coverage: float | None,
    raw_recall: float | None,
    shift_recall: float | None,
    dtw_recall: float | None,
) -> str:
    if not f0_available:
        return "unknown_missing_f0"
    if expected_note_count > 0 and predicted_note_count < max(10, int(expected_note_count * 0.10)):
        return "possible_segmentation_or_filtering"
    if coverage is not None and coverage < 0.20:
        return "possible_vocal_activity_or_separation"
    if (
        raw_recall is not None
        and shift_recall is not None
        and dtw_recall is not None
        and raw_recall < 0.05
        and shift_recall < 0.05
        and dtw_recall < 0.15
    ):
        return "possible_pitch_or_segmentation_or_selector"
    return "mixed_issue_needs_manual_review"


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _round_float(value: float) -> float:
    return round(float(value), 6)


def _round_optional(value: Any) -> float | None:
    value_float = _as_float(value)
    return None if value_float is None else _round_float(value_float)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        number = _as_float(item)
        if number is not None:
            result.append(float(number))
    return sorted(result)


def _positive_diffs(values: list[float]) -> list[float]:
    return [values[index] - values[index - 1] for index in range(1, len(values)) if values[index] > values[index - 1]]


def _rhythm_tempo_bpm(payload: dict[str, Any], beat_gaps: list[float]) -> float | None:
    for key in ("tempo_bpm", "bpm"):
        value = _as_float(payload.get(key))
        if value is not None and value > 0:
            return value
    gap = _median(beat_gaps)
    if gap is None or gap <= 0:
        return None
    return 60.0 / gap


def _tempo_stability(payload: dict[str, Any], beat_gaps: list[float]) -> float | None:
    for key in ("tempo_stability", "stability_score", "bpm_confidence"):
        value = _as_float(payload.get(key))
        if value is not None:
            return max(0.0, min(1.0, value))
    if len(beat_gaps) < 2:
        return None
    mean_gap = _mean(beat_gaps)
    if mean_gap is None or mean_gap <= 0:
        return None
    deviations = [abs(gap - mean_gap) for gap in beat_gaps]
    mean_abs_deviation = _mean(deviations) or 0.0
    return max(0.0, min(1.0, 1.0 - mean_abs_deviation / max(mean_gap, 1e-6)))


def _bar_phase_confidence(
    *,
    beat_times: list[float],
    downbeat_times: list[float],
    beats_per_bar: int,
    downbeat_confidence: float | None,
) -> float | None:
    if not beat_times or not downbeat_times:
        return 0.0
    beat_index_by_time = [_nearest_index(beat_times, downbeat) for downbeat in downbeat_times]
    valid_indices = [index for index in beat_index_by_time if index is not None]
    if not valid_indices:
        return 0.0
    phase_matches = sum(1 for index in valid_indices if index % beats_per_bar == valid_indices[0] % beats_per_bar)
    phase_consistency = phase_matches / max(1, len(valid_indices))
    if downbeat_confidence is None:
        return phase_consistency
    return max(0.0, min(1.0, 0.55 * phase_consistency + 0.45 * downbeat_confidence))


def _off_grid_onsets(predicted_notes: list[NoteEvent], beat_times: list[float], beat_gap_mean: float | None) -> dict[str, Any]:
    if not predicted_notes or len(beat_times) < 2 or beat_gap_mean is None or beat_gap_mean <= 0:
        return {"ratio": None, "onsets": []}
    tolerance = max(0.06, min(0.18, beat_gap_mean * 0.18))
    off_grid: list[dict[str, Any]] = []
    for note in predicted_notes:
        distance = _distance_to_nearest(beat_times, float(note.start))
        if distance is not None and distance > tolerance:
            off_grid.append(
                {
                    "start_sec": _round_float(float(note.start)),
                    "pitch": int(note.pitch),
                    "nearest_grid_distance_sec": _round_float(distance),
                }
            )
    return {"ratio": len(off_grid) / max(1, len(predicted_notes)), "onsets": off_grid}


def _pickup_likelihood(predicted_notes: list[NoteEvent], beat_times: list[float], downbeat_times: list[float], beat_gap_mean: float | None) -> float | None:
    if not predicted_notes:
        return None
    first_note = min(float(note.start) for note in predicted_notes)
    anchors = downbeat_times or beat_times
    if not anchors:
        return None
    first_anchor = min(anchors)
    beat_gap = beat_gap_mean or 0.5
    leading_gap = first_note - first_anchor
    if leading_gap < -0.05:
        return 0.85
    if 0.05 <= leading_gap <= max(beat_gap * 1.5, 0.75):
        return 0.45
    if leading_gap > max(beat_gap * 4.0, 2.0):
        return 0.75
    return 0.0


def _rubato_likelihood(beat_gaps: list[float]) -> float | None:
    if len(beat_gaps) < 3:
        return None
    mean_gap = _mean(beat_gaps)
    if mean_gap is None or mean_gap <= 0:
        return None
    p95 = _percentile(beat_gaps, 95.0)
    p05 = _percentile(beat_gaps, 5.0)
    if p95 is None or p05 is None:
        return None
    spread_ratio = max(0.0, (p95 - p05) / max(mean_gap, 1e-6))
    return max(0.0, min(1.0, spread_ratio / 0.5))


def _grid_uncertain_regions(
    *,
    beat_times: list[float],
    beat_gap_mean: float | None,
    beat_gap_p95: float | None,
    downbeat_confidence: float | None,
    bar_phase_confidence: float | None,
    off_grid_onsets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    if beat_times and beat_gap_mean and beat_gap_p95 and beat_gap_p95 > beat_gap_mean * 1.35:
        threshold = beat_gap_mean * 1.35
        for index in range(1, len(beat_times)):
            gap = beat_times[index] - beat_times[index - 1]
            if gap > threshold:
                regions.append(
                    {
                        "start_sec": _round_float(beat_times[index - 1]),
                        "end_sec": _round_float(beat_times[index]),
                        "reason": "irregular_beat_gap",
                        "confidence": _round_float(min(1.0, (gap - threshold) / max(beat_gap_mean, 1e-6))),
                    }
                )
    if downbeat_confidence is not None and downbeat_confidence < 0.35 and beat_times:
        regions.append(
            {
                "start_sec": _round_float(beat_times[0]),
                "end_sec": _round_float(beat_times[-1]),
                "reason": "low_downbeat_confidence",
                "confidence": _round_float(1.0 - downbeat_confidence),
            }
        )
    if bar_phase_confidence is not None and bar_phase_confidence < 0.45 and beat_times:
        regions.append(
            {
                "start_sec": _round_float(beat_times[0]),
                "end_sec": _round_float(beat_times[-1]),
                "reason": "low_bar_phase_confidence",
                "confidence": _round_float(1.0 - bar_phase_confidence),
            }
        )
    for onset in off_grid_onsets[:20]:
        start = _as_float(onset.get("start_sec")) if isinstance(onset, dict) else None
        if start is None:
            continue
        regions.append(
            {
                "start_sec": _round_float(max(0.0, start - 0.1)),
                "end_sec": _round_float(start + 0.1),
                "reason": "off_grid_predicted_note_onset",
                "confidence": _round_float(min(1.0, (_as_float(onset.get("nearest_grid_distance_sec")) or 0.0) / max(beat_gap_mean or 0.5, 1e-6))),
            }
        )
    return regions[:50]


def _rhythm_preliminary_diagnosis(
    *,
    tempo_stability: float | None,
    downbeat_confidence: float | None,
    bar_phase_confidence: float | None,
    off_grid_onset_ratio: float | None,
    pickup_likelihood: float | None,
    rubato_likelihood: float | None,
) -> str:
    issues = []
    if tempo_stability is not None and tempo_stability < 0.65:
        issues.append("possible_tempo_instability")
    if downbeat_confidence is not None and downbeat_confidence < 0.35:
        issues.append("possible_downbeat_uncertainty")
    if bar_phase_confidence is not None and bar_phase_confidence < 0.45:
        issues.append("possible_bar_phase_error")
    if off_grid_onset_ratio is not None and off_grid_onset_ratio > 0.35:
        issues.append("possible_off_grid_quantization")
    if pickup_likelihood is not None and pickup_likelihood >= 0.7:
        issues.append("possible_pickup_or_leading_silence")
    if rubato_likelihood is not None and rubato_likelihood >= 0.7 and "possible_tempo_instability" not in issues:
        issues.append("possible_tempo_instability")
    if len(issues) > 1:
        return "mixed_rhythm_issue"
    if issues:
        return issues[0]
    return "stable_grid"


def _rhythm_flags(
    *,
    diagnosis: str,
    tempo_stability: float | None,
    downbeat_confidence: float | None,
    bar_phase_confidence: float | None,
    off_grid_onset_ratio: float | None,
    pickup_likelihood: float | None,
    rubato_likelihood: float | None,
) -> list[str]:
    flags: list[str] = []
    if diagnosis != "stable_grid":
        flags.append(diagnosis)
    if tempo_stability is not None and tempo_stability < 0.65:
        flags.append("possible_tempo_instability")
    if downbeat_confidence is not None and downbeat_confidence < 0.35:
        flags.append("possible_downbeat_uncertainty")
    if bar_phase_confidence is not None and bar_phase_confidence < 0.45:
        flags.append("possible_bar_phase_error")
    if off_grid_onset_ratio is not None and off_grid_onset_ratio > 0.35:
        flags.append("possible_off_grid_quantization")
    if pickup_likelihood is not None and pickup_likelihood >= 0.7:
        flags.append("possible_pickup_or_leading_silence")
    if rubato_likelihood is not None and rubato_likelihood >= 0.7:
        flags.append("possible_tempo_instability")
    return sorted(set(flags))


def _nearest_index(values: list[float], target: float) -> int | None:
    if not values:
        return None
    return min(range(len(values)), key=lambda index: abs(values[index] - target))


def _distance_to_nearest(values: list[float], target: float) -> float | None:
    index = _nearest_index(values, target)
    if index is None:
        return None
    return abs(values[index] - target)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * max(0.0, min(100.0, percentile)) / 100.0
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = _as_float(value)
        if number is not None:
            return number
    return None

