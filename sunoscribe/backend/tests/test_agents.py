from __future__ import annotations

import unittest

from app.modules.agents import (
    AgentRevisionContext,
    AgentScorePatchValidator,
    ArtifactReference,
    DiagnosisAgent,
    RvcPrepareAgent,
    RvcSpecValidator,
    ScorePatchAgent,
)


def _sample_score_ir() -> dict:
    return {
        "meta": {
            "time_signature": "4/4",
            "analysis_info": {"detector": "rmvpe"},
        },
        "notes": [
            {
                "id": "n1",
                "pitch": "C4",
                "pitch_midi": 60,
                "start_time": 0.0,
                "end_time": 0.5,
                "duration_sec": 0.5,
                "duration_beats": 1.0,
                "measure_num": 1,
                "beat_position": 1.0,
                "confidence": 0.92,
                "lyric": None,
            },
            {
                "id": "n2",
                "pitch": "D4",
                "pitch_midi": 62,
                "start_time": 0.5,
                "end_time": 1.0,
                "duration_sec": 0.5,
                "duration_beats": 1.0,
                "measure_num": 1,
                "beat_position": 2.0,
                "confidence": 0.58,
                "lyric": None,
                "uncertain": True,
                "reason_codes": ["large_quantize_error"],
                "source_candidate_id": "cand2",
                "quantized_note_id": "qn2",
            },
            {
                "id": "n3",
                "pitch": "E4",
                "pitch_midi": 64,
                "start_time": 2.0,
                "end_time": 2.5,
                "duration_sec": 0.5,
                "duration_beats": 1.0,
                "measure_num": 2,
                "beat_position": 1.0,
                "confidence": 0.48,
                "lyric": None,
                "reason_codes": ["octave_outlier"],
            },
        ],
        "measures": [
            {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "is_anacrusis": False, "note_ids": ["n1", "n2"]},
            {"measure_num": 2, "start_time": 2.0, "end_time": 4.0, "is_anacrusis": False, "note_ids": ["n3"]},
        ],
        "analysis_hints": {"downbeat_confidence": 0.2},
        "issue_spots": [
            {
                "type": "low_downbeat_confidence",
                "severity": "medium",
                "measure_num": None,
                "note_ids": [],
                "segment_ids": [],
                "message": "Low downbeat confidence.",
            }
        ],
        "warnings": ["test_warning"],
    }


def _sample_context() -> AgentRevisionContext:
    return AgentRevisionContext(
        project_id="project-001",
        revision_id="revision-001",
        score_ir=_sample_score_ir(),
        artifacts=[
            ArtifactReference(id="a1", artifact_type="vocals_stem"),
            ArtifactReference(id="a2", artifact_type="accompaniment_stem"),
            ArtifactReference(id="a3", artifact_type="corrected_f0_track"),
        ],
        f0_track={"vocal_activity": {"segments": [{"state": "vocal", "start_time": 0.0, "end_time": 4.0}]}},
        note_candidates={"role": "melody_candidates", "notes": []},
        rhythm_grid={"beats_per_bar": 4, "beat_times": [0.0, 0.5, 1.0, 1.5]},
        vocal_activity={"segments": [{"state": "vocal", "start_time": 0.0, "end_time": 4.0}]},
        warnings=["test_warning"],
    )


class TestDiagnosisAgent(unittest.TestCase):
    def test_run_reports_existing_issue_spots_and_actions(self) -> None:
        diagnosis = DiagnosisAgent().run(_sample_context())

        self.assertIn("3 notes", diagnosis.summary)
        self.assertTrue(any(issue.code == "low_downbeat_confidence" for issue in diagnosis.suspected_issues))
        self.assertTrue(any(action.action.startswith("treat measure boundaries") for action in diagnosis.recommended_actions))
        self.assertEqual([note.note_id for note in diagnosis.uncertain_notes], ["n2", "n3"])
        self.assertEqual(diagnosis.uncertain_notes[0].reason_codes, ["large_quantize_error", "uncertain"])
        self.assertEqual(diagnosis.uncertain_notes[0].suggested_patch_types, ["move_note_to_grid", "adjust_duration"])
        self.assertEqual(diagnosis.uncertain_notes[1].suggested_patch_types, ["shift_octave", "replace_pitch", "mark_uncertain"])


