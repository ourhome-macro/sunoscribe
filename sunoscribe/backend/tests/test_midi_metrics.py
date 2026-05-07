from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import mido

from app.modules.benchmark.midi_metrics import (
    MidiMetricConfig,
    NoteEvent,
    build_midi_diagnostics,
    compute_midi_alignment_diagnostics,
    compute_midi_audibility_metrics,
    compute_midi_metrics,
    infer_midi_failure_modes,
    read_midi_notes,
)


class MidiMetricsTests(unittest.TestCase):
    def test_first_note_delay_is_relative_to_expected_first_note(self) -> None:
        expected = [NoteEvent(start=20.0, end=21.0, pitch=60)]
        predicted = [NoteEvent(start=22.0, end=23.0, pitch=60)]

        audibility = compute_midi_audibility_metrics(expected, predicted)

        self.assertEqual(audibility.expected_first_note_time_sec, 20.0)
        self.assertEqual(audibility.predicted_first_note_time_sec, 22.0)
        self.assertEqual(audibility.first_note_delay_sec, 2.0)
        self.assertEqual(audibility.duration_ratio, 23.0 / 21.0)

    def test_failure_modes_find_late_first_note_and_low_coverage(self) -> None:
        expected = [NoteEvent(start=float(index), end=float(index) + 1.0, pitch=60) for index in range(20)]
        predicted = [NoteEvent(start=40.0, end=41.0, pitch=60)]
        metrics = compute_midi_metrics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))
        audibility = compute_midi_audibility_metrics(expected, predicted)

        modes = infer_midi_failure_modes(metrics, audibility)

        self.assertIn("leading_silence_too_long", modes)
        self.assertIn("midi_coverage_too_low", modes)
        self.assertIn("too_few_predicted_notes", modes)

    def test_f1_is_diagnostic_not_failure_mode_by_itself(self) -> None:
        expected = [NoteEvent(start=float(index), end=float(index) + 1.0, pitch=60) for index in range(20)]
        predicted = [NoteEvent(start=float(index), end=float(index) + 1.0, pitch=60) for index in range(20)]
        metrics = compute_midi_metrics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))
        audibility = compute_midi_audibility_metrics(expected, predicted)
        diagnostics = build_midi_diagnostics(metrics, audibility)

        self.assertEqual(metrics.note_f1, 1.0)
        self.assertEqual(diagnostics["note_f1"], 1.0)
        self.assertEqual(infer_midi_failure_modes(metrics, audibility), [])

    def test_read_midi_notes_uses_global_tempo_map_for_type_one_midi(self) -> None:
        midi = mido.MidiFile(type=1, ticks_per_beat=100)
        tempo_track = mido.MidiTrack()
        tempo_track.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))
        midi.tracks.append(tempo_track)
        melody_track = mido.MidiTrack()
        melody_track.append(mido.Message("note_on", note=60, velocity=80, time=100, channel=0))
        melody_track.append(mido.Message("note_off", note=60, velocity=0, time=100, channel=0))
        midi.tracks.append(melody_track)

        with tempfile.TemporaryDirectory() as tmpdir:
            midi_path = Path(tmpdir) / "global_tempo.mid"
            midi.save(midi_path)

            notes = read_midi_notes(midi_path, track_index=1)

        self.assertEqual(len(notes), 1)
        self.assertAlmostEqual(notes[0].start, 1.0)
        self.assertAlmostEqual(notes[0].end, 2.0)

    def test_alignment_diagnostics_expose_octave_shift_improvement(self) -> None:
        expected = [NoteEvent(start=float(index), end=float(index) + 0.5, pitch=72) for index in range(12)]
        predicted = [NoteEvent(start=float(index), end=float(index) + 0.5, pitch=60) for index in range(12)]
        metrics = compute_midi_metrics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))
        audibility = compute_midi_audibility_metrics(expected, predicted)

        alignment = compute_midi_alignment_diagnostics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))
        diagnostics = build_midi_diagnostics(metrics, audibility, alignment)
        modes = infer_midi_failure_modes(metrics, audibility, alignment)

        self.assertEqual(alignment.best_octave_shift_semitones, 12)
        self.assertEqual(alignment.best_octave_shift_note_recall, 1.0)
        self.assertIn("alignment", diagnostics)
        self.assertIn("octave_shift_improves_alignment", modes)
        self.assertIn("possible_reference_octave_mismatch", modes)

    def test_alignment_diagnostics_expose_time_shift_improvement(self) -> None:
        expected = [NoteEvent(start=float(index), end=float(index) + 0.5, pitch=60) for index in range(12)]
        predicted = [NoteEvent(start=float(index) + 30.0, end=float(index) + 30.5, pitch=60) for index in range(12)]
        metrics = compute_midi_metrics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))
        audibility = compute_midi_audibility_metrics(expected, predicted)

        alignment = compute_midi_alignment_diagnostics(expected, predicted, config=MidiMetricConfig(onset_tolerance_sec=0.12))
        modes = infer_midi_failure_modes(metrics, audibility, alignment)

        self.assertEqual(metrics.note_recall, 0.0)
        self.assertEqual(alignment.best_time_shift_sec, -30.0)
        self.assertEqual(alignment.best_time_shift_note_recall, 1.0)
        self.assertIn("time_shift_improves_alignment", modes)
        self.assertIn("possible_reference_time_offset", modes)


if __name__ == "__main__":
    unittest.main()
