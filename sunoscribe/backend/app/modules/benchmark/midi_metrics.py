from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any


class MidiReadError(RuntimeError):
    """Raised when a MIDI file cannot be read for benchmark metrics."""


@dataclass(frozen=True, slots=True)
class NoteEvent:
    start: float
    end: float
    pitch: int
    velocity: int = 64
    track_index: int | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiTrackInfo:
    index: int
    name: str
    program: int | None
    is_drum: bool
    note_count: int
    duration_sec: float
    min_pitch: int | None
    max_pitch: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiMetricConfig:
    onset_tolerance_sec: float = 0.12
    pitch_tolerance_semitones: int = 0
    octave_tolerance_semitones: int = 12


@dataclass(frozen=True, slots=True)
class MidiMetrics:
    expected_note_count: int
    predicted_note_count: int
    matched_note_count: int
    note_precision: float
    note_recall: float
    note_f1: float
    pitch_accuracy: float
    onset_mae_ms: float | None
    duration_overlap: float | None
    octave_error_rate: float
    semitone_error_rate: float
    unmatched_expected_count: int
    unmatched_predicted_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_midi_track_info(path: str | Path) -> list[MidiTrackInfo]:
    midi = _load_midi(path)
    track_infos: list[MidiTrackInfo] = []
    ticks_per_beat = max(1, int(midi.ticks_per_beat))
    for index, track in enumerate(midi.tracks):
        track_name = ""
        program: int | None = None
        is_drum = False
        notes = _extract_track_notes(track, ticks_per_beat=ticks_per_beat, track_index=index)
        for msg in track:
            if msg.type == "track_name" and not track_name:
                track_name = str(getattr(msg, "name", ""))
            elif msg.type == "program_change" and program is None:
                program = int(getattr(msg, "program", 0))
            channel = getattr(msg, "channel", None)
            if channel == 9:
                is_drum = True
        duration_sec = max((note.end for note in notes), default=0.0)
        pitches = [note.pitch for note in notes]
        track_infos.append(
            MidiTrackInfo(
                index=index,
                name=track_name,
                program=program,
                is_drum=is_drum,
                note_count=len(notes),
                duration_sec=duration_sec,
                min_pitch=min(pitches) if pitches else None,
                max_pitch=max(pitches) if pitches else None,
            )
        )
    return track_infos


def read_midi_notes(path: str | Path, *, track_index: int | None = None) -> list[NoteEvent]:
    midi = _load_midi(path)
    ticks_per_beat = max(1, int(midi.ticks_per_beat))
    notes: list[NoteEvent] = []
    if track_index is not None:
        if track_index < 0 or track_index >= len(midi.tracks):
            raise MidiReadError(f"MIDI track index out of range: {track_index}")
        notes.extend(_extract_track_notes(midi.tracks[track_index], ticks_per_beat=ticks_per_beat, track_index=track_index))
    else:
        for index, track in enumerate(midi.tracks):
            notes.extend(_extract_track_notes(track, ticks_per_beat=ticks_per_beat, track_index=index))
    return sorted(notes, key=lambda note: (note.start, note.pitch, note.end, note.track_index or -1))


def find_midi_track_index_by_name(path: str | Path, track_name: str) -> int | None:
    target = str(track_name or "").strip().lower()
    if not target:
        return None
    for track in read_midi_track_info(path):
        if str(track.name or "").strip().lower() == target:
            return track.index
    return None


def compute_midi_metrics(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    config: MidiMetricConfig | None = None,
) -> MidiMetrics:
    config = config or MidiMetricConfig()
    matches = _match_notes(expected_notes, predicted_notes, config=config)
    matched_count = len(matches)
    precision = _safe_div(matched_count, len(predicted_notes))
    recall = _safe_div(matched_count, len(expected_notes))
    note_f1 = _safe_div(2 * precision * recall, precision + recall)

    exact_pitch_matches = sum(1 for expected, predicted in matches if expected.pitch == predicted.pitch)
    semitone_errors = sum(1 for expected, predicted in matches if abs(expected.pitch - predicted.pitch) == 1)
    octave_errors = sum(1 for expected, predicted in matches if abs(expected.pitch - predicted.pitch) == config.octave_tolerance_semitones)
    onset_errors = [abs(expected.start - predicted.start) * 1000.0 for expected, predicted in matches]
    duration_overlaps = [_duration_iou(expected, predicted) for expected, predicted in matches]

    return MidiMetrics(
        expected_note_count=len(expected_notes),
        predicted_note_count=len(predicted_notes),
        matched_note_count=matched_count,
        note_precision=precision,
        note_recall=recall,
        note_f1=note_f1,
        pitch_accuracy=_safe_div(exact_pitch_matches, matched_count),
        onset_mae_ms=(sum(onset_errors) / len(onset_errors)) if onset_errors else None,
        duration_overlap=(sum(duration_overlaps) / len(duration_overlaps)) if duration_overlaps else None,
        octave_error_rate=_safe_div(octave_errors, matched_count),
        semitone_error_rate=_safe_div(semitone_errors, matched_count),
        unmatched_expected_count=max(0, len(expected_notes) - matched_count),
        unmatched_predicted_count=max(0, len(predicted_notes) - matched_count),
    )