class TestScorePatchAgent(unittest.TestCase):
    def test_propose_shift_octave_from_instruction(self) -> None:
        proposal = ScorePatchAgent().propose(_sample_context(), "请将 n1 升八度")

        self.assertEqual(proposal.base_revision_id, "revision-001")
        self.assertEqual(proposal.operations[0].op, "shift_octave")
        self.assertEqual(proposal.operations[0].note_id, "n1")

    def test_propose_patch_can_target_first_uncertain_note(self) -> None:
        proposal = ScorePatchAgent().propose(_sample_context(), "replace uncertain note pitch 64")

        self.assertEqual(proposal.base_revision_id, "revision-001")
        self.assertEqual(proposal.operations[0].op, "replace_pitch")
        self.assertEqual(proposal.operations[0].note_id, "n2")
        self.assertEqual(proposal.operations[0].pitch_midi, 64)


class TestAgentScorePatchValidator(unittest.TestCase):
    def test_validate_and_apply_supports_shift_split_and_mark(self) -> None:
        context = _sample_context()
        proposal = {
            "base_revision_id": "revision-001",
            "confidence": 0.9,
            "operations": [
                {"op": "shift_octave", "note_id": "n1", "octaves": 1},
                {"op": "split_note", "note_id": "n2", "split_ratio": 0.5},
                {"op": "mark_uncertain", "note_id": "n3"},
            ],
        }

        result = AgentScorePatchValidator().validate_and_apply(context=context, proposal=proposal)
        note_by_id = {note["id"]: note for note in result.score_ir["notes"]}

        self.assertEqual(note_by_id["n1"]["pitch_midi"], 72)
        self.assertIn("n2__split1", note_by_id)
        self.assertTrue(note_by_id["n3"]["uncertain"])
        self.assertIn("uncertain", note_by_id["n3"]["reason_codes"])
        self.assertTrue(note_by_id["n3"]["agent_metadata"]["uncertain"])
        self.assertEqual(result.diff_summary["operation_count"], 3)
        self.assertIn("n3", result.diff_summary["changed_note_ids"])

    def test_move_note_to_grid_requires_rhythm_grid(self) -> None:
        context = _sample_context().model_copy(update={"rhythm_grid": None})
        validation = AgentScorePatchValidator().validate(
            context=context,
            proposal={
                "base_revision_id": "revision-001",
                "confidence": 0.8,
                "operations": [{"op": "move_note_to_grid", "note_id": "n1", "beat_position": 2.0}],
            },
        )

        self.assertFalse(validation["accepted"])


class TestRvcPrepareAgent(unittest.TestCase):
    def test_prepare_and_validate_rvc_spec(self) -> None:
        context = _sample_context()
        spec = RvcPrepareAgent().prepare(context, voice_model_id="voice-model-001", transpose_semitones=2)
        validation = RvcSpecValidator().validate(context=context, spec=spec)

        self.assertTrue(validation.accepted)
        self.assertEqual(spec.vocal_stem_artifact_id, "a1")
        self.assertEqual(spec.accompaniment_artifact_id, "a2")
        self.assertEqual(spec.corrected_f0_artifact_id, "a3")

    def test_voice_conversion_mode_does_not_require_corrected_f0_or_accompaniment(self) -> None:
        context = _sample_context().model_copy(
            update={
                "artifacts": [ArtifactReference(id="a1", artifact_type="vocals_stem")],
            }
        )
        spec = RvcPrepareAgent().prepare(
            context,
            voice_model_id="voice-model-001",
            transpose_semitones=2,
            mode="voice_conversion",
        )
        validation = RvcSpecValidator().validate(context=context, spec=spec)

        self.assertTrue(validation.accepted)
        self.assertEqual(spec.mode, "voice_conversion")
        self.assertEqual(spec.vocal_stem_artifact_id, "a1")
        self.assertIsNone(spec.corrected_f0_artifact_id)
        self.assertIn("voice_conversion_mode_not_score_guided", spec.warnings)


if __name__ == "__main__":
    unittest.main()
