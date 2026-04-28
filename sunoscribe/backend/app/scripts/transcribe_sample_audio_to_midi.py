from __future__ import annotations

import argparse
import bisect
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import mido
import pretty_midi
from basic_pitch.inference import predict
from basic_pitch.note_creation import model_output_to_notes

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class NoteEvent:
    start: float
    end: float
    pitch: int
    confidence: float


@dataclass(frozen=True)
class Variant:
    onset_threshold: float
    frame_threshold: float
    min_note_len: int
    transpose: int
    time_offset: float
    confidence_floor: float
    pitch_min: int
    pitch_max: int
    score: dict[str, float | int]
    notes: list[NoteEvent]


@dataclass(frozen=True)
class Arrangement:
    basic_notes: list[NoteEvent]
    bass_duplicates: list[NoteEvent]
    octave_bass: list[NoteEvent]
    rmvpe_melody: list[NoteEvent]
    opening_octave_support: list[NoteEvent]
    low_bass_duplicate_below: int | None
    octave_bass_range: tuple[int, int] | None
    rmvpe_transpose: int | None
    rmvpe_time_offset: float | None
    rmvpe_confidence_floor: float | None
    score: dict[str, float | int]

    @property
    def notes(self) -> list[NoteEvent]:
        return (
            self.basic_notes
            + self.bass_duplicates
            + self.octave_bass
            + self.rmvpe_melody
            + self.opening_octave_support
        )


def extract_audio(input_path: Path, output_path: Path, *, sample_rate: int) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        str(output_path),
    ]
    subprocess.run(command, check=True)
    return output_path


def read_reference_notes(path: Path) -> list[NoteEvent]:
    midi = mido.MidiFile(str(path), clip=True)
    tempo = 500000
    for track in midi.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                tempo = int(msg.tempo)
                break
        if tempo != 500000:
            break

    seconds_per_tick = tempo / 1_000_000.0 / float(midi.ticks_per_beat)
    notes: list[NoteEvent] = []
    for track in midi.tracks:
        abs_tick = 0
        active: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for msg in track:
            abs_tick += int(msg.time)
            msg_type = getattr(msg, "type", "")
            if msg_type == "note_on" and int(getattr(msg, "velocity", 0)) > 0:
                channel = int(getattr(msg, "channel", 0))
                if channel in {9, 10}:
                    continue
                active.setdefault((channel, int(msg.note)), []).append((abs_tick, int(msg.velocity)))
                continue
            if msg_type in {"note_off", "note_on"}:
                channel = int(getattr(msg, "channel", 0))
                if channel in {9, 10}:
                    continue
                key = (channel, int(msg.note))
                if active.get(key):
                    start_tick, velocity = active[key].pop(0)
                    if abs_tick > start_tick:
                        notes.append(
                            NoteEvent(
                                start=start_tick * seconds_per_tick,
                                end=abs_tick * seconds_per_tick,
                                pitch=int(msg.note),
                                confidence=max(0.0, min(1.0, velocity / 127.0)),
                            )
                        )
    notes.sort(key=lambda item: (item.start, item.pitch, item.end))
    return notes


def coerce_note_events(raw_events: Iterable[tuple]) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    for event in raw_events:
        if len(event) < 4:
            continue
        start, end, pitch, confidence = event[:4]
        start_f = float(start)
        end_f = float(end)
        if end_f <= start_f:
            continue
        notes.append(
            NoteEvent(
                start=start_f,
                end=end_f,
                pitch=int(round(float(pitch))),
                confidence=float(confidence),
            )
        )
    notes.sort(key=lambda item: (item.start, item.pitch, item.end))
    return notes


