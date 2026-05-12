import tempfile
import unittest
from pathlib import Path

from app.modules.pitch.midi_exporter import MidiExporter
from app.modules.pitch.types import NoteType, QuantizedNote


def _note_windows_from_items(items):
    return sorted(
        (float(item["start_time"]), float(item["end_time"]))
        for item in items
    )


def _note_windows_from_pretty_midi(notes):
    return sorted((float(note.start), float(note.end)) for note in notes)


def _short_note_ratio(note_windows, *, threshold):
    if not note_windows:
        return 0.0
    short_note_count = sum(1 for start, end in note_windows if (end - start) < threshold)
    return short_note_count / len(note_windows)


def _short_gap_ratio(note_windows, *, threshold):
    positive_gaps = [
        next_start - current_end
        for (_, current_end), (next_start, _) in zip(note_windows, note_windows[1:])
        if next_start > current_end
    ]
    if not positive_gaps:
        return 0.0
    short_gap_count = sum(1 for gap in positive_gaps if gap < threshold)
    return short_gap_count / len(positive_gaps)


def _track_signature(instrument):
    return [
        (int(note.pitch), round(float(note.start), 3), round(float(note.end), 3))
        for note in instrument.notes
    ]


class TestMidiExporter(unittest.TestCase):
    def test_export_quantized_notes_to_bytes_and_file(self):
        exporter = MidiExporter(default_velocity=96, instrument_program=0)
        notes = [
            QuantizedNote(
                pitch="C4",
                start_time=0.0,
                end_time=0.5,
                confidence=0.95,
                duration_beats=1.0,
                note_type=NoteType.QUARTER,
                measure_num=1,
                beat_position=1.0,
            ),
            QuantizedNote(
                pitch="E4",
                start_time=0.5,
                end_time=1.0,
                confidence=0.9,
                duration_beats=1.0,
                note_type=NoteType.QUARTER,
                measure_num=1,
                beat_position=2.0,
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sample.mid"
            data = exporter.export_quantized_notes(notes, bpm=120.0, output_path=out)

            self.assertGreater(len(data), 8)
            self.assertTrue(data.startswith(b"MThd"))
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 8)


    def test_midi_export_preserves_score_pitch_with_octave_reference_metrics(self):
        import pretty_midi

        exporter = MidiExporter()
        score_data = {
            "bpm": 120.0,
            "measures": [
                {
                    "measure_num": 1,
                    "notes": [
                        {
                            "pitch": "C4",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "beat_position": 1.0,
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "score.mid"
            exporter.export_from_score_data(score_data=score_data, bpm=120.0, output_path=out)
            midi = pretty_midi.PrettyMIDI(str(out))

        self.assertEqual([int(note.pitch) for note in midi.instruments[0].notes], [60])

    def test_export_from_measures(self):
        exporter = MidiExporter()
        measures = [
            {
                "measure_num": 1,
                "start_time": 0.0,
                "notes": [
                    {
                        "pitch": "G4",
                        "start_time": 0.0,
                        "end_time": 0.5,
                        "duration_beats": 1.0,
                        "note_type": "quarter",
                        "beat_position": 1.0,
                        "confidence": 0.92,
                    }
                ],
            }
        ]

        data = exporter.export_from_measures(measures=measures, bpm=110.0)
        self.assertTrue(data.startswith(b"MThd"))

    def test_export_from_score_data_writes_optional_hook_track(self):
        import pretty_midi

        exporter = MidiExporter()
        score_data = {
            "bpm": 120.0,
            "measures": [
                {
                    "measure_num": 1,
                    "notes": [
                        {
                            "pitch": "C4",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "beat_position": 1.0,
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            "instrumental_melody_notes": [
                {
                    "pitch": "G5",
                    "start_time": 1.0,
                    "end_time": 1.5,
                    "duration_beats": 1.0,
                    "measure_num": 1,
                    "beat_position": 3.0,
                    "confidence": 0.85,
                    "source": "instrumental_hook",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dual.mid"
            data = exporter.export_from_score_data(score_data=score_data, bpm=120.0, output_path=out)
            midi = pretty_midi.PrettyMIDI(str(out))

        self.assertTrue(data.startswith(b"MThd"))
        self.assertEqual([instrument.name for instrument in midi.instruments], ["Lead Vocal", "Instrumental Hook"])
        self.assertEqual([len(instrument.notes) for instrument in midi.instruments], [1, 1])
        self.assertEqual(_track_signature(midi.instruments[0]), [(60, 0.0, 0.5)])
        self.assertEqual(_track_signature(midi.instruments[1]), [(79, 1.0, 1.5)])

    def test_export_from_score_data_keeps_single_track_when_hook_empty(self):
        import pretty_midi

        exporter = MidiExporter()
        score_data = {
            "bpm": 120.0,
            "measures": [
                {
                    "measure_num": 1,
                    "notes": [
                        {
                            "pitch": "C4",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            "instrumental_melody_notes": [],
        }

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "lead.mid"
            exporter.export_from_score_data(score_data=score_data, bpm=120.0, output_path=out)
            midi = pretty_midi.PrettyMIDI(str(out))

        self.assertEqual([instrument.name for instrument in midi.instruments], ["Lead Vocal"])

    def test_export_from_score_data_preserves_lead_vocal_continuity_and_prelude_timeline(self):
        import pretty_midi

        exporter = MidiExporter()
        lead_notes = [
            {
                "pitch": "C4",
                "start_time": 8.0,
                "end_time": 8.12,
                "duration_beats": 0.25,
                "note_type": "sixteenth",
                "beat_position": 1.0,
                "confidence": 0.92,
            },
            {
                "pitch": "D4",
                "start_time": 8.17,
                "end_time": 8.67,
                "duration_beats": 1.0,
                "note_type": "quarter",
                "beat_position": 1.5,
                "confidence": 0.91,
            },
            {
                "pitch": "E4",
                "start_time": 9.27,
                "end_time": 9.39,
                "duration_beats": 0.25,
                "note_type": "sixteenth",
                "beat_position": 1.0,
                "confidence": 0.9,
            },
            {
                "pitch": "F4",
                "start_time": 9.43,
                "end_time": 10.03,
                "duration_beats": 1.25,
                "note_type": "quarter",
                "beat_position": 1.5,
                "confidence": 0.88,
            },
        ]
        score_data = {
            "bpm": 96.0,
            "measures": [
                {"measure_num": 1, "notes": lead_notes[:2]},
                {"measure_num": 2, "notes": lead_notes[2:]},
            ],
            "instrumental_melody_notes": [],
        }

        expected_windows = _note_windows_from_items(lead_notes)
        expected_short_note_ratio = _short_note_ratio(expected_windows, threshold=0.25)
        expected_short_gap_ratio = _short_gap_ratio(expected_windows, threshold=0.1)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "continuity.mid"
            exporter.export_from_score_data(score_data=score_data, bpm=96.0, output_path=out)
            midi = pretty_midi.PrettyMIDI(str(out))

        self.assertEqual([instrument.name for instrument in midi.instruments], ["Lead Vocal"])
        lead_track = midi.instruments[0]
        exported_windows = _note_windows_from_pretty_midi(lead_track.notes)

        self.assertEqual([note.pitch for note in lead_track.notes], [60, 62, 64, 65])
        self.assertAlmostEqual(lead_track.notes[0].start, 8.0, delta=0.002)
        self.assertAlmostEqual(lead_track.notes[-1].end, 10.03, delta=0.002)
        self.assertEqual(len(exported_windows), len(expected_windows))
        for (expected_start, expected_end), (actual_start, actual_end) in zip(expected_windows, exported_windows):
            self.assertAlmostEqual(actual_start, expected_start, delta=0.002)
            self.assertAlmostEqual(actual_end, expected_end, delta=0.002)
        self.assertAlmostEqual(
            _short_note_ratio(exported_windows, threshold=0.25),
            expected_short_note_ratio,
            places=6,
        )
        self.assertAlmostEqual(
            _short_gap_ratio(exported_windows, threshold=0.1),
            expected_short_gap_ratio,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
