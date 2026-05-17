from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any


MIDI_FAILURE_FRAGMENTED_MELODY_GAPS = "fragmented_melody_gaps"
MIDI_FAILURE_EXCESSIVE_SHORT_NOTES = "excessive_short_notes"
MIDI_FAILURE_LARGE_PITCH_JUMPS = "large_pitch_jumps"


class MidiReadError(RuntimeError):
    """Raised when a MIDI file cannot be read for benchmark metrics."""


@dataclass(frozen=True, slots=True)
class NoteEvent:
    start: float
    end: float
    pitch: int
    velocity: int = 64
    track_index: int | None = None
    channel: int | None = None
    program: int | None = None

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
    auto_octave_normalize: bool = True


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
    octave_shift_applied: int
    octave_shift_target: str | None
    expected_median_pitch_raw: float | None
    predicted_median_pitch_raw: float | None
    median_pitch_delta_raw: float | None
    octave_normalized_matched_note_count: int
    octave_normalized_note_precision: float
    octave_normalized_note_recall: float
    octave_normalized_note_f1: float
    octave_normalized_pitch_accuracy: float
    octave_normalized_octave_error_rate: float
    octave_normalized_mean_abs_pitch_delta: float | None
    octave_normalized_recall_lift: float
    octave_normalized_f1_lift: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiAudibilityMetrics:
    expected_first_note_time_sec: float | None
    predicted_first_note_time_sec: float | None
    first_note_delay_sec: float | None
    expected_duration_sec: float
    predicted_duration_sec: float
    duration_ratio: float | None
    midi_coverage_ratio: float
    longest_silence_sec: float
    produced_note_seconds: float
    velocity_min: int | None
    velocity_mean: float | None
    velocity_max: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiContinuityMetrics:
    note_count: int
    adjacent_pair_count: int
    gap_threshold_sec: float
    gap50_count: int
    gap50_ratio: float
    big_gap_threshold_sec: float
    big_gap_count: int
    big_gap_ratio: float
    longest_inter_note_gap_sec: float | None
    mean_inter_note_gap_sec: float | None
    short_note_threshold_sec: float
    short_note_count: int
    short_note_ratio: float
    large_jump_threshold_semitones: int
    large_jump_count: int
    large_jump_ratio: float
    phrase_gap_threshold_sec: float
    local_adjacent_pair_count: int
    local_large_jump_count: int
    local_large_jump_ratio: float
    cross_phrase_adjacent_pair_count: int
    cross_phrase_large_jump_count: int
    cross_phrase_large_jump_ratio: float
    max_abs_pitch_jump_semitones: int | None
    median_pitch: float | None
    pitch_range: list[int | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiDtwDiagnostics:
    best_dtw_octave_shift_semitones: int | None
    dtw_normalized_cost: float | None
    dtw_aligned_note_pairs: int
    dtw_pitch_match_recall_proxy: float | None
    dtw_pitch_match_precision_proxy: float | None
    dtw_mean_abs_pitch_delta: float | None
    dtw_skipped_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SmartOnsetAlignmentDiagnostics:
    pred_to_exp_shift_sec: float
    shift_corrected_recall: float
    shift_corrected_f1: float
    shift_corrected_matched: int
    shift_corrected_coverage: float
    shift_recall_gain: float
    shift_f1_gain: float
    shift_matched_gain: int
    shift_peak_support: int
    shift_peak_ratio: float | None
    shift_candidate_count: int
    alignment_diagnosis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiAlignmentDiagnostics:
    best_octave_shift_semitones: int
    best_octave_shift_note_recall: float
    best_octave_shift_note_f1: float
    best_octave_shift_matched_notes: int
    best_time_shift_sec: float
    best_time_shift_note_recall: float
    best_time_shift_note_f1: float
    best_time_shift_matched_notes: int
    expected_median_pitch: float | None
    predicted_median_pitch: float | None
    median_pitch_delta: float | None
    expected_pitch_range: list[int | None]
    predicted_pitch_range: list[int | None]
    reference_track_suspect_reasons: list[str]
    dtw: MidiDtwDiagnostics
    smart_onset_alignment: SmartOnsetAlignmentDiagnostics

    @property
    def pred_to_exp_shift_sec(self) -> float:
        return self.smart_onset_alignment.pred_to_exp_shift_sec

    @property
    def shift_corrected_recall(self) -> float:
        return self.smart_onset_alignment.shift_corrected_recall

    @property
    def shift_corrected_f1(self) -> float:
        return self.smart_onset_alignment.shift_corrected_f1

    @property
    def shift_corrected_matched(self) -> int:
        return self.smart_onset_alignment.shift_corrected_matched

    @property
    def shift_corrected_coverage(self) -> float:
        return self.smart_onset_alignment.shift_corrected_coverage

    @property
    def shift_recall_gain(self) -> float:
        return self.smart_onset_alignment.shift_recall_gain

    @property
    def shift_f1_gain(self) -> float:
        return self.smart_onset_alignment.shift_f1_gain

    @property
    def shift_matched_gain(self) -> int:
        return self.smart_onset_alignment.shift_matched_gain

    @property
    def shift_peak_support(self) -> int:
        return self.smart_onset_alignment.shift_peak_support

    @property
    def shift_peak_ratio(self) -> float | None:
        return self.smart_onset_alignment.shift_peak_ratio

    @property
    def shift_candidate_count(self) -> int:
        return self.smart_onset_alignment.shift_candidate_count

    @property
    def alignment_diagnosis(self) -> str:
        return self.smart_onset_alignment.alignment_diagnosis

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        smart = payload.get("smart_onset_alignment")
        if isinstance(smart, dict):
            payload.update(smart)
        return payload


@dataclass(frozen=True, slots=True)
class ReferenceMelodyExtraction:
    strategy: str
    source_note_count: int
    selected_note_count: int
    selected_track_index: int | None = None
    selected_channel: int | None = None
    selected_program: int | None = None
    applied: bool = False
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_midi_track_info(path: str | Path) -> list[MidiTrackInfo]:
    midi = _load_midi(path)
    track_infos: list[MidiTrackInfo] = []
    ticks_per_beat = max(1, int(midi.ticks_per_beat))
    tempo_map = _build_tempo_map(midi)
    for index, track in enumerate(midi.tracks):
        track_name = ""
        program: int | None = None
        is_drum = False
        notes = _extract_track_notes(
            track,
            ticks_per_beat=ticks_per_beat,
            track_index=index,
            tempo_map=tempo_map,
        )
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


def read_midi_notes(
    path: str | Path,
    *,
    track_index: int | None = None,
    channel: int | None = None,
    program: int | None = None,
) -> list[NoteEvent]:
    midi = _load_midi(path)
    ticks_per_beat = max(1, int(midi.ticks_per_beat))
    tempo_map = _build_tempo_map(midi)
    notes: list[NoteEvent] = []
    if track_index is not None:
        if track_index < 0 or track_index >= len(midi.tracks):
            raise MidiReadError(f"MIDI track index out of range: {track_index}")
        notes.extend(
            _extract_track_notes(
                midi.tracks[track_index],
                ticks_per_beat=ticks_per_beat,
                track_index=track_index,
                tempo_map=tempo_map,
            )
        )
    else:
        for index, track in enumerate(midi.tracks):
            notes.extend(
                _extract_track_notes(
                    track,
                    ticks_per_beat=ticks_per_beat,
                    track_index=index,
                    tempo_map=tempo_map,
                )
            )
    if channel is not None:
        notes = [note for note in notes if note.channel == channel]
    if program is not None:
        notes = [note for note in notes if note.program == program]
    return sorted(notes, key=lambda note: (note.start, note.pitch, note.end, note.track_index or -1, note.channel or -1))


def extract_reference_melody_notes(
    path: str | Path,
    *,
    track_index: int | None = None,
    strategy: str | None = None,
) -> tuple[list[NoteEvent], ReferenceMelodyExtraction]:
    normalized_strategy = str(strategy or "track").strip().lower()
    if normalized_strategy in {"", "none", "track", "selected_track"}:
        notes = read_midi_notes(path, track_index=track_index)
        return notes, ReferenceMelodyExtraction(
            strategy="track",
            source_note_count=len(notes),
            selected_note_count=len(notes),
            selected_track_index=track_index,
            applied=False,
        )

    if normalized_strategy in {"skyline", "highest_voice"}:
        source_notes = read_midi_notes(path, track_index=track_index)
        melody_notes = extract_skyline_melody(source_notes)
        return melody_notes, ReferenceMelodyExtraction(
            strategy="skyline",
            source_note_count=len(source_notes),
            selected_note_count=len(melody_notes),
            selected_track_index=track_index,
            applied=True,
            details={
                "min_duration_sec": 0.08,
                "merge_gap_sec": 0.06,
            },
        )

    if normalized_strategy in {"vocal_like_track", "vocal_like", "voice_track"}:
        source_notes = read_midi_notes(path)
        selected_notes, details = select_vocal_like_reference_notes(source_notes)
        return selected_notes, ReferenceMelodyExtraction(
            strategy="vocal_like_track",
            source_note_count=len(source_notes),
            selected_note_count=len(selected_notes),
            selected_track_index=details.get("selected_track_index"),
            selected_channel=details.get("selected_channel"),
            selected_program=details.get("selected_program"),
            applied=True,
            details=details,
        )

    raise MidiReadError(f"unknown expected reference strategy: {strategy}")


def transpose_note_events(notes: list[NoteEvent], semitones: int) -> list[NoteEvent]:
    shift = int(semitones)
    if shift == 0:
        return list(notes)
    transposed: list[NoteEvent] = []
    for note in notes:
        pitch = int(note.pitch) + shift
        if pitch < 0 or pitch > 127:
            raise MidiReadError(f"transposed reference pitch out of MIDI range: {pitch}")
        transposed.append(
            NoteEvent(
                start=note.start,
                end=note.end,
                pitch=pitch,
                velocity=note.velocity,
                track_index=note.track_index,
                channel=note.channel,
                program=note.program,
            )
        )
    return transposed


def extract_skyline_melody(
    notes: list[NoteEvent],
    *,
    min_duration_sec: float = 0.08,
    merge_gap_sec: float = 0.06,
) -> list[NoteEvent]:
    if not notes:
        return []

    events: list[tuple[float, int, int, NoteEvent]] = []
    for index, note in enumerate(notes):
        if note.end <= note.start:
            continue
        events.append((note.start, 1, index, note))
        events.append((note.end, -1, index, note))
    events.sort(key=lambda event: (event[0], -event[1], event[3].pitch, event[3].end))

    active: dict[int, NoteEvent] = {}
    last_time: float | None = None
    slices: list[NoteEvent] = []
    event_index = 0
    while event_index < len(events):
        event_time = events[event_index][0]
        if last_time is not None and event_time > last_time and active:
            source_note = max(active.values(), key=lambda note: (note.pitch, note.end, -note.start, note.velocity))
            slices.append(
                NoteEvent(
                    start=last_time,
                    end=event_time,
                    pitch=source_note.pitch,
                    velocity=source_note.velocity,
                    track_index=source_note.track_index,
                    channel=source_note.channel,
                    program=source_note.program,
                )
            )
        while event_index < len(events) and events[event_index][0] == event_time:
            _, event_type, note_index, note = events[event_index]
            if event_type == 1:
                active[note_index] = note
            else:
                active.pop(note_index, None)
            event_index += 1
        last_time = event_time

    merged: list[NoteEvent] = []
    for note in slices:
        if (
            merged
            and merged[-1].pitch == note.pitch
            and note.start - merged[-1].end <= merge_gap_sec
            and merged[-1].track_index == note.track_index
            and merged[-1].channel == note.channel
        ):
            previous = merged[-1]
            merged[-1] = NoteEvent(
                start=previous.start,
                end=max(previous.end, note.end),
                pitch=previous.pitch,
                velocity=max(previous.velocity, note.velocity),
                track_index=previous.track_index,
                channel=previous.channel,
                program=previous.program,
            )
        else:
            merged.append(note)

    return [note for note in merged if note.duration >= min_duration_sec]


def select_vocal_like_reference_notes(notes: list[NoteEvent]) -> tuple[list[NoteEvent], dict[str, Any]]:
    candidates: list[tuple[float, tuple[int | None, int | None, int | None], list[NoteEvent], dict[str, Any]]] = []
    for key, group_notes in _group_notes_by_source(notes).items():
        if not group_notes:
            continue
        track_index, channel, program = key
        if channel == 9:
            continue
        pitches = [note.pitch for note in group_notes]
        duration = max((note.end for note in group_notes), default=0.0) - min((note.start for note in group_notes), default=0.0)
        pitch_range = max(pitches) - min(pitches)
        note_count = len(group_notes)
        median_pitch = _median(pitches)
        density_per_sec = _safe_div(note_count, duration)
        score = _vocal_like_candidate_score(
            note_count=note_count,
            pitch_range=pitch_range,
            median_pitch=median_pitch,
            density_per_sec=density_per_sec,
        )
        details = {
            "track_index": track_index,
            "channel": channel,
            "program": program,
            "note_count": note_count,
            "pitch_range": pitch_range,
            "min_pitch": min(pitches),
            "max_pitch": max(pitches),
            "median_pitch": median_pitch,
            "density_per_sec": density_per_sec,
            "score": score,
        }
        candidates.append((score, key, sorted(group_notes, key=lambda note: (note.start, note.pitch, note.end)), details))

    if not candidates:
        return [], {"candidates": [], "selected_reason": "no_non_drum_candidates"}

    candidates.sort(key=lambda item: (item[0], item[3]["note_count"], item[3]["median_pitch"] or 0.0), reverse=True)
    _, selected_key, selected_notes, selected_details = candidates[0]
    return selected_notes, {
        "selected_track_index": selected_key[0],
        "selected_channel": selected_key[1],
        "selected_program": selected_key[2],
        "selected_reason": "highest_vocal_like_score",
        "selected_candidate": selected_details,
        "candidates": [candidate_details for _, _, _, candidate_details in candidates],
    }


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
    octave_normalization = _infer_octave_normalization(expected_notes, predicted_notes, config=config)
    evaluated_predicted_notes = predicted_notes
    if octave_normalization["octave_shift_applied"]:
        evaluated_predicted_notes = _shift_notes(predicted_notes, pitch_shift=int(octave_normalization["octave_shift_applied"]))

    match_config = config
    if config.auto_octave_normalize:
        match_config = MidiMetricConfig(
            onset_tolerance_sec=config.onset_tolerance_sec,
            pitch_tolerance_semitones=config.pitch_tolerance_semitones,
            octave_tolerance_semitones=-1,
            auto_octave_normalize=False,
        )
    matches = _match_notes(expected_notes, evaluated_predicted_notes, config=match_config)
    octave_matches = _match_notes(expected_notes, evaluated_predicted_notes, config=match_config, octave_equivalent=True)
    matched_count = len(matches)
    precision = _safe_div(matched_count, len(evaluated_predicted_notes))
    recall = _safe_div(matched_count, len(expected_notes))
    note_f1 = _safe_div(2 * precision * recall, precision + recall)
    octave_matched_count = len(octave_matches)
    octave_precision = _safe_div(octave_matched_count, len(evaluated_predicted_notes))
    octave_recall = _safe_div(octave_matched_count, len(expected_notes))
    octave_f1 = _safe_div(2 * octave_precision * octave_recall, octave_precision + octave_recall)

    exact_pitch_matches = sum(1 for expected, predicted in matches if expected.pitch == predicted.pitch)
    semitone_errors = sum(1 for expected, predicted in matches if abs(expected.pitch - predicted.pitch) == 1)
    octave_errors = sum(1 for expected, predicted in matches if abs(expected.pitch - predicted.pitch) == config.octave_tolerance_semitones)
    onset_errors = [abs(expected.start - predicted.start) * 1000.0 for expected, predicted in matches]
    duration_overlaps = [_duration_iou(expected, predicted) for expected, predicted in matches]
    octave_pitch_class_matches = sum(
        1 for expected, predicted in octave_matches if _pitch_class_delta(expected.pitch, predicted.pitch) <= config.pitch_tolerance_semitones
    )
    octave_equivalent_errors = sum(
        1
        for expected, predicted in octave_matches
        if expected.pitch != predicted.pitch and _pitch_class_delta(expected.pitch, predicted.pitch) <= config.pitch_tolerance_semitones
    )
    octave_abs_pitch_deltas = [abs(expected.pitch - predicted.pitch) for expected, predicted in octave_matches]

    return MidiMetrics(
        expected_note_count=len(expected_notes),
        predicted_note_count=len(evaluated_predicted_notes),
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
        unmatched_predicted_count=max(0, len(evaluated_predicted_notes) - matched_count),
        octave_shift_applied=int(octave_normalization["octave_shift_applied"]),
        octave_shift_target=octave_normalization["octave_shift_target"],
        expected_median_pitch_raw=octave_normalization["expected_median_pitch_raw"],
        predicted_median_pitch_raw=octave_normalization["predicted_median_pitch_raw"],
        median_pitch_delta_raw=octave_normalization["median_pitch_delta_raw"],
        octave_normalized_matched_note_count=octave_matched_count,
        octave_normalized_note_precision=octave_precision,
        octave_normalized_note_recall=octave_recall,
        octave_normalized_note_f1=octave_f1,
        octave_normalized_pitch_accuracy=_safe_div(octave_pitch_class_matches, octave_matched_count),
        octave_normalized_octave_error_rate=_safe_div(octave_equivalent_errors, octave_matched_count),
        octave_normalized_mean_abs_pitch_delta=(sum(octave_abs_pitch_deltas) / len(octave_abs_pitch_deltas)) if octave_abs_pitch_deltas else None,
        octave_normalized_recall_lift=octave_recall - recall,
        octave_normalized_f1_lift=octave_f1 - note_f1,
    )


def compute_midi_audibility_metrics(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
) -> MidiAudibilityMetrics:
    expected_first = min((note.start for note in expected_notes), default=None)
    predicted_first = min((note.start for note in predicted_notes), default=None)
    expected_duration = max((note.end for note in expected_notes), default=0.0)
    predicted_duration = max((note.end for note in predicted_notes), default=0.0)
    duration_basis = max(expected_duration, predicted_duration)
    first_note_delay = None
    if expected_first is not None and predicted_first is not None:
        first_note_delay = predicted_first - expected_first

    coverage_seconds, longest_silence = _coverage_and_longest_silence(predicted_notes, duration_basis=duration_basis)
    velocities = [note.velocity for note in predicted_notes]
    return MidiAudibilityMetrics(
        expected_first_note_time_sec=expected_first,
        predicted_first_note_time_sec=predicted_first,
        first_note_delay_sec=first_note_delay,
        expected_duration_sec=expected_duration,
        predicted_duration_sec=predicted_duration,
        duration_ratio=_safe_div(predicted_duration, expected_duration) if expected_duration > 0 else None,
        midi_coverage_ratio=_safe_div(coverage_seconds, duration_basis),
        longest_silence_sec=longest_silence,
        produced_note_seconds=sum(note.duration for note in predicted_notes),
        velocity_min=min(velocities) if velocities else None,
        velocity_mean=(sum(velocities) / len(velocities)) if velocities else None,
        velocity_max=max(velocities) if velocities else None,
    )


def compute_midi_continuity_metrics(
    notes: list[NoteEvent],
    *,
    gap_threshold_sec: float = 0.05,
    big_gap_threshold_sec: float = 0.5,
    short_note_threshold_sec: float = 0.18,
    large_jump_threshold_semitones: int = 7,
    phrase_gap_threshold_sec: float = 0.12,
) -> MidiContinuityMetrics:
    ordered_notes = sorted(notes, key=lambda note: (note.start, note.end, note.pitch))
    adjacent_pair_count = max(0, len(ordered_notes) - 1)
    gaps = [max(0.0, ordered_notes[index + 1].start - ordered_notes[index].end) for index in range(adjacent_pair_count)]
    pitch_jumps = [abs(int(ordered_notes[index + 1].pitch) - int(ordered_notes[index].pitch)) for index in range(adjacent_pair_count)]
    durations = [note.duration for note in ordered_notes]

    gap_count = sum(1 for gap in gaps if gap > gap_threshold_sec)
    big_gap_count = sum(1 for gap in gaps if gap > big_gap_threshold_sec)
    short_note_count = sum(1 for duration in durations if duration < short_note_threshold_sec)
    large_jump_count = sum(1 for jump in pitch_jumps if jump >= large_jump_threshold_semitones)
    local_pair_indexes = [index for index, gap in enumerate(gaps) if gap <= phrase_gap_threshold_sec]
    cross_phrase_pair_indexes = [index for index, gap in enumerate(gaps) if gap > phrase_gap_threshold_sec]
    local_large_jump_count = sum(
        1 for index in local_pair_indexes if pitch_jumps[index] >= large_jump_threshold_semitones
    )
    cross_phrase_large_jump_count = sum(
        1 for index in cross_phrase_pair_indexes if pitch_jumps[index] >= large_jump_threshold_semitones
    )
    return MidiContinuityMetrics(
        note_count=len(ordered_notes),
        adjacent_pair_count=adjacent_pair_count,
        gap_threshold_sec=float(gap_threshold_sec),
        gap50_count=gap_count,
        gap50_ratio=_safe_div(gap_count, adjacent_pair_count),
        big_gap_threshold_sec=float(big_gap_threshold_sec),
        big_gap_count=big_gap_count,
        big_gap_ratio=_safe_div(big_gap_count, adjacent_pair_count),
        longest_inter_note_gap_sec=max(gaps) if gaps else None,
        mean_inter_note_gap_sec=(sum(gaps) / len(gaps)) if gaps else None,
        short_note_threshold_sec=float(short_note_threshold_sec),
        short_note_count=short_note_count,
        short_note_ratio=_safe_div(short_note_count, len(ordered_notes)),
        large_jump_threshold_semitones=int(large_jump_threshold_semitones),
        large_jump_count=large_jump_count,
        large_jump_ratio=_safe_div(large_jump_count, adjacent_pair_count),
        phrase_gap_threshold_sec=float(phrase_gap_threshold_sec),
        local_adjacent_pair_count=len(local_pair_indexes),
        local_large_jump_count=local_large_jump_count,
        local_large_jump_ratio=_safe_div(local_large_jump_count, len(local_pair_indexes)),
        cross_phrase_adjacent_pair_count=len(cross_phrase_pair_indexes),
        cross_phrase_large_jump_count=cross_phrase_large_jump_count,
        cross_phrase_large_jump_ratio=_safe_div(cross_phrase_large_jump_count, len(cross_phrase_pair_indexes)),
        max_abs_pitch_jump_semitones=max(pitch_jumps) if pitch_jumps else None,
        median_pitch=_median_pitch(ordered_notes),
        pitch_range=_pitch_range(ordered_notes),
    )


def compute_midi_alignment_diagnostics(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    config: MidiMetricConfig | None = None,
) -> MidiAlignmentDiagnostics:
    config = config or MidiMetricConfig()
    raw_metric_config = MidiMetricConfig(
        onset_tolerance_sec=config.onset_tolerance_sec,
        pitch_tolerance_semitones=config.pitch_tolerance_semitones,
        octave_tolerance_semitones=config.octave_tolerance_semitones,
        auto_octave_normalize=False,
    )
    base_metrics = compute_midi_metrics(expected_notes, predicted_notes, config=raw_metric_config)
    strict_pitch_config = MidiMetricConfig(
        onset_tolerance_sec=config.onset_tolerance_sec,
        pitch_tolerance_semitones=config.pitch_tolerance_semitones,
        octave_tolerance_semitones=-1,
        auto_octave_normalize=False,
    )
    expected_median_pitch = _median_pitch(expected_notes)
    predicted_median_pitch = _median_pitch(predicted_notes)
    median_pitch_delta = None
    if expected_median_pitch is not None and predicted_median_pitch is not None:
        median_pitch_delta = predicted_median_pitch - expected_median_pitch

    octave_candidates: list[tuple[float, float, int, int]] = []
    for semitone_shift in (-24, -12, 0, 12, 24):
        shifted_notes = _shift_notes(predicted_notes, pitch_shift=semitone_shift)
        shifted_metrics = compute_midi_metrics(expected_notes, shifted_notes, config=strict_pitch_config)
        octave_candidates.append(
            (
                shifted_metrics.note_recall,
                shifted_metrics.note_f1,
                shifted_metrics.matched_note_count,
                semitone_shift,
            )
        )
    best_octave = max(octave_candidates, key=lambda item: (item[0], item[1], item[2], -abs(item[3])))

    time_shifts = _candidate_time_shifts(expected_notes, predicted_notes)
    time_candidates: list[tuple[float, float, int, float]] = []
    for time_shift in time_shifts:
        shifted_notes = _shift_notes(predicted_notes, time_shift=time_shift)
        shifted_metrics = compute_midi_metrics(expected_notes, shifted_notes, config=raw_metric_config)
        time_candidates.append(
            (
                shifted_metrics.note_recall,
                shifted_metrics.note_f1,
                shifted_metrics.matched_note_count,
                time_shift,
            )
        )
    best_time = max(time_candidates, key=lambda item: (item[0], item[1], item[2], -abs(item[3])))
    dtw = _compute_dtw_diagnostics(expected_notes, predicted_notes, config=config)
    public_raw_metrics = compute_midi_metrics(expected_notes, predicted_notes, config=config)
    smart_onset_alignment = _compute_smart_onset_alignment_diagnostics(
        expected_notes,
        predicted_notes,
        raw_metrics=public_raw_metrics,
        config=config,
    )

    suspect_reasons = _infer_reference_track_suspect_reasons(
        base_metrics=base_metrics,
        best_octave=best_octave,
        best_time=best_time,
        dtw=dtw,
        expected_notes=expected_notes,
        predicted_notes=predicted_notes,
        median_pitch_delta=median_pitch_delta,
    )

    return MidiAlignmentDiagnostics(
        best_octave_shift_semitones=best_octave[3],
        best_octave_shift_note_recall=best_octave[0],
        best_octave_shift_note_f1=best_octave[1],
        best_octave_shift_matched_notes=best_octave[2],
        best_time_shift_sec=best_time[3],
        best_time_shift_note_recall=best_time[0],
        best_time_shift_note_f1=best_time[1],
        best_time_shift_matched_notes=best_time[2],
        expected_median_pitch=expected_median_pitch,
        predicted_median_pitch=predicted_median_pitch,
        median_pitch_delta=median_pitch_delta,
        expected_pitch_range=_pitch_range(expected_notes),
        predicted_pitch_range=_pitch_range(predicted_notes),
        reference_track_suspect_reasons=suspect_reasons,
        dtw=dtw,
        smart_onset_alignment=smart_onset_alignment,
    )


def build_midi_diagnostics(
    metrics: MidiMetrics,
    audibility: MidiAudibilityMetrics,
    alignment: MidiAlignmentDiagnostics | None = None,
    continuity: MidiContinuityMetrics | None = None,
) -> dict[str, Any]:
    expected_count = metrics.expected_note_count
    predicted_count = metrics.predicted_note_count
    diagnostics = {
        "predicted_to_expected_note_ratio": _safe_div(predicted_count, expected_count),
        "matched_to_expected_note_ratio": _safe_div(metrics.matched_note_count, expected_count),
        "matched_to_predicted_note_ratio": _safe_div(metrics.matched_note_count, predicted_count),
        "note_f1": metrics.note_f1,
        "note_precision": metrics.note_precision,
        "note_recall": metrics.note_recall,
        "pitch_accuracy": metrics.pitch_accuracy,
        "octave_error_rate": metrics.octave_error_rate,
        "octave_shift_applied": metrics.octave_shift_applied,
        "octave_shift_target": metrics.octave_shift_target,
        "median_pitch_delta_raw": metrics.median_pitch_delta_raw,
        "octave_normalized_matched_note_count": metrics.octave_normalized_matched_note_count,
        "octave_normalized_note_f1": metrics.octave_normalized_note_f1,
        "octave_normalized_note_precision": metrics.octave_normalized_note_precision,
        "octave_normalized_note_recall": metrics.octave_normalized_note_recall,
        "octave_normalized_pitch_accuracy": metrics.octave_normalized_pitch_accuracy,
        "octave_normalized_recall_lift": metrics.octave_normalized_recall_lift,
        "octave_normalized_f1_lift": metrics.octave_normalized_f1_lift,
        "onset_mae_ms": metrics.onset_mae_ms,
        "audibility": audibility.to_dict(),
    }
    if alignment is not None:
        diagnostics["alignment"] = alignment.to_dict()
    if continuity is not None:
        diagnostics["continuity"] = continuity.to_dict()
    return diagnostics


def infer_midi_failure_modes(
    metrics: MidiMetrics,
    audibility: MidiAudibilityMetrics,
    alignment: MidiAlignmentDiagnostics | None = None,
    continuity: MidiContinuityMetrics | None = None,
) -> list[str]:
    modes: list[str] = []
    expected_count = metrics.expected_note_count
    predicted_count = metrics.predicted_note_count
    predicted_expected_ratio = _safe_div(predicted_count, expected_count)
    if predicted_count == 0:
        modes.append("no_predicted_notes")
    if predicted_expected_ratio < 0.2:
        modes.append("too_few_predicted_notes")
    if audibility.first_note_delay_sec is None:
        if predicted_count == 0:
            modes.append("missing_predicted_first_note")
        elif expected_count == 0:
            modes.append("missing_expected_first_note")
    elif audibility.first_note_delay_sec > 15.0:
        modes.append("leading_silence_too_long")
    if audibility.midi_coverage_ratio < 0.45:
        modes.append("midi_coverage_too_low")
    if max(metrics.octave_error_rate, metrics.octave_normalized_octave_error_rate) > 0.3:
        modes.append("possible_octave_error")
    if metrics.pitch_accuracy < 0.2 and metrics.octave_normalized_pitch_accuracy < 0.2:
        modes.append("pitch_detection_or_reference_mismatch")
    if metrics.pitch_accuracy >= 0.2 and metrics.note_f1 < 0.03:
        modes.append("timing_or_quantization_failure")
    if alignment is not None:
        for reason in alignment.reference_track_suspect_reasons:
            if reason not in modes:
                modes.append(reason)
        smart_diagnosis = alignment.smart_onset_alignment.alignment_diagnosis
        if smart_diagnosis == "possible_reference_time_offset" and smart_diagnosis not in modes:
            modes.append(smart_diagnosis)
    if continuity is not None and continuity.note_count >= 20:
        if continuity.gap50_ratio >= 0.65 and MIDI_FAILURE_FRAGMENTED_MELODY_GAPS not in modes:
            modes.append(MIDI_FAILURE_FRAGMENTED_MELODY_GAPS)
        if continuity.short_note_ratio >= 0.20 and MIDI_FAILURE_EXCESSIVE_SHORT_NOTES not in modes:
            modes.append(MIDI_FAILURE_EXCESSIVE_SHORT_NOTES)
        if continuity.large_jump_ratio >= 0.10 and MIDI_FAILURE_LARGE_PITCH_JUMPS not in modes:
            modes.append(MIDI_FAILURE_LARGE_PITCH_JUMPS)
    return modes


def _load_midi(path: str | Path):
    try:
        import mido

        return mido.MidiFile(str(path), clip=True)
    except Exception as exc:
        raise MidiReadError(f"failed to read MIDI file {path}: {exc}") from exc


TempoMap = tuple[tuple[int, int], ...]


def _build_tempo_map(midi: Any) -> TempoMap:
    tempo_events: list[tuple[int, int]] = []
    for track in midi.tracks:
        current_ticks = 0
        for msg in track:
            current_ticks += int(getattr(msg, "time", 0) or 0)
            if msg.type == "set_tempo":
                tempo_events.append((current_ticks, int(getattr(msg, "tempo", 500000) or 500000)))

    tempo_events.sort(key=lambda item: item[0])
    if not tempo_events or tempo_events[0][0] != 0:
        tempo_events.insert(0, (0, 500000))

    normalized: list[tuple[int, int]] = []
    for tick, tempo in tempo_events:
        if normalized and normalized[-1][0] == tick:
            normalized[-1] = (tick, tempo)
        else:
            normalized.append((tick, tempo))
    return tuple(normalized)


def _extract_track_notes(
    track: Any,
    *,
    ticks_per_beat: int,
    track_index: int,
    tempo_map: TempoMap,
) -> list[NoteEvent]:
    current_ticks = 0
    active: dict[tuple[int | None, int], list[tuple[int, int, int | None, int]]] = {}
    programs_by_channel: dict[int, int] = {}
    notes: list[NoteEvent] = []
    order = 0
    for msg in track:
        current_ticks += int(getattr(msg, "time", 0) or 0)
        if msg.type == "program_change":
            channel = getattr(msg, "channel", None)
            if channel is not None:
                programs_by_channel[int(channel)] = int(getattr(msg, "program", 0) or 0)
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
            program = programs_by_channel.get(int(channel)) if channel is not None else None
            active.setdefault(key, []).append((current_ticks, velocity, program, order))
            order += 1
            continue
        starts = active.get(key) or []
        if not starts:
            continue
        start_ticks, start_velocity, program, _ = starts.pop(0)
        if current_ticks <= start_ticks:
            continue
        start_sec = _ticks_to_seconds(start_ticks, ticks_per_beat=ticks_per_beat, tempo_map=tempo_map)
        end_sec = _ticks_to_seconds(current_ticks, ticks_per_beat=ticks_per_beat, tempo_map=tempo_map)
        notes.append(
            NoteEvent(
                start=start_sec,
                end=end_sec,
                pitch=int(note_number),
                velocity=start_velocity,
                track_index=track_index,
                channel=int(channel) if channel is not None else None,
                program=program,
            )
        )
    return sorted(notes, key=lambda note: (note.start, note.pitch, note.end))


def _ticks_to_seconds(ticks: int, *, ticks_per_beat: int, tempo_map: TempoMap) -> float:
    target_ticks = max(0, int(ticks))
    ticks_per_beat = max(1, int(ticks_per_beat))
    if not tempo_map:
        return float(target_ticks) * 500000.0 / 1_000_000.0 / float(ticks_per_beat)

    elapsed_sec = 0.0
    last_tick, active_tempo = tempo_map[0]
    if target_ticks <= last_tick:
        return float(target_ticks) * float(active_tempo) / 1_000_000.0 / float(ticks_per_beat)

    for next_tick, next_tempo in tempo_map[1:]:
        if target_ticks <= next_tick:
            elapsed_sec += (target_ticks - last_tick) * float(active_tempo) / 1_000_000.0 / float(ticks_per_beat)
            return elapsed_sec
        elapsed_sec += (next_tick - last_tick) * float(active_tempo) / 1_000_000.0 / float(ticks_per_beat)
        last_tick = next_tick
        active_tempo = next_tempo

    elapsed_sec += (target_ticks - last_tick) * float(active_tempo) / 1_000_000.0 / float(ticks_per_beat)
    return elapsed_sec


def _match_notes(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig,
    octave_equivalent: bool = False,
) -> list[tuple[NoteEvent, NoteEvent]]:
    candidate_edges: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(expected_notes):
        for predicted_index, predicted in enumerate(predicted_notes):
            onset_delta = abs(expected.start - predicted.start)
            if onset_delta > config.onset_tolerance_sec:
                continue
            pitch_cost = _pitch_match_cost(expected.pitch, predicted.pitch, config=config, octave_equivalent=octave_equivalent)
            if pitch_cost is None:
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


def _pitch_match_cost(
    expected_pitch: int,
    predicted_pitch: int,
    *,
    config: MidiMetricConfig,
    octave_equivalent: bool = False,
) -> float | None:
    pitch_delta = abs(int(expected_pitch) - int(predicted_pitch))
    if pitch_delta <= config.pitch_tolerance_semitones:
        return float(pitch_delta)
    if pitch_delta == 1:
        return float(pitch_delta + 100)
    if octave_equivalent and _pitch_class_delta(expected_pitch, predicted_pitch) <= config.pitch_tolerance_semitones:
        return float(100 + pitch_delta * 0.01)
    if config.octave_tolerance_semitones > 0 and pitch_delta == config.octave_tolerance_semitones:
        return float(pitch_delta + 100)
    return None


def _pitch_class_delta(expected_pitch: int, predicted_pitch: int) -> int:
    raw_delta = abs(int(expected_pitch) - int(predicted_pitch)) % 12
    return min(raw_delta, 12 - raw_delta)


def _infer_octave_normalization(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig,
) -> dict[str, Any]:
    expected_median = _median_pitch(expected_notes)
    predicted_median = _median_pitch(predicted_notes)
    median_delta = None
    shift = 0
    target: str | None = None
    if expected_median is not None and predicted_median is not None:
        median_delta = predicted_median - expected_median
        if config.auto_octave_normalize:
            rounded_octave_shift = round(median_delta / 12.0) * 12
            if rounded_octave_shift in {-24, -12, 12, 24} and abs(median_delta - rounded_octave_shift) <= 1.0:
                shift = -rounded_octave_shift
                target = "predicted"
    return {
        "octave_shift_applied": shift,
        "octave_shift_target": target,
        "expected_median_pitch_raw": expected_median,
        "predicted_median_pitch_raw": predicted_median,
        "median_pitch_delta_raw": median_delta,
    }


def _duration_iou(expected: NoteEvent, predicted: NoteEvent) -> float:
    intersection = max(0.0, min(expected.end, predicted.end) - max(expected.start, predicted.start))
    union = max(expected.end, predicted.end) - min(expected.start, predicted.start)
    if union <= 0 or math.isclose(union, 0.0):
        return 0.0
    return intersection / union


def _shift_notes(
    notes: list[NoteEvent],
    *,
    pitch_shift: int = 0,
    time_shift: float = 0.0,
) -> list[NoteEvent]:
    return [
        NoteEvent(
            start=float(note.start) + float(time_shift),
            end=float(note.end) + float(time_shift),
            pitch=int(note.pitch) + int(pitch_shift),
            velocity=int(note.velocity),
            track_index=note.track_index,
            channel=note.channel,
            program=note.program,
        )
        for note in notes
    ]


def _candidate_time_shifts(expected_notes: list[NoteEvent], predicted_notes: list[NoteEvent]) -> list[float]:
    candidates = {0.0}
    expected_first = min((note.start for note in expected_notes), default=None)
    predicted_first = min((note.start for note in predicted_notes), default=None)
    if expected_first is not None and predicted_first is not None:
        candidates.add(round(expected_first - predicted_first, 3))

    expected_median_start = _median([note.start for note in expected_notes])
    predicted_median_start = _median([note.start for note in predicted_notes])
    if expected_median_start is not None and predicted_median_start is not None:
        candidates.add(round(expected_median_start - predicted_median_start, 3))

    for shift in (-90.0, -60.0, -45.0, -32.0, -24.0, -16.0, -12.0, -8.0, -4.0, 4.0, 8.0, 12.0, 16.0, 24.0, 32.0, 45.0, 60.0, 90.0):
        candidates.add(shift)
    return sorted(candidates)


def _compute_smart_onset_alignment_diagnostics(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    raw_metrics: MidiMetrics,
    config: MidiMetricConfig,
    bucket_size_sec: float = 0.5,
    max_abs_shift_sec: float = 90.0,
    top_k: int = 30,
) -> SmartOnsetAlignmentDiagnostics:
    raw_recall = float(raw_metrics.octave_normalized_note_recall)
    raw_f1 = float(raw_metrics.octave_normalized_note_f1)
    raw_matched = int(raw_metrics.octave_normalized_matched_note_count)
    raw_coverage = _shift_corrected_coverage(predicted_notes, expected_notes)
    empty_result = SmartOnsetAlignmentDiagnostics(
        pred_to_exp_shift_sec=0.0,
        shift_corrected_recall=raw_recall,
        shift_corrected_f1=raw_f1,
        shift_corrected_matched=raw_matched,
        shift_corrected_coverage=raw_coverage,
        shift_recall_gain=0.0,
        shift_f1_gain=0.0,
        shift_matched_gain=0,
        shift_peak_support=0,
        shift_peak_ratio=None,
        shift_candidate_count=0,
        alignment_diagnosis="weak_alignment_signal" if expected_notes and predicted_notes else "not_shift_rescuable",
    )
    if not expected_notes or not predicted_notes:
        return empty_result

    candidates = _smart_onset_shift_candidates(
        expected_notes,
        predicted_notes,
        bucket_size_sec=bucket_size_sec,
        max_abs_shift_sec=max_abs_shift_sec,
        top_k=top_k,
    )
    if not candidates:
        return empty_result

    strict_config = MidiMetricConfig(
        onset_tolerance_sec=config.onset_tolerance_sec,
        pitch_tolerance_semitones=config.pitch_tolerance_semitones,
        octave_tolerance_semitones=config.octave_tolerance_semitones,
        auto_octave_normalize=config.auto_octave_normalize,
    )
    evaluated: list[tuple[tuple[float, float, int, float, float], SmartOnsetAlignmentDiagnostics]] = []
    for shift, support, peak_ratio in candidates:
        shifted_notes = _shift_notes(predicted_notes, time_shift=shift)
        shifted_metrics = compute_midi_metrics(expected_notes, shifted_notes, config=strict_config)
        shifted_coverage = _shift_corrected_coverage(shifted_notes, expected_notes)
        shift_recall = float(shifted_metrics.octave_normalized_note_recall)
        shift_f1 = float(shifted_metrics.octave_normalized_note_f1)
        shift_matched = int(shifted_metrics.octave_normalized_matched_note_count)
        recall_gain = shift_recall - raw_recall
        f1_gain = shift_f1 - raw_f1
        matched_gain = shift_matched - raw_matched
        diagnosis = _diagnose_smart_onset_alignment(
            shift=shift,
            raw_recall=raw_recall,
            shift_corrected_recall=shift_recall,
            shift_recall_gain=recall_gain,
            shift_matched_gain=matched_gain,
            shift_peak_support=support,
            shift_peak_ratio=peak_ratio,
        )
        result = SmartOnsetAlignmentDiagnostics(
            pred_to_exp_shift_sec=shift,
            shift_corrected_recall=shift_recall,
            shift_corrected_f1=shift_f1,
            shift_corrected_matched=shift_matched,
            shift_corrected_coverage=shifted_coverage,
            shift_recall_gain=recall_gain,
            shift_f1_gain=f1_gain,
            shift_matched_gain=matched_gain,
            shift_peak_support=int(support),
            shift_peak_ratio=peak_ratio,
            shift_candidate_count=len(candidates),
            alignment_diagnosis=diagnosis,
        )
        evaluated.append(((recall_gain, f1_gain, matched_gain, shift_recall, -abs(shift)), result))

    return max(evaluated, key=lambda item: item[0])[1]


def _smart_onset_shift_candidates(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    bucket_size_sec: float,
    max_abs_shift_sec: float,
    top_k: int,
) -> list[tuple[float, int, float | None]]:
    bucket_size = max(float(bucket_size_sec), 0.001)
    max_abs_shift = abs(float(max_abs_shift_sec))
    histogram: dict[int, int] = {}
    shift_sums: dict[int, float] = {}
    predicted_sorted = sorted(predicted_notes, key=lambda note: float(note.start))
    predicted_starts = [float(note.start) for note in predicted_sorted]
    for expected in expected_notes:
        expected_start = float(expected.start)
        left = bisect_left(predicted_starts, expected_start - max_abs_shift)
        right = bisect_right(predicted_starts, expected_start + max_abs_shift)
        for predicted in predicted_sorted[left:right]:
            if not _smart_onset_pitch_compatible(expected.pitch, predicted.pitch):
                continue
            shift = expected_start - float(predicted.start)
            bucket = int(round(shift / bucket_size))
            histogram[bucket] = histogram.get(bucket, 0) + 1
            shift_sums[bucket] = shift_sums.get(bucket, 0.0) + shift

    if not histogram:
        return [(0.0, 0, None)]

    ranked_buckets = sorted(histogram.items(), key=lambda item: (-item[1], abs(item[0])))[: max(1, int(top_k))]
    top_support = ranked_buckets[0][1]
    second_support = ranked_buckets[1][1] if len(ranked_buckets) > 1 else 0
    peak_ratio = float(top_support) / float(second_support) if second_support > 0 else None
    candidates: list[tuple[float, int, float | None]] = []
    seen: set[float] = set()
    for bucket, support in ranked_buckets:
        shift = round(shift_sums[bucket] / support, 3)
        if abs(shift) > max_abs_shift:
            continue
        if shift in seen:
            continue
        seen.add(shift)
        candidates.append((shift, int(support), peak_ratio if support == top_support else None))
    if 0.0 not in seen:
        candidates.append((0.0, histogram.get(0, 0), None))
    return candidates


def _smart_onset_pitch_compatible(expected_pitch: int, predicted_pitch: int) -> bool:
    pitch_delta = int(expected_pitch) - int(predicted_pitch)
    return pitch_delta in {-24, -12, 0, 12, 24}


def _diagnose_smart_onset_alignment(
    *,
    shift: float,
    raw_recall: float,
    shift_corrected_recall: float,
    shift_recall_gain: float,
    shift_matched_gain: int,
    shift_peak_support: int,
    shift_peak_ratio: float | None,
) -> str:
    ratio_ok = shift_peak_ratio is not None and shift_peak_ratio >= 1.5
    recall_ok = shift_recall_gain >= 0.05 or shift_corrected_recall >= raw_recall * 2.0
    if (
        abs(shift) >= 2.0
        and recall_ok
        and shift_matched_gain > 0
        and shift_peak_support >= 5
        and ratio_ok
    ):
        return "possible_reference_time_offset"
    if abs(shift) < 2.0 and shift_recall_gain >= 0.10 and shift_matched_gain >= 20:
        return "minor_onset_alignment_gain"
    if abs(shift) < 2.0:
        return "no_significant_offset"
    if shift_peak_support < 5 or not ratio_ok:
        return "weak_alignment_signal"
    return "not_shift_rescuable"


def _shift_corrected_coverage(predicted_notes: list[NoteEvent], expected_notes: list[NoteEvent]) -> float:
    expected_duration = max((note.end for note in expected_notes), default=0.0)
    predicted_duration = max((note.end for note in predicted_notes), default=0.0)
    duration_basis = max(expected_duration, predicted_duration)
    coverage_seconds, _ = _coverage_and_longest_silence(predicted_notes, duration_basis=duration_basis)
    return _safe_div(coverage_seconds, duration_basis)


_DTW_NOTE_PAIR_LIMIT = 5_000_000
_DTW_GAP_COST = 18.0


def _compute_dtw_diagnostics(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    config: MidiMetricConfig,
) -> MidiDtwDiagnostics:
    expected_count = len(expected_notes)
    predicted_count = len(predicted_notes)
    if expected_count == 0 or predicted_count == 0:
        return MidiDtwDiagnostics(
            best_dtw_octave_shift_semitones=None,
            dtw_normalized_cost=None,
            dtw_aligned_note_pairs=0,
            dtw_pitch_match_recall_proxy=None,
            dtw_pitch_match_precision_proxy=None,
            dtw_mean_abs_pitch_delta=None,
            dtw_skipped_reason="empty_note_sequence",
        )
    if expected_count * predicted_count > _DTW_NOTE_PAIR_LIMIT:
        return MidiDtwDiagnostics(
            best_dtw_octave_shift_semitones=None,
            dtw_normalized_cost=None,
            dtw_aligned_note_pairs=0,
            dtw_pitch_match_recall_proxy=None,
            dtw_pitch_match_precision_proxy=None,
            dtw_mean_abs_pitch_delta=None,
            dtw_skipped_reason="too_many_note_pairs",
        )

    expected_sorted = sorted(expected_notes, key=lambda note: (note.start, note.pitch, note.end))
    predicted_sorted = sorted(predicted_notes, key=lambda note: (note.start, note.pitch, note.end))
    expected_duration = max((note.end for note in expected_sorted), default=0.0) - min((note.start for note in expected_sorted), default=0.0)
    predicted_duration = max((note.end for note in predicted_sorted), default=0.0) - min((note.start for note in predicted_sorted), default=0.0)
    duration_basis = max(expected_duration, predicted_duration, 1.0)

    candidates: list[tuple[float, int, int, int, float]] = []
    for semitone_shift in (-24, -12, 0, 12, 24):
        shifted_notes = _shift_notes(predicted_sorted, pitch_shift=semitone_shift)
        raw_cost, aligned_pairs, pitch_matches, pitch_delta_sum = _dtw_sequence_cost(
            expected_sorted,
            shifted_notes,
            duration_basis=duration_basis,
            config=config,
        )
        path_units = max(1, expected_count + predicted_count)
        normalized_cost = raw_cost / path_units
        candidates.append((normalized_cost, semitone_shift, aligned_pairs, pitch_matches, pitch_delta_sum))

    normalized_cost, semitone_shift, aligned_pairs, pitch_matches, pitch_delta_sum = min(
        candidates,
        key=lambda item: (item[0], abs(item[1])),
    )
    return MidiDtwDiagnostics(
        best_dtw_octave_shift_semitones=semitone_shift,
        dtw_normalized_cost=normalized_cost,
        dtw_aligned_note_pairs=aligned_pairs,
        dtw_pitch_match_recall_proxy=_safe_div(pitch_matches, expected_count),
        dtw_pitch_match_precision_proxy=_safe_div(pitch_matches, predicted_count),
        dtw_mean_abs_pitch_delta=_safe_div(pitch_delta_sum, aligned_pairs),
        dtw_skipped_reason=None,
    )


def _dtw_sequence_cost(
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    *,
    duration_basis: float,
    config: MidiMetricConfig,
) -> tuple[float, int, int, float]:
    previous_row: list[tuple[float, int, int, float]] = [(0.0, 0, 0, 0.0)]
    for predicted_index in range(1, len(predicted_notes) + 1):
        prev_cost, prev_pairs, prev_matches, prev_delta = previous_row[-1]
        previous_row.append((prev_cost + _DTW_GAP_COST, prev_pairs, prev_matches, prev_delta))

    for expected_index, expected in enumerate(expected_notes, start=1):
        current_row: list[tuple[float, int, int, float]] = []
        prev_cost, prev_pairs, prev_matches, prev_delta = previous_row[0]
        current_row.append((prev_cost + _DTW_GAP_COST, prev_pairs, prev_matches, prev_delta))
        for predicted_index, predicted in enumerate(predicted_notes, start=1):
            pitch_delta = abs(expected.pitch - predicted.pitch)
            time_delta = abs(_note_relative_position(expected, duration_basis) - _note_relative_position(predicted, duration_basis))
            pair_cost = float(pitch_delta) + min(4.0, time_delta * 4.0) + (1.0 - _duration_iou(expected, predicted)) * 0.1
            diagonal = _append_dtw_pair(previous_row[predicted_index - 1], pair_cost, pitch_delta, config)
            delete_expected = _append_dtw_gap(previous_row[predicted_index])
            delete_predicted = _append_dtw_gap(current_row[predicted_index - 1])
            current_row.append(min((diagonal, delete_expected, delete_predicted), key=lambda item: (item[0], -item[2], item[3])))
        previous_row = current_row
    return previous_row[-1]


def _append_dtw_pair(
    state: tuple[float, int, int, float],
    pair_cost: float,
    pitch_delta: int,
    config: MidiMetricConfig,
) -> tuple[float, int, int, float]:
    cost, pairs, matches, pitch_delta_sum = state
    pitch_match = pitch_delta <= config.pitch_tolerance_semitones
    return (cost + pair_cost, pairs + 1, matches + (1 if pitch_match else 0), pitch_delta_sum + pitch_delta)


def _append_dtw_gap(state: tuple[float, int, int, float]) -> tuple[float, int, int, float]:
    cost, pairs, matches, pitch_delta_sum = state
    return (cost + _DTW_GAP_COST, pairs, matches, pitch_delta_sum)


def _note_relative_position(note: NoteEvent, duration_basis: float) -> float:
    return _safe_div(float(note.start), duration_basis)


def _infer_reference_track_suspect_reasons(
    *,
    base_metrics: MidiMetrics,
    best_octave: tuple[float, float, int, int],
    best_time: tuple[float, float, int, float],
    dtw: MidiDtwDiagnostics,
    expected_notes: list[NoteEvent],
    predicted_notes: list[NoteEvent],
    median_pitch_delta: float | None,
) -> list[str]:
    reasons: list[str] = []
    if not expected_notes or not predicted_notes:
        return reasons

    base_recall = float(base_metrics.note_recall)
    octave_recall, _, octave_matched, octave_shift = best_octave
    time_recall, _, time_matched, time_shift = best_time
    expected_first = min(note.start for note in expected_notes)
    predicted_first = min(note.start for note in predicted_notes)

    octave_shift_plausible = (
        abs(octave_shift) in {12, 24}
        and octave_matched >= max(3, int(base_metrics.expected_note_count * 0.05))
        and (octave_matched >= base_metrics.matched_note_count + 3 or base_metrics.octave_error_rate > 0.3)
    )
    if octave_shift_plausible:
        reasons.append("octave_shift_improves_alignment")
    if octave_shift_plausible and octave_recall >= max(0.05, base_recall * 0.8):
        reasons.append("possible_reference_octave_mismatch")
    if abs(time_shift) >= 15.0 and time_matched >= max(3, base_metrics.matched_note_count + 3):
        reasons.append("time_shift_improves_alignment")
    if time_recall >= max(0.05, base_recall * 2.0) and time_matched >= max(5, base_metrics.matched_note_count + 5):
        reasons.append("possible_reference_time_offset")
    if expected_first + 15.0 < predicted_first and base_metrics.matched_note_count < 10:
        reasons.append("expected_track_starts_before_vocal")
    if median_pitch_delta is not None and abs(median_pitch_delta) >= 10.0 and base_metrics.pitch_accuracy < 0.2:
        reasons.append("median_pitch_range_mismatch")
    if dtw.dtw_skipped_reason is None and dtw.dtw_pitch_match_recall_proxy is not None:
        dtw_recall = float(dtw.dtw_pitch_match_recall_proxy)
        if dtw_recall >= max(0.05, base_recall * 2.0) and dtw.dtw_aligned_note_pairs >= max(5, base_metrics.matched_note_count + 5):
            reasons.append("dtw_alignment_improves_recall")
        if dtw_recall >= max(0.5, time_recall * 2.0) and dtw.dtw_mean_abs_pitch_delta is not None and dtw.dtw_mean_abs_pitch_delta <= 2.0:
            reasons.append("possible_nonlinear_time_alignment")
        if dtw.dtw_mean_abs_pitch_delta is not None and dtw.dtw_mean_abs_pitch_delta >= 7.0 and dtw_recall < 0.05:
            reasons.append("possible_reference_sequence_mismatch")
    return reasons


def _median_pitch(notes: list[NoteEvent]) -> float | None:
    return _median([note.pitch for note in notes])


def _median(values: list[float | int]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(float(value) for value in values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2.0


def _pitch_range(notes: list[NoteEvent]) -> list[int | None]:
    if not notes:
        return [None, None]
    pitches = [int(note.pitch) for note in notes]
    return [min(pitches), max(pitches)]


def _group_notes_by_source(notes: list[NoteEvent]) -> dict[tuple[int | None, int | None, int | None], list[NoteEvent]]:
    groups: dict[tuple[int | None, int | None, int | None], list[NoteEvent]] = {}
    for note in notes:
        groups.setdefault((note.track_index, note.channel, note.program), []).append(note)
    return groups


def _vocal_like_candidate_score(
    *,
    note_count: int,
    pitch_range: int,
    median_pitch: float | None,
    density_per_sec: float,
) -> float:
    score = 0.0
    if 100 <= note_count <= 600:
        score += 3.0
    elif 60 <= note_count < 100 or 600 < note_count <= 900:
        score += 1.0
    else:
        score -= 3.0

    if 12 <= pitch_range <= 36:
        score += 2.0
    elif 8 <= pitch_range < 12 or 36 < pitch_range <= 48:
        score += 0.5
    else:
        score -= 2.0

    if median_pitch is not None:
        if 50 <= median_pitch <= 76:
            score += 2.0
        elif 45 <= median_pitch < 50 or 76 < median_pitch <= 84:
            score += 0.5
        else:
            score -= 1.0

    if 0.2 <= density_per_sec <= 3.0:
        score += 1.0
    elif density_per_sec > 5.0:
        score -= 1.0
    return score


def _coverage_and_longest_silence(notes: list[NoteEvent], *, duration_basis: float) -> tuple[float, float]:
    if duration_basis <= 0:
        return 0.0, 0.0
    intervals = sorted((max(0.0, note.start), min(duration_basis, note.end)) for note in notes if note.end > note.start)
    coverage = 0.0
    longest_silence = 0.0
    current_end = 0.0
    for start, end in intervals:
        if end <= start:
            continue
        if start > current_end:
            longest_silence = max(longest_silence, start - current_end)
            coverage += end - start
            current_end = end
        elif end > current_end:
            coverage += end - current_end
            current_end = end
    longest_silence = max(longest_silence, duration_basis - current_end)
    return coverage, longest_silence


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)
