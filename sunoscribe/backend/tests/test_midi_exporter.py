import tempfile
import unittest
from pathlib import Path

from app.modules.pitch.midi_exporter import MidiExporter
from app.modules.pitch.types import NoteType, QuantizedNote


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


if __name__ == "__main__":
    unittest.main()