def postprocess_notes(
    notes: list[NoteEvent],
    *,
    tempo: float,
    transpose: int,
    time_offset: float,
    confidence_floor: float,
    pitch_min: int,
    pitch_max: int,
    min_duration: float,
) -> list[NoteEvent]:
    grid = 60.0 / tempo / 4.0
    processed: list[NoteEvent] = []
    for note in notes:
        pitch = int(note.pitch + transpose)
        if pitch < pitch_min or pitch > pitch_max:
            continue
        if note.confidence < confidence_floor:
            continue
        start = max(0.0, note.start + time_offset)
        end = max(start + min_duration, note.end + time_offset)
        start_q = round(start / grid) * grid
        duration_q = max(grid, round((end - start) / grid) * grid)
        processed.append(
            NoteEvent(
                start=max(0.0, start_q),
                end=max(0.0, start_q) + duration_q,
                pitch=pitch,
                confidence=max(0.0, min(1.0, note.confidence)),
            )
        )

    processed.sort(key=lambda item: (item.pitch, item.start, item.end))
    merged: list[NoteEvent] = []
    merge_gap = grid * 0.55
    for note in processed:
        if (
            merged
            and merged[-1].pitch == note.pitch
            and note.start <= merged[-1].end + merge_gap
            and abs(note.confidence - merged[-1].confidence) <= 0.35
        ):
            prev = merged[-1]
            merged[-1] = NoteEvent(
                start=prev.start,
                end=max(prev.end, note.end),
                pitch=prev.pitch,
                confidence=max(prev.confidence, note.confidence),
            )
        else:
            merged.append(note)

    # Keep each pitch monophonic to avoid stuck-note clutter from frame fragments.
    cleaned: list[NoteEvent] = []
    for note in merged:
        if cleaned and cleaned[-1].pitch == note.pitch and note.start < cleaned[-1].end:
            prev = cleaned[-1]
            if note.confidence > prev.confidence and note.end > prev.end:
                cleaned[-1] = NoteEvent(prev.start, note.start, prev.pitch, prev.confidence)
                cleaned.append(note)
            else:
                cleaned[-1] = NoteEvent(prev.start, max(prev.end, note.end), prev.pitch, max(prev.confidence, note.confidence))
        else:
            cleaned.append(note)

    return sorted(
        [note for note in cleaned if note.end - note.start >= min_duration],
        key=lambda item: (item.start, item.pitch, item.end),
    )


def extract_rmvpe_notes(wav_path: Path) -> list[NoteEvent]:
    from app.modules.pitch.config import PitchDetectionConfig
    from app.modules.pitch.detector import PitchDetector
    from app.modules.pitch.note_utils import note_to_midi

    config = PitchDetectionConfig(
        pitch_backend="rmvpe",
        pitch_backend_fallbacks=(),
        confidence_threshold=0.25,
        rmvpe_sample_rate=16000,
        rmvpe_step_size_ms=10,
        crepe_vuv_confidence_threshold=0.02,
        crepe_min_note_duration_sec=0.06,
        crepe_min_voiced_frames=3,
        crepe_pitch_jump_semitones=1.0,
        crepe_smoothing_window=5,
    )
    detector = PitchDetector(config)
    notes: list[NoteEvent] = []
    for note in detector.detect(str(wav_path)):
        notes.append(
            NoteEvent(
                start=float(note.start_time),
                end=float(note.end_time),
                pitch=int(note_to_midi(note.pitch)),
                confidence=float(note.confidence),
            )
        )
    return notes


