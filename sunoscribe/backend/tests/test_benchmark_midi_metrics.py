from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.midi_metrics import (
    MidiMetricConfig,
    compute_midi_metrics,
    read_midi_notes,
    read_midi_track_info,
)


def _write_midi(path: Path, notes: list[tuple[float, float, int]], *, track_name: str = "melody") -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(program=0, name=track_name)
    for start, end, pitch in notes:
        instrument.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end))
    midi.instruments.append(instrument)
    midi.write(str(path))


class BenchmarkMidiMetricsTests(unittest.TestCase):
    def test_read_midi_track_info_and_notes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            midi_path = Path(temp_dir) / "song.mid"
            _write_midi(midi_path, [(0.0, 0.5, 60), (1.0, 1.5, 62)])

            tracks = read_midi_track_info(midi_path)
            notes = read_midi_notes(midi_path, track_index=1)

            self.assertGreaterEqual(len(tracks), 2)
            self.assertEqual(tracks[1].note_count, 2)
            self.assertEqual([note.pitch for note in notes], [60, 62])

    def test_compute_metrics_for_exact_and_octave_errors(self) -> None:
        expected = [
            _note(0.0, 0.5, 60),
            _note(1.0, 1.5, 62),
            _note(2.0, 2.5, 64),
        ]
        predicted = [
            _note(0.02, 0.52, 60),
            _note(1.05, 1.45, 74),
            _note(3.0, 3.5, 67),
        ]

        metrics = compute_midi_metrics(
            expected,
            predicted,
            config=MidiMetricConfig(onset_tolerance_sec=0.12, auto_octave_normalize=False),
        )

        self.assertEqual(metrics.matched_note_count, 2)
        self.assertAlmostEqual(metrics.note_precision, 2 / 3)
        self.assertAlmostEqual(metrics.note_recall, 2 / 3)
        self.assertAlmostEqual(metrics.pitch_accuracy, 1 / 2)
        self.assertAlmostEqual(metrics.octave_error_rate, 1 / 2)
        self.assertIsNotNone(metrics.onset_mae_ms)

    def test_auto_octave_normalize_handles_two_octaves(self) -> None:
        expected = [
            _note(0.0, 0.5, 60),
            _note(1.0, 1.5, 62),
            _note(2.0, 2.5, 64),
        ]
        predicted = [
            _note(0.02, 0.52, 84),
            _note(1.02, 1.52, 86),
            _note(2.02, 2.52, 88),
        ]

        metrics = compute_midi_metrics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))

        self.assertEqual(metrics.octave_shift_applied, -24)
        self.assertEqual(metrics.matched_note_count, 3)
        self.assertAlmostEqual(metrics.note_recall, 1.0)
        self.assertAlmostEqual(metrics.pitch_accuracy, 1.0)


def _note(start: float, end: float, pitch: int):
    from app.modules.benchmark.midi_metrics import NoteEvent

    return NoteEvent(start=start, end=end, pitch=pitch)


if __name__ == "__main__":
    unittest.main()
