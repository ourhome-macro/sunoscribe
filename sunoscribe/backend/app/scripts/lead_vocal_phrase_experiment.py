from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.melody_selection_artifact import MelodySelectionConfig, RuleBasedMelodySelector
from app.modules.pitch.midi_exporter import MidiExporter
from app.modules.pitch.note_utils import midi_to_note
from app.modules.pitch.quantizer import NoteQuantizer
from app.modules.pitch.types import Note


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    pitch_dir = Path(args.pitch_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    note_candidates_payload = _read_json(pitch_dir / "note_candidates.json")
    selected_payload = _read_json(pitch_dir / "selected_melody.json")
    rhythm_grid = _read_json(pitch_dir / "rhythm_grid.json")
    selected_notes = selected_payload.get("selected_notes") or []
    raw_candidates = ((note_candidates_payload.get("melody_candidates") or {}).get("notes") or [])
    bpm = float(rhythm_grid.get("bpm") or 0.0)
    beat_times = [float(item) for item in rhythm_grid.get("beat_times") or []]

    variants = {
        "baseline_selected": {
            "notes": [_dict_to_note(note) for note in selected_notes],
            "description": "selected_melody baseline, no extra phrase experiment",
        },
        "phrase_no_postprocess": {
            "notes": _selector_variant(
                note_candidates_payload,
                MelodySelectionConfig(phrase_postprocess_enabled=False, prefer_preselected_notes=False),
            ),
            "description": "reselect raw candidates without phrase postprocess",
        },
        "phrase_sustain_heavy": {
            "notes": _selector_variant(
                note_candidates_payload,
                MelodySelectionConfig(
                    phrase_postprocess_enabled=True,
                    prefer_preselected_notes=False,
                    phrase_sustain_gap_sec=0.22,
                    phrase_sustain_max_pitch_delta_semitones=2,
                ),
            ),
            "description": "reselect raw candidates with stronger phrase sustain",
        },
        "phrase_cleanup_aggressive": {
            "notes": _selector_variant(
                note_candidates_payload,
                MelodySelectionConfig(
                    phrase_postprocess_enabled=True,
                    prefer_preselected_notes=False,
                    postprocess_profile="cleanup_aggressive",
                    phrase_remove_isolated_fragments_enabled=True,
                ),
            ),
            "description": "reselect raw candidates with cleanup_aggressive phrase pass",
        },
        "listen_same_contour_merge_strict": {
            "notes": _same_contour_listen_merge(selected_notes),
            "description": "offline listening-only strict same-contour merge on selected melody",
        },
    }

    summary: dict[str, Any] = {"pitch_dir": str(pitch_dir), "variants": {}}
    quantizer = NoteQuantizer(PitchDetectionConfig())
    exporter = MidiExporter()

    for variant_name, variant in variants.items():
        notes = list(variant["notes"])
        quantized = quantizer.quantize(notes, bpm=bpm, beat_times=beat_times)
        midi_path = out_dir / f"{variant_name}.mid"
        exporter.export_quantized_notes(quantized, bpm=bpm, output_path=midi_path)
        summary["variants"][variant_name] = {
            "description": variant["description"],
            "note_count": len(notes),
            "quantized_note_count": len(quantized),
            "midi_path": str(midi_path),
            "total_duration_sec": round(sum(max(0.0, note.end_time - note.start_time) for note in notes), 6),
        }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote phrase experiment package to {out_dir}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate lead-vocal phrase comparison MIDIs from existing artifacts.")
    parser.add_argument("--pitch-dir", required=True, help="Path to pitch artifact directory containing selected_melody.json and rhythm_grid.json")
    parser.add_argument("--output-dir", required=True, help="Directory to write comparison MIDIs and summary")
    return parser.parse_args(argv)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _selector_variant(note_candidates_payload: dict[str, Any], config: MelodySelectionConfig) -> list[Note]:
    selector = RuleBasedMelodySelector(config)
    result = selector.select(note_candidates=note_candidates_payload)
    processed = result.get("selected_notes") if isinstance(result, dict) else None
    return [_dict_to_note(note) for note in processed or []]


def _same_contour_listen_merge(selected_notes: list[dict[str, Any]]) -> list[Note]:
    merged: list[dict[str, Any]] = []
    idx = 0
    while idx < len(selected_notes):
        current = dict(selected_notes[idx])
        if idx < len(selected_notes) - 1:
            nxt = dict(selected_notes[idx + 1])
            current_contours = list(current.get("source_contour_ids") or [])
            next_contours = list(nxt.get("source_contour_ids") or [])
            if len(current_contours) == 1 and current_contours == next_contours:
                current_pitch = float(current.get("pitch_center_midi") or 0.0)
                next_pitch = float(nxt.get("pitch_center_midi") or 0.0)
                gap = float(nxt.get("start_time_sec", nxt.get("start_time", 0.0))) - float(
                    current.get("end_time_sec", current.get("end_time", 0.0))
                )
                total_duration = float(nxt.get("end_time_sec", nxt.get("end_time", 0.0))) - float(
                    current.get("start_time_sec", current.get("start_time", 0.0))
                )
                if 0.0 <= gap <= 0.08 and abs(next_pitch - current_pitch) <= 1.0 and total_duration <= 1.05:
                    merged_pitch = round((current_pitch + next_pitch) / 2.0, 6)
                    current["candidate_id"] = f"{current.get('candidate_id')}+{nxt.get('candidate_id')}"
                    current["source_candidate_ids"] = list(dict.fromkeys(list(current.get("source_candidate_ids") or []) + list(nxt.get("source_candidate_ids") or [])))
                    current["end_time_sec"] = round(float(nxt.get("end_time_sec", nxt.get("end_time", 0.0))), 6)
                    current["end_time"] = current["end_time_sec"]
                    current["duration_sec"] = round(total_duration, 6)
                    current["pitch_center_midi"] = merged_pitch
                    current["pitch"] = midi_to_note(merged_pitch)
                    current["confidence"] = round(max(float(current.get("confidence") or 0.0), float(nxt.get("confidence") or 0.0)), 6)
                    current["reason_codes"] = list(dict.fromkeys(list(current.get("reason_codes") or []) + list(nxt.get("reason_codes") or []) + ["offline_same_contour_merge"]))
                    merged.append(current)
                    idx += 2
                    continue
        merged.append(current)
        idx += 1
    return [_dict_to_note(note) for note in merged]


def _dict_to_note(note: dict[str, Any]) -> Note:
    return Note(
        pitch=str(note.get("pitch") or "C4"),
        start_time=float(note.get("start_time_sec", note.get("start_time", 0.0)) or 0.0),
        end_time=float(note.get("end_time_sec", note.get("end_time", 0.0)) or 0.0),
        confidence=float(note.get("confidence") or 0.0),
        reason_codes=list(note.get("reason_codes") or []),
        candidate_id=note.get("candidate_id"),
        source_candidate_id=note.get("source_candidate_id"),
        source_candidate_ids=list(note.get("source_candidate_ids") or []),
        source_contour_ids=list(note.get("source_contour_ids") or []),
        source_f0_frame_range=dict(note.get("source_f0_frame_range") or {}),
        candidate_origin=note.get("candidate_origin"),
        contour_bridge_evidence=dict(note.get("contour_bridge_evidence") or {}),
        contour_bridge_guard_reason_codes=list(note.get("contour_bridge_guard_reason_codes") or []),
        segmentation_evidence=dict(note.get("segmentation_evidence") or {}),
    )


if __name__ == "__main__":
    raise SystemExit(main())
