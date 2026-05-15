import unittest

from app.modules.analysis_ir.types import AnalysisIR, AnalysisIRMeta, ChordSpan, FormSection
from app.modules.pitch.types import MetaInfo, Note, NoteCandidateSet, NoteType, PitchAnalysisResult, QuantizedNote, SemanticAudioResult
from app.modules.score_ir import ScoreIRBuilder, ScoreIRSerializer


def _semantic_audio_with_quantized_payload(notes: list[dict]) -> SemanticAudioResult:
    payload_notes = []
    for note in notes:
        item = dict(note)
        if "id" not in item and item.get("quantized_note_id") is not None:
            item["id"] = item["quantized_note_id"]
        payload_notes.append(item)
    return SemanticAudioResult(
        melody_candidates=NoteCandidateSet(
            role="melody_candidates",
            analysis_info={
                "quantized_notes": {
                    "version": "test_quantized_notes_v1",
                    "schema_version": "quantized_note_set_v2",
                    "notes": payload_notes,
                    "summary": {"note_count": len(payload_notes)},
                }
            },
        )
    )


class TestScoreIRBuilder(unittest.TestCase):
    def test_build_hard_fails_authoritative_empty_lead_selection(self):
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
            analysis_info={
                "lead_selection_authoritative": True,
                "arrangement_decision": {
                    "policy": "deterministic_melody_source_arbitration",
                    "lead_note_count": 0,
                },
            },
            measures=[
                {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "is_anacrusis": False, "notes": []},
                {"measure_num": 2, "start_time": 2.0, "end_time": 4.0, "is_anacrusis": False, "notes": []},
            ],
            lead_notes=[],
            raw_notes=[
                Note(pitch="G5", start_time=0.2, end_time=0.8, confidence=0.95),
            ],
        )

        with self.assertRaisesRegex(RuntimeError, "score_ir_quantized_primary_contract_failed:missing_quantized_note_set_v2"):
            builder.build(pitch_result)

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

    def test_serializer_outputs_instrumental_melody_notes_without_polluting_measures(self):
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
            measures=[
                {
                    "measure_num": 1,
                    "start_time": 0.0,
                    "end_time": 2.0,
                    "is_anacrusis": False,
                    "notes": [
                        {
                            "id": "qn_missing_lineage",
                            "quantized_note_id": "qn_missing_lineage",
                            "pitch": "C4",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "beat_position": 1.0,
                            "confidence": 0.9,
                        }
                    ],
                },
                {"measure_num": 2, "start_time": 2.0, "end_time": 4.0, "is_anacrusis": False, "notes": []},
            ],
            instrumental_melody_notes=[
                QuantizedNote(
                    pitch="G5",
                    start_time=2.1,
                    end_time=2.6,
                    confidence=0.88,
                    duration_beats=1.0,
                    note_type=NoteType.QUARTER,
                    measure_num=2,
                    beat_position=1.2,
                    source="instrumental_hook",
                )
            ],
        )

        score_ir = builder.build(pitch_result)
        score_data = ScoreIRSerializer.to_score_data(score_ir)

        self.assertEqual(len(score_data["measures"][0]["notes"]), 1)
        self.assertEqual(score_data["measures"][1]["notes"], [])
        self.assertEqual(len(score_data["instrumental_melody_notes"]), 1)
        self.assertEqual(score_data["instrumental_melody_notes"][0]["pitch"], "G5")
        self.assertEqual(score_data["instrumental_melody_notes"][0]["measure_num"], 2)
        self.assertEqual(score_data["instrumental_melody_notes"][0]["source"], "instrumental_hook")

    def test_production_lineage_hard_fails_missing_source_candidate_id(self):
        builder = ScoreIRBuilder()
        pitch_result = PitchAnalysisResult(
            version="1.4",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                duration_sec=1.0,
                time_signature="4/4",
            ),
            measures=[
                {
                    "measure_num": 1,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "is_anacrusis": False,
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
            analysis_info={"lead_note_source": "quantized_notes"},
            semantic_audio=_semantic_audio_with_quantized_payload([
                {
                    "id": "qn_missing_lineage",
                    "pitch": "C4",
                    "start_time": 0.0,
                    "end_time": 0.5,
                    "duration_beats": 1.0,
                    "note_type": "quarter",
                    "beat_position": 1.0,
                    "confidence": 0.9,
                }
            ]),
        )

        with self.assertRaisesRegex(RuntimeError, "score_ir_lineage_contract_failed"):
            builder.build(pitch_result)

    def test_build_uses_quantized_primary_with_full_lineage(self):
        builder = ScoreIRBuilder()
        pitch_result = PitchAnalysisResult(
            version="1.4",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                duration_sec=1.0,
                time_signature="4/4",
            ),
            measures=[
                {
                    "measure_num": 1,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "is_anacrusis": False,
                    "notes": [
                        {
                            "id": "qn_00001",
                            "quantized_note_id": "qn_00001",
                            "pitch": "C4",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "beat_position": 1.0,
                            "confidence": 0.9,
                            "source_candidate_id": "cand_1",
                            "source_candidate_ids": ["cand_1"],
                            "source_contour_ids": ["pc_1"],
                            "source_f0_frame_range": {
                                "start_frame_index": 0,
                                "end_frame_index": 2,
                                "frame_count": 3,
                            },
                        }
                    ],
                }
            ],
            analysis_info={"lead_note_source": "quantized_notes"},
            semantic_audio=_semantic_audio_with_quantized_payload([
                {
                    "id": "qn_00001",
                    "quantized_note_id": "qn_00001",
                    "pitch": "C4",
                    "start_time": 0.0,
                    "end_time": 0.5,
                    "duration_beats": 1.0,
                    "note_type": "quarter",
                    "beat_position": 1.0,
                    "confidence": 0.9,
                    "source_candidate_id": "cand_1",
                    "source_candidate_ids": ["cand_1"],
                    "source_contour_ids": ["pc_1"],
                    "source_f0_frame_range": {
                        "start_frame_index": 0,
                        "end_frame_index": 2,
                        "frame_count": 3,
                    },
                }
            ]),
        )

        score_ir = builder.build(pitch_result)

        self.assertEqual(len(score_ir.notes), 1)
        self.assertEqual(score_ir.notes[0].source, "quantized_notes")
        self.assertEqual(score_ir.notes[0].source_candidate_id, "cand_1")
        self.assertEqual(score_ir.notes[0].source_candidate_ids, ["cand_1"])
        self.assertEqual(score_ir.notes[0].source_contour_ids, ["pc_1"])
        self.assertEqual(score_ir.notes[0].source_f0_frame_range["frame_count"], 3)
        self.assertEqual(score_ir.notes[0].quantized_note_id, "qn_00001")


    def test_build_uses_quantized_payload_not_measure_note_body(self):
        builder = ScoreIRBuilder()
        pitch_result = PitchAnalysisResult(
            version="1.4",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.8,
                duration_sec=1.0,
                time_signature="4/4",
            ),
            measures=[
                {
                    "measure_num": 1,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "is_anacrusis": False,
                    "notes": [
                        {
                            "id": "qn_payload_authority",
                            "quantized_note_id": "qn_payload_authority",
                            "pitch": "F#2",
                            "start_time": 0.3,
                            "end_time": 0.4,
                            "duration_beats": 0.25,
                            "note_type": "sixteenth",
                            "beat_position": 2.0,
                            "confidence": 0.1,
                        }
                    ],
                }
            ],
            analysis_info={"lead_note_source": "quantized_notes"},
            semantic_audio=_semantic_audio_with_quantized_payload([
                {
                    "id": "qn_payload_authority",
                    "quantized_note_id": "qn_payload_authority",
                    "pitch": "C4",
                    "start_time": 0.0,
                    "end_time": 0.5,
                    "duration_beats": 1.0,
                    "note_type": "quarter",
                    "measure_num": 1,
                    "beat_position": 1.0,
                    "confidence": 0.9,
                    "source_candidate_id": "cand_payload",
                    "source_candidate_ids": ["cand_payload"],
                    "source_contour_ids": ["pc_payload"],
                    "source_f0_frame_range": {
                        "start_frame_index": 10,
                        "end_frame_index": 14,
                        "frame_count": 5,
                    },
                }
            ]),
        )

        score_ir = builder.build(pitch_result)

        self.assertEqual(len(score_ir.notes), 1)
        self.assertEqual(score_ir.notes[0].pitch, "C4")
        self.assertEqual(score_ir.notes[0].confidence, 0.9)
        self.assertEqual(score_ir.notes[0].source_candidate_id, "cand_payload")
        self.assertEqual(score_ir.notes[0].source_f0_frame_range["start_frame_index"], 10)
        self.assertEqual(score_ir.measures[0].note_ids, [score_ir.notes[0].id])



if __name__ == "__main__":
    unittest.main()