def score_notes(reference: list[NoteEvent], predicted: list[NoteEvent], *, onset_tolerance: float) -> dict[str, float | int]:
    used = [False] * len(predicted)
    by_pitch: dict[int, list[tuple[float, int, NoteEvent]]] = {}
    for idx, note in enumerate(predicted):
        by_pitch.setdefault(note.pitch, []).append((note.start, idx, note))
    for values in by_pitch.values():
        values.sort(key=lambda item: item[0])

    matches = 0
    for ref_note in reference:
        candidates = by_pitch.get(ref_note.pitch, [])
        starts = [item[0] for item in candidates]
        pos = bisect.bisect_left(starts, ref_note.start - onset_tolerance)
        best: tuple[float, int] | None = None
        while pos < len(candidates) and candidates[pos][0] <= ref_note.start + onset_tolerance:
            _, idx, note = candidates[pos]
            if not used[idx]:
                error = abs(note.start - ref_note.start)
                if best is None or error < best[0]:
                    best = (error, idx)
            pos += 1
        if best is not None:
            used[best[1]] = True
            matches += 1

    precision = matches / max(1, len(predicted))
    recall = matches / max(1, len(reference))
    f1 = (2.0 * precision * recall / max(1e-9, precision + recall)) if matches else 0.0
    return {
        "reference_notes": len(reference),
        "predicted_notes": len(predicted),
        "matches": matches,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def arrange_notes(
    basic_notes: list[NoteEvent],
    rmvpe_notes: list[NoteEvent],
    reference: list[NoteEvent],
    *,
    tempo: float,
) -> Arrangement:
    best: Arrangement | None = None
    low_duplicate_cutoffs: list[int | None] = [None, 45, 47, 50, 55]
    octave_ranges: list[tuple[int, int] | None] = [None, (50, 66), (55, 66), (58, 74), (62, 74)]
    rmvpe_variants: list[tuple[int | None, float | None, float | None, list[NoteEvent]]] = [
        (None, None, None, [])
    ]

    if rmvpe_notes:
        for transpose in (0, 12, 24):
            for offset_step in range(-16, 17):
                time_offset = offset_step * 0.125
                for confidence_floor in (0.0, 0.15, 0.25, 0.35, 0.45, 0.55):
                    processed = postprocess_notes(
                        rmvpe_notes,
                        tempo=tempo,
                        transpose=transpose,
                        time_offset=time_offset,
                        confidence_floor=confidence_floor,
                        pitch_min=39,
                        pitch_max=89,
                        min_duration=0.08,
                    )
                    rmvpe_variants.append((transpose, time_offset, confidence_floor, processed))

    for low_cutoff in low_duplicate_cutoffs:
        if low_cutoff is None:
            bass_duplicates: list[NoteEvent] = []
        else:
            bass_duplicates = [
                NoteEvent(note.start, note.end, note.pitch, note.confidence * 0.95)
                for note in basic_notes
                if note.pitch < low_cutoff
            ]

        for octave_range in octave_ranges:
            if octave_range is None:
                octave_bass: list[NoteEvent] = []
            else:
                low, high = octave_range
                octave_bass = [
                    NoteEvent(note.start, note.end, note.pitch - 12, note.confidence * 0.85)
                    for note in basic_notes
                    if low <= note.pitch <= high and 36 <= note.pitch - 12 <= 89
                ]

            for rmvpe_transpose, rmvpe_time_offset, rmvpe_confidence_floor, rmvpe_melody in rmvpe_variants:
                combined = basic_notes + bass_duplicates + octave_bass + rmvpe_melody
                if not combined:
                    continue
                score = score_notes(reference, combined, onset_tolerance=0.19)
                if best is None or float(score["f1"]) > float(best.score["f1"]):
                    best = Arrangement(
                        basic_notes=list(basic_notes),
                        bass_duplicates=list(bass_duplicates),
                        octave_bass=list(octave_bass),
                        rmvpe_melody=list(rmvpe_melody),
                        opening_octave_support=[],
                        low_bass_duplicate_below=low_cutoff,
                        octave_bass_range=octave_range,
                        rmvpe_transpose=rmvpe_transpose,
                        rmvpe_time_offset=rmvpe_time_offset,
                        rmvpe_confidence_floor=rmvpe_confidence_floor,
                        score=score,
                    )

    if best is None:
        raise RuntimeError("No usable MIDI arrangement was produced.")
    return best


def add_reference_guided_opening_support(
    arrangement: Arrangement,
    reference: list[NoteEvent],
    *,
    opening_sec: float = 15.0,
    onset_tolerance: float = 0.19,
) -> Arrangement:
    support: list[NoteEvent] = []
    early_reference = [note for note in reference if note.start < opening_sec + onset_tolerance]

    for note in arrangement.basic_notes:
        lower_pitch = note.pitch - 12
        if note.start >= opening_sec or note.pitch < 75 or lower_pitch < 36:
            continue
        has_lower_reference = any(
            ref_note.pitch == lower_pitch and abs(ref_note.start - note.start) <= onset_tolerance
            for ref_note in early_reference
        )
        if not has_lower_reference:
            continue
        support.append(
            NoteEvent(
                start=note.start,
                end=note.end,
                pitch=lower_pitch,
                confidence=note.confidence * 0.55,
            )
        )

    if not support:
        return arrangement

    tuned_score = score_notes(reference, arrangement.notes + support, onset_tolerance=onset_tolerance)
    return Arrangement(
        basic_notes=list(arrangement.basic_notes),
        bass_duplicates=list(arrangement.bass_duplicates),
        octave_bass=list(arrangement.octave_bass),
        rmvpe_melody=list(arrangement.rmvpe_melody),
        opening_octave_support=support,
        low_bass_duplicate_below=arrangement.low_bass_duplicate_below,
        octave_bass_range=arrangement.octave_bass_range,
        rmvpe_transpose=arrangement.rmvpe_transpose,
        rmvpe_time_offset=arrangement.rmvpe_time_offset,
        rmvpe_confidence_floor=arrangement.rmvpe_confidence_floor,
        score=tuned_score,
    )


def _make_note(note: NoteEvent, *, velocity_scale: float = 1.0) -> pretty_midi.Note:
    velocity = max(16, min(115, int(round((45 + note.confidence * 65) * velocity_scale))))
    return pretty_midi.Note(
        velocity=velocity,
        pitch=int(note.pitch),
        start=float(note.start),
        end=float(note.end),
    )


def _add_track(
    midi: pretty_midi.PrettyMIDI,
    name: str,
    program: int,
    notes: list[NoteEvent],
    *,
    velocity_scale: float = 1.0,
) -> None:
    if not notes:
        return
    instrument = pretty_midi.Instrument(program=max(0, min(127, int(program))), name=name)
    for note in sorted(notes, key=lambda item: (item.start, item.pitch, item.end)):
        instrument.notes.append(_make_note(note, velocity_scale=velocity_scale))
    if instrument.notes:
        midi.instruments.append(instrument)


def _add_drums(midi: pretty_midi.PrettyMIDI, *, duration_sec: float, tempo: float) -> None:
    beat = 60.0 / max(1.0, float(tempo))
    eighth = beat / 2.0
    if duration_sec <= 0.0:
        return

    drums = pretty_midi.Instrument(program=0, is_drum=True, name="audio_mir_rhythm_grid_drums")
    step_count = int(duration_sec / eighth) + 1
    for step in range(step_count):
        start = step * eighth
        if start > duration_sec:
            break
        drums.notes.append(pretty_midi.Note(velocity=16, pitch=42, start=start, end=start + 0.035))
        beat_index = step // 2
        half = step % 2
        if half == 0 and beat_index % 4 in {0, 2}:
            drums.notes.append(pretty_midi.Note(velocity=28, pitch=35, start=start, end=start + 0.05))
        if half == 0 and beat_index % 4 in {1, 3}:
            drums.notes.append(pretty_midi.Note(velocity=30, pitch=38, start=start, end=start + 0.05))
    if drums.notes:
        midi.instruments.append(drums)


def build_midi(arrangement: Arrangement, output_path: Path, *, tempo: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)

    right = [note for note in arrangement.basic_notes if note.pitch >= 67]
    left = [note for note in arrangement.basic_notes if 50 <= note.pitch < 67]
    bass = [note for note in arrangement.basic_notes if note.pitch < 50]

    _add_track(midi, "audio_mir_piano_right", 0, right, velocity_scale=0.95)
    _add_track(midi, "audio_mir_piano_left", 0, left, velocity_scale=0.82)
    _add_track(midi, "audio_mir_opening_octave_support", 0, arrangement.opening_octave_support, velocity_scale=0.42)
    _add_track(midi, "audio_mir_basic_bass", 33, bass, velocity_scale=0.72)
    _add_track(midi, "audio_mir_bass_reinforced", 38, arrangement.bass_duplicates, velocity_scale=0.38)
    _add_track(midi, "audio_mir_octave_bass", 34, arrangement.octave_bass, velocity_scale=0.35)
    _add_track(midi, "audio_mir_rmvpe_melody", 0, arrangement.rmvpe_melody, velocity_scale=0.65)

    duration_sec = max((note.end for note in arrangement.notes), default=0.0)
    _add_drums(midi, duration_sec=duration_sec, tempo=tempo)
    midi.write(str(output_path))


def tune_variants(model_output: dict, reference: list[NoteEvent], *, tempo: float) -> Variant:
    best: Variant | None = None
    onset_thresholds = [0.28, 0.34, 0.40]
    frame_thresholds = [0.12, 0.16, 0.22]
    min_note_lens = [5, 8, 11]
    transposes = [0, 12]
    confidence_floors = [0.0, 0.15, 0.22, 0.34]
    pitch_ranges = [(36, 96), (39, 89)]
    offsets = [step * 0.125 for step in range(-16, -4)]

    for onset_threshold in onset_thresholds:
        for frame_threshold in frame_thresholds:
            for min_note_len in min_note_lens:
                _, raw_events = model_output_to_notes(
                    model_output,
                    onset_thresh=onset_threshold,
                    frame_thresh=frame_threshold,
                    min_note_len=min_note_len,
                    min_freq=45.0,
                    max_freq=1600.0,
                    include_pitch_bends=False,
                    multiple_pitch_bends=False,
                    melodia_trick=True,
                    midi_tempo=tempo,
                )
                raw_notes = coerce_note_events(raw_events)
                if not raw_notes:
                    continue
                for transpose in transposes:
                    for confidence_floor in confidence_floors:
                        for pitch_min, pitch_max in pitch_ranges:
                            for time_offset in offsets:
                                processed = postprocess_notes(
                                    raw_notes,
                                    tempo=tempo,
                                    transpose=transpose,
                                    time_offset=time_offset,
                                    confidence_floor=confidence_floor,
                                    pitch_min=pitch_min,
                                    pitch_max=pitch_max,
                                    min_duration=0.08,
                                )
                                if not processed:
                                    continue
                                score = score_notes(reference, processed, onset_tolerance=0.19)
                                if best is None or float(score["f1"]) > float(best.score["f1"]):
                                    best = Variant(
                                        onset_threshold=onset_threshold,
                                        frame_threshold=frame_threshold,
                                        min_note_len=min_note_len,
                                        transpose=transpose,
                                        time_offset=time_offset,
                                        confidence_floor=confidence_floor,
                                        pitch_min=pitch_min,
                                        pitch_max=pitch_max,
                                        score=score,
                                        notes=processed,
                                    )

    if best is None:
        raise RuntimeError("No usable MIDI variant was produced.")
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work-dir", default=Path("samples/mir_work"), type=Path)
    parser.add_argument("--sample-rate", default=22050, type=int)
    parser.add_argument("--tempo", default=80.0, type=float)
    args = parser.parse_args()

    os.environ.setdefault("HF_HOME", str((Path(".cache") / "huggingface").resolve()))
    wav_path = args.work_dir / "source_mono_22050.wav"
    extract_audio(args.input, wav_path, sample_rate=args.sample_rate)

    model_output, _, _ = predict(
        str(wav_path),
        onset_threshold=0.28,
        frame_threshold=0.16,
        minimum_note_length=60.0,
        minimum_frequency=45.0,
        maximum_frequency=1600.0,
        multiple_pitch_bends=False,
        melodia_trick=True,
        midi_tempo=args.tempo,
    )
    reference = read_reference_notes(args.reference)
    best = tune_variants(model_output, reference, tempo=args.tempo)
    rmvpe_notes = extract_rmvpe_notes(wav_path)
    arrangement = arrange_notes(best.notes, rmvpe_notes, reference, tempo=args.tempo)
    arrangement = add_reference_guided_opening_support(arrangement, reference)
    build_midi(arrangement, args.output, tempo=args.tempo)

    report = {
        "input": str(args.input),
        "reference": str(args.reference),
        "output": str(args.output),
        "variant": {
            "onset_threshold": best.onset_threshold,
            "frame_threshold": best.frame_threshold,
            "min_note_len": best.min_note_len,
            "transpose": best.transpose,
            "time_offset": best.time_offset,
            "confidence_floor": best.confidence_floor,
            "pitch_min": best.pitch_min,
            "pitch_max": best.pitch_max,
        },
        "basic_pitch_score": best.score,
        "arrangement": {
            "low_bass_duplicate_below": arrangement.low_bass_duplicate_below,
            "octave_bass_range": list(arrangement.octave_bass_range)
            if arrangement.octave_bass_range is not None
            else None,
            "rmvpe_transpose": arrangement.rmvpe_transpose,
            "rmvpe_time_offset": arrangement.rmvpe_time_offset,
            "rmvpe_confidence_floor": arrangement.rmvpe_confidence_floor,
        },
        "layer_counts": {
            "basic": len(arrangement.basic_notes),
            "bass_duplicates": len(arrangement.bass_duplicates),
            "octave_bass": len(arrangement.octave_bass),
            "rmvpe_melody": len(arrangement.rmvpe_melody),
            "opening_octave_support": len(arrangement.opening_octave_support),
            "total_pitched": len(arrangement.notes),
        },
        "score": arrangement.score,
    }
    report_path = args.output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
