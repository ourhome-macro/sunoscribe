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


if __name__ == "__main__":
    unittest.main()
