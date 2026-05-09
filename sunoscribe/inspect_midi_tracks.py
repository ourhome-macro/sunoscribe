#!/usr/bin/env python3
"""Inspect MIDI tracks/instruments in a directory.

Usage:
    python inspect_midi_tracks.py /path/to/midi_folder [/path/to/another_folder_or_file ...]

Dependency:
    pip install pretty_midi numpy
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import numpy as np
import pretty_midi


MIDI_EXTENSIONS = {".mid", ".midi"}


def format_float(value: float | None, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "-"
    return f"{value:.{digits}f}"


def estimate_track_beats(
    midi: pretty_midi.PrettyMIDI,
    start_time: float,
    end_time: float,
) -> float:
    duration = max(0.0, end_time - start_time)
    if duration <= 0:
        return 0.0

    beats = midi.get_beats()
    if len(beats) >= 2:
        beat_count = int(np.sum((beats >= start_time) & (beats <= end_time)))
        if beat_count > 0:
            return float(beat_count)

    tempo = midi.estimate_tempo()
    if tempo and np.isfinite(tempo) and tempo > 0:
        return duration * tempo / 60.0

    return 0.0


def inspect_instrument(
    midi: pretty_midi.PrettyMIDI,
    instrument: pretty_midi.Instrument,
) -> dict[str, str]:
    notes = instrument.notes
    note_count = len(notes)

    if note_count == 0:
        return {
            "name": instrument.name or "-",
            "program": str(instrument.program),
            "is_drum": "yes" if instrument.is_drum else "no",
            "notes": "0",
            "pitch_range": "-",
            "mean_pitch": "-",
            "median_pitch": "-",
            "duration_sec": "0.00",
            "density_notes_per_beat": "-",
        }

    pitches = [note.pitch for note in notes]
    start_time = min(note.start for note in notes)
    end_time = max(note.end for note in notes)
    duration = max(0.0, end_time - start_time)
    beat_count = estimate_track_beats(midi, start_time, end_time)
    density = note_count / beat_count if beat_count > 0 else None

    return {
        "name": instrument.name or "-",
        "program": str(instrument.program),
        "is_drum": "yes" if instrument.is_drum else "no",
        "notes": str(note_count),
        "pitch_range": f"{min(pitches)}-{max(pitches)} ({max(pitches) - min(pitches)})",
        "mean_pitch": format_float(float(statistics.mean(pitches))),
        "median_pitch": format_float(float(statistics.median(pitches))),
        "duration_sec": format_float(duration),
        "density_notes_per_beat": format_float(density),
    }


def print_table(rows: list[dict[str, str]]) -> None:
    headers = [
        "track",
        "name",
        "program",
        "drum",
        "notes",
        "pitch_range",
        "mean",
        "median",
        "duration_s",
        "density/beat",
    ]
    keys = [
        "track",
        "name",
        "program",
        "is_drum",
        "notes",
        "pitch_range",
        "mean_pitch",
        "median_pitch",
        "duration_sec",
        "density_notes_per_beat",
    ]

    widths = [len(header) for header in headers]
    for row in rows:
        for index, key in enumerate(keys):
            widths[index] = max(widths[index], len(row[key]))

    header_line = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    separator = "  ".join("-" * width for width in widths)
    print(header_line)
    print(separator)
    for row in rows:
        print(
            "  ".join(
                row[key].ljust(widths[index]) for index, key in enumerate(keys)
            )
        )


def inspect_midi_file(path: Path) -> None:
    print(f"\n=== {path} ===")
    try:
        midi = pretty_midi.PrettyMIDI(str(path))
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"ERROR: failed to read MIDI: {exc}")
        return

    rows = []
    for index, instrument in enumerate(midi.instruments):
        row = inspect_instrument(midi, instrument)
        row["track"] = str(index)
        rows.append(row)

    if not rows:
        print("No instruments/tracks found.")
        return

    print_table(rows)


def find_midi_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() in MIDI_EXTENSIONS:
        return [path]
    if not path.is_dir():
        return []
    return sorted(
        child
        for child in path.rglob("*")
        if child.is_file() and child.suffix.lower() in MIDI_EXTENSIONS
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect note statistics for every MIDI track in a folder."
    )
    parser.add_argument("midi_paths", nargs="+", type=Path, help="MIDI file(s) or folder(s) containing .mid/.midi files")
    args = parser.parse_args()

    input_paths = [path.expanduser().resolve() for path in args.midi_paths]
    missing_paths = [path for path in input_paths if not path.exists()]
    if missing_paths:
        parser.error("missing path(s): " + ", ".join(str(path) for path in missing_paths))

    midi_files: list[Path] = []
    for path in input_paths:
        midi_files.extend(find_midi_files(path))
    midi_files = sorted(set(midi_files))
    if not midi_files:
        print("No MIDI files found under input path(s).")
        return 1

    print(f"Found {len(midi_files)} MIDI file(s).")
    for midi_file in midi_files:
        inspect_midi_file(midi_file)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
