import unittest

from app.modules.analysis_ir import BaselineAnalysisInferencer
from app.modules.pitch.types import MetaInfo, Note, NoteCandidateSet, PitchAnalysisResult, RhythmGrid, SemanticAudioResult


class TestBaselineAnalysisInferencer(unittest.TestCase):
    def test_infer_builds_baseline_analysis_ir_from_semantic_audio(self):
        inferencer = BaselineAnalysisInferencer()
        semantic_audio = SemanticAudioResult(
            source_stems={
                "vocals": "vocals.wav",
                "other": "other.wav",
                "bass": "bass.wav",
                "drums": "drums.wav",
            },
            melody_candidates=NoteCandidateSet(
                role="melody_candidates",
                source_stem="vocals",
                selected_notes=[
                    Note(pitch="C4", start_time=0.1, end_time=0.8, confidence=0.92),
                    Note(pitch="D4", start_time=2.1, end_time=2.8, confidence=0.9),
                ],
            ),
            harmony_candidates=NoteCandidateSet(
                role="harmony_candidates",
                source_stem="other",
                notes=[
                    Note(pitch="C4", start_time=0.0, end_time=1.9, confidence=0.8),
                    Note(pitch="E4", start_time=0.0, end_time=1.9, confidence=0.8),
                    Note(pitch="G4", start_time=0.0, end_time=1.9, confidence=0.8),
                    Note(pitch="D4", start_time=2.0, end_time=3.9, confidence=0.78),
                    Note(pitch="F4", start_time=2.0, end_time=3.9, confidence=0.78),
                    Note(pitch="A4", start_time=2.0, end_time=3.9, confidence=0.78),
                ],
            ),
            bass_root_candidates=NoteCandidateSet(
                role="bass_root_candidates",
                source_stem="bass",
                notes=[
                    Note(pitch="C2", start_time=0.0, end_time=1.8, confidence=0.88),
                    Note(pitch="D2", start_time=2.0, end_time=3.8, confidence=0.86),
                ],
            ),
            rhythm_grid=RhythmGrid(
                source_stem="drums",
                input_audio_path="drums.wav",
                beat_times=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
                downbeat_times=[0.0, 2.0],
                bpm=120.0,
                bpm_confidence=0.9,
                beats_per_bar=4,
                beat_unit=4,
                beat_duration_sec=0.5,
                rhythm_type="stable",
                stability_score=0.95,
            ),
        )
        pitch_result = PitchAnalysisResult(
            version="1.4",
            meta=MetaInfo(
                bpm=120.0,
                bpm_confidence=0.9,
                key="C Major",
                key_confidence=0.82,
                duration_sec=4.0,
                time_signature="4/4",
                rhythm_type="stable",
                total_measures=2,
            ),
            measures=[
                {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "notes": []},
                {"measure_num": 2, "start_time": 2.0, "end_time": 4.0, "notes": []},
            ],
            lead_notes=list(semantic_audio.melody_candidates.selected_notes),
            raw_notes=list(semantic_audio.melody_candidates.selected_notes),
            semantic_audio=semantic_audio,
        )

        result = inferencer.infer(pitch_result, lyrics_segments=[{"text": "la la", "start": 0.0, "end": 3.5}])

        self.assertEqual(result.version, "analysis_ir_v1")
        self.assertEqual(result.lead_source_stem, "vocals")
        self.assertEqual(result.bass_source_stem, "bass")
        self.assertEqual(len(result.selected_lead_melody), 2)
        self.assertEqual(len(result.selected_bassline), 2)
        self.assertEqual([item.symbol for item in result.chord_timeline], ["C", "Dm"])
        self.assertEqual(len(result.form_sections), 1)
        self.assertEqual(result.form_sections[0].measure_start, 1)
        self.assertEqual(result.form_sections[0].measure_end, 2)
        self.assertGreater(result.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
