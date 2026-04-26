import unittest

from app.modules.analysis_ir.types import AnalysisIR, AnalysisIRMeta, ChordSpan, FormSection
from app.modules.pitch.types import MetaInfo, Note, PitchAnalysisResult
from app.modules.score_ir import ScoreIRBuilder, ScoreIRSerializer


class TestScoreIRBuilder(unittest.TestCase):
    def test_build_uses_analysis_ir_for_lead_chords_bass_and_sections(self):
        builder = ScoreIRBuilder()
        pitch_result = PitchAnalysisResult(
            version="1.4",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.81,
                duration_sec=4.0,
                time_signature="4/4",
                rhythm_type="stable",
                total_measures=2,
            ),
            analysis_info={"detector": "crepe", "quantize_mode": "adaptive"},
            measures=[
                {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "is_anacrusis": False, "notes": []},
                {"measure_num": 2, "start_time": 2.0, "end_time": 4.0, "is_anacrusis": False, "notes": []},
            ],
            lead_notes=[],
            raw_notes=[],
        )
        analysis_ir = AnalysisIR(
            version="analysis_ir_v1",
            meta=AnalysisIRMeta(
                source_version="1.4",
                bpm=120.0,
                key="C Major",
                time_signature="4/4",
                duration_sec=4.0,
                total_measures=2,
            ),
            lead_source_stem="vocals",
            bass_source_stem="bass",
            selected_lead_melody=[
                Note(pitch="C4", start_time=0.1, end_time=0.9, confidence=0.92),
                Note(pitch="D4", start_time=2.1, end_time=2.8, confidence=0.9),
            ],
            selected_bassline=[
                Note(pitch="C2", start_time=0.0, end_time=1.8, confidence=0.86),
                Note(pitch="D2", start_time=2.0, end_time=3.8, confidence=0.84),
            ],
            chord_timeline=[
                ChordSpan(
                    start_time=0.0,
                    end_time=2.0,
                    measure_num=1,
                    symbol="C",
                    root="C",
                    quality="",
                    bass=None,
                    confidence=0.76,
                ),
                ChordSpan(
                    start_time=2.0,
                    end_time=4.0,
                    measure_num=2,
                    symbol="Dm",
                    root="D",
                    quality="m",
                    bass=None,
                    confidence=0.72,
                ),
            ],
            form_sections=[
                FormSection(
                    id="section_a",
                    label="section_a",
                    start_time=0.0,
                    end_time=4.0,
                    measure_start=1,
                    measure_end=2,
                    confidence=0.4,
                )
            ],
            confidence=0.63,
        )

        score_ir = builder.build(
            pitch_result,
            lyrics_segments=[{"text": "la la", "start": 0.0, "end": 3.8}],
            analysis_ir=analysis_ir,
        )

        self.assertEqual(len(score_ir.notes), 2)
        self.assertEqual(score_ir.notes[0].source, "analysis_ir_lead")
        self.assertEqual(score_ir.notes[0].measure_num, 1)
        self.assertEqual(score_ir.notes[1].measure_num, 2)
        self.assertEqual(score_ir.measures[0].note_ids, [score_ir.notes[0].id])
        self.assertEqual(score_ir.measures[1].note_ids, [score_ir.notes[1].id])
        self.assertEqual(len(score_ir.bassline_notes), 2)
        self.assertEqual(score_ir.bassline_notes[0].source, "analysis_ir_bass")
        self.assertEqual(score_ir.bassline_notes[1].measure_num, 2)
        self.assertEqual([item.symbol for item in score_ir.chord_timeline], ["C", "Dm"])
        self.assertEqual(len(score_ir.form_sections), 1)
        self.assertEqual(score_ir.form_sections[0].measure_start, 1)
        self.assertEqual(score_ir.meta.analysis_info["analysis_ir_version"], "analysis_ir_v1")
        self.assertEqual(score_ir.meta.analysis_info["analysis_ir_chord_count"], 2)
        self.assertEqual(score_ir.meta.analysis_info["analysis_ir_form_section_count"], 1)

        score_data = ScoreIRSerializer.to_score_data(score_ir)
        self.assertEqual(len(score_data["chord_timeline"]), 2)
        self.assertEqual(score_data["chord_timeline"][1]["symbol"], "Dm")
        self.assertEqual(len(score_data["form_sections"]), 1)
        self.assertEqual(score_data["form_sections"][0]["label"], "section_a")


if __name__ == "__main__":
    unittest.main()