def _load_midi(path: str | Path):
    try:
        import mido

        return mido.MidiFile(str(path), clip=True)
    except Exception as exc:
        raise MidiReadError(f"failed to read MIDI file {path}: {exc}") from exc


def _extract_track_notes(track: Any, *, ticks_per_beat: int, track_index: int) -> list[NoteEvent]:
    tempo = 500000
    current_ticks = 0
    active: dict[tuple[int | None, int], list[tuple[int, int, int]]] = {}
    notes: list[NoteEvent] = []
    order = 0
    for msg in track:
        current_ticks += int(getattr(msg, "time", 0) or 0)
        if msg.type == "set_tempo":
            tempo = int(getattr(msg, "tempo", tempo) or tempo)
            continue
        if msg.type not in {"note_on", "note_off"}:
            continue
        note_number = getattr(msg, "note", None)
        if note_number is None:
            continue
        channel = getattr(msg, "channel", None)
        key = (channel, int(note_number))
        velocity = int(getattr(msg, "velocity", 0) or 0)
        if msg.type == "note_on" and velocity > 0:
            active.setdefault(key, []).append((current_ticks, velocity, order))
            order += 1
            continue
        starts = active.get(key) or []
        if not starts:
            continue
        start_ticks, start_velocity, _ = starts.pop(0)
        if current_ticks <= start_ticks:
            continue
        start_sec = _ticks_to_seconds(start_ticks, ticks_per_beat=ticks_per_beat, tempo=tempo)
        end_sec = _ticks_to_seconds(current_ticks, ticks_per_beat=ticks_per_beat, tempo=tempo)
        notes.append(NoteEvent(start=start_sec, end=end_sec, pitch=int(note_number), velocity=start_velocity, track_index=track_index))
    return sorted(notes, key=lambda note: (note.start, note.pitch, note.end))


def _ticks_to_seconds(ticks: int, *, ticks_per_beat: int, tempo: int) -> float:
    return float(ticks) * float(tempo) / 1_000_000.0 / float(ticks_per_beat)


def _match_notes(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig,
) -> list[tuple[NoteEvent, NoteEvent]]:
    candidate_edges: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(expected_notes):
        for predicted_index, predicted in enumerate(predicted_notes):
            onset_delta = abs(expected.start - predicted.start)
            if onset_delta > config.onset_tolerance_sec:
                continue
            pitch_delta = abs(expected.pitch - predicted.pitch)
            if pitch_delta <= config.pitch_tolerance_semitones:
                pitch_cost = pitch_delta
            elif pitch_delta in {1, config.octave_tolerance_semitones}:
                pitch_cost = pitch_delta + 100
            else:
                continue
            duration_cost = 1.0 - _duration_iou(expected, predicted)
            cost = onset_delta + pitch_cost + duration_cost * 0.01
            candidate_edges.append((cost, expected_index, predicted_index))

    candidate_edges.sort(key=lambda edge: edge[0])
    used_expected: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[tuple[NoteEvent, NoteEvent]] = []
    for _, expected_index, predicted_index in candidate_edges:
        if expected_index in used_expected or predicted_index in used_predicted:
            continue
        used_expected.add(expected_index)
        used_predicted.add(predicted_index)
        matches.append((expected_notes[expected_index], predicted_notes[predicted_index]))
    matches.sort(key=lambda pair: (pair[0].start, pair[1].start, pair[0].pitch))
    return matches


def _duration_iou(expected: NoteEvent, predicted: NoteEvent) -> float:
    intersection = max(0.0, min(expected.end, predicted.end) - max(expected.start, predicted.start))
    union = max(expected.end, predicted.end) - min(expected.start, predicted.start)
    if union <= 0 or math.isclose(union, 0.0):
        return 0.0
    return intersection / union


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)
