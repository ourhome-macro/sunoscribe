from __future__ import annotations

import importlib
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.modules.agents import RvcJobSpec, RvcVoiceConversionResult, TranscriptionDiagnosis
from app.modules.agents.types import (
    AgentScorePatch,
    DiagnosisAction,
    DiagnosisIssue,
    DiagnosisSectionFinding,
    UncertainNoteDiagnosis,
)
from app.schemas.audio_analysis import (
    AudioAnalysisExpression,
    AudioAnalysisLyrics,
    AudioAnalysisPitch,
    AudioAnalysisRange,
    AudioAnalysisReport,
    AudioAnalysisRhythm,
    AudioAnalysisSummary,
)
from app.utils.dependencies import get_current_user


REVISION_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "22222222-2222-4222-8222-222222222222"


class TestAgentWorkflowApi(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.db = MagicMock()
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_diagnose_endpoint_calls_service_and_returns_structured_diagnosis(self) -> None:
        service = MagicMock()
        service.diagnose_transcription.return_value = TranscriptionDiagnosis(
            summary="one octave jump looks suspicious",
            section_findings=[
                DiagnosisSectionFinding(
                    label="verse",
                    summary="unstable pitch center",
                    measure_start=1,
                    measure_end=4,
                    issue_tags=["octave_error"],
                )
            ],
            suspected_issues=[
                DiagnosisIssue(
                    code="octave_error",
                    severity="medium",
                    summary="note n1 may be one octave high",
                    note_ids=["n1"],
                    evidence={"cents": 1200},
                )
            ],
            uncertain_notes=[
                UncertainNoteDiagnosis(
                    note_id="n1",
                    pitch="C4",
                    measure=1,
                    beat=1.0,
                    onset_tick=0,
                    duration_tick=480,
                    confidence=0.42,
                    reason_codes=["low_confidence", "uncertain"],
                    suggested_patch_types=["mark_uncertain", "replace_pitch"],
                )
            ],
            recommended_actions=[
                DiagnosisAction(action="propose score patch", rationale="correct n1 before export")
            ],
        )

        with self._patched_workflow_service(service):
            response = self.client.post(f"/api/score-revisions/{REVISION_ID}/agent/diagnose")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["summary"], "one octave jump looks suspicious")
        self.assertEqual(payload["data"]["section_findings"][0]["label"], "verse")
        self.assertEqual(payload["data"]["suspected_issues"][0]["note_ids"], ["n1"])
        self.assertEqual(payload["data"]["uncertain_notes"][0]["note_id"], "n1")
        self.assertEqual(payload["data"]["uncertain_notes"][0]["reason_codes"], ["low_confidence", "uncertain"])
        service.diagnose_transcription.assert_called_once_with(
            self.db,
            user=self.user,
            revision_id=REVISION_ID,
        )

    def test_audio_analysis_post_endpoint_returns_report_and_public_artifact(self) -> None:
        service = MagicMock()
        artifact_id = uuid.uuid4()
        service.run_audio_analysis.return_value = (
            _sample_audio_analysis_report(),
            SimpleNamespace(id=artifact_id, status="available", created_at=None),
        )

        with self._patched_workflow_service(service):
            response = self.client.post(f"/api/score-revisions/{REVISION_ID}/audio-analysis")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["artifact_id"], str(artifact_id))
        self.assertEqual(payload["data"]["report"]["revision_id"], REVISION_ID)
        self.assertEqual(payload["data"]["report"]["summary"]["headline"], "主旋律音域约为 C4 到 G4。")
        service.run_audio_analysis.assert_called_once_with(
            self.db,
            user=self.user,
            revision_id=REVISION_ID,
        )

    def test_propose_patch_endpoint_validates_and_returns_score_patch(self) -> None:
        service = MagicMock()
        service.propose_score_patch.return_value = AgentScorePatch(
            base_revision_id=REVISION_ID,
            operations=[{"op": "replace_pitch", "note_id": "n1", "pitch_midi": 64}],
            rationale="n1 is closer to E4",
            confidence=0.88,
        )

        with self._patched_workflow_service(service):
            response = self.client.post(
                f"/api/score-revisions/{REVISION_ID}/agent/patch/propose",
                json={"instruction": "change n1 to E4"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["base_revision_id"], REVISION_ID)
        self.assertEqual(payload["data"]["operations"][0]["op"], "replace_pitch")
        self.assertEqual(payload["data"]["operations"][0]["pitch_midi"], 64)
        service.propose_score_patch.assert_called_once_with(
            self.db,
            user=self.user,
            revision_id=REVISION_ID,
            instruction="change n1 to E4",
        )

    def test_apply_patch_endpoint_returns_new_revision_metadata(self) -> None:
        service = MagicMock()
        new_revision_id = uuid.uuid4()
        service.apply_score_patch.return_value = SimpleNamespace(
            id=new_revision_id,
            project_id=uuid.UUID(PROJECT_ID),
            score_id=uuid.uuid4(),
            parent_revision_id=uuid.UUID(REVISION_ID),
            revision_number=3,
            revision_type="user",
            score_type="staff",
            key="C Major",
            artifacts=[],
            score_ir={
                "notes": [
                    {
                        "id": "n1",
                        "pitch": "E4",
                        "pitch_midi": 64,
                        "start_tick": 0,
                        "duration_tick": 480,
                        "measure_num": 1,
                        "beat_position": 1.0,
                        "confidence": 0.4,
                        "uncertain": True,
                        "reason_codes": ["low_confidence", "uncertain"],
                        "source_candidate_id": "cand1",
                        "quantized_note_id": "qn1",
                    }
                ]
            },
            created_at=None,
            updated_at=None,
            revision_metadata={
                "agent_workflow": {
                    "operation_count": 1,
                    "diff_summary": {"changed_note_ids": ["n1"], "operation_count": 1},
                }
            },
        )
        patch = {
            "base_revision_id": REVISION_ID,
            "operations": [{"op": "replace_pitch", "note_id": "n1", "pitch_midi": 64}],
            "rationale": "n1 is closer to E4",
            "confidence": 0.88,
        }

        with self._patched_workflow_service(service):
            response = self.client.post(f"/api/score-revisions/{REVISION_ID}/agent/patch/apply", json=patch)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["id"], str(new_revision_id))
        self.assertEqual(payload["data"]["parent_revision_id"], REVISION_ID)
        self.assertEqual(payload["data"]["revision_number"], 3)
        self.assertEqual(payload["data"]["revision_type"], "user")
        self.assertNotIn("revision_metadata", payload["data"])
        self.assertEqual(payload["data"]["client_summary"]["uncertain_note_count"], 1)
        self.assertEqual(payload["data"]["client_summary"]["low_confidence_note_count"], 1)
        self.assertEqual(payload["data"]["client_summary"]["score_notes"][0]["reason_codes"], ["low_confidence", "uncertain"])
        self.assertEqual(payload["data"]["diff_summary"]["changed_note_ids"], ["n1"])
        self.assertNotIn("storage_path", str(payload["data"]))
        called_proposal = service.apply_score_patch.call_args.kwargs["proposal"]
        self.assertEqual(called_proposal.base_revision_id, REVISION_ID)
        self.assertEqual(called_proposal.operations[0].op, "replace_pitch")

    def test_prepare_rvc_endpoint_returns_rvc_job_spec(self) -> None:
        service = MagicMock()
        service.prepare_rvc_job.return_value = RvcJobSpec(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            vocal_stem_artifact_id="33333333-3333-4333-8333-333333333333",
            accompaniment_artifact_id="44444444-4444-4444-8444-444444444444",
            corrected_f0_artifact_id="55555555-5555-4555-8555-555555555555",
            voice_model_id="voice-a",
            transpose_semitones=2,
            warnings=["missing_optional_mix_preview"],
        )

        with self._patched_workflow_service(service):
            response = self.client.post(
                f"/api/score-revisions/{REVISION_ID}/agent/rvc/prepare",
                json={"voice_model_id": "voice-a", "transpose_semitones": 2},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["voice_model_id"], "voice-a")
        self.assertEqual(payload["data"]["corrected_f0_artifact_id"], "55555555-5555-4555-8555-555555555555")
        self.assertEqual(payload["data"]["warnings"], ["missing_optional_mix_preview"])
        service.prepare_rvc_job.assert_called_once_with(
            self.db,
            user=self.user,
            revision_id=REVISION_ID,
            voice_model_id="voice-a",
            transpose_semitones=2,
            mode="score_guided",
        )

    def test_rvc_voice_conversion_endpoint_returns_rvc_vocal_artifact(self) -> None:
        service = MagicMock()
        artifact_id = "66666666-6666-4666-8666-666666666666"
        source_artifact_id = "33333333-3333-4333-8333-333333333333"
        artifact = SimpleNamespace(
            id=uuid.UUID(artifact_id),
            artifact_type="rvc_vocal",
            status="available",
            filename="rvc_vocal.wav",
            mime_type="audio/wav",
            file_size_bytes=321,
            checksum="abc",
            created_at=None,
            artifact_metadata={"mode": "voice_conversion"},
        )
        service.run_rvc_voice_conversion.return_value = (
            RvcVoiceConversionResult(
                project_id=PROJECT_ID,
                revision_id=REVISION_ID,
                rvc_vocal_artifact_id=artifact_id,
                source_vocal_stem_artifact_id=source_artifact_id,
                voice_model_id="voice-a",
                transpose_semitones=2,
                rvc_backend="external",
                warnings=["voice_conversion_mode_not_score_guided"],
            ),
            artifact,
        )

        with self._patched_workflow_service(service):
            response = self.client.post(
                f"/api/score-revisions/{REVISION_ID}/agent/rvc/voice-conversion",
                json={"voice_model_id": "voice-a", "transpose_semitones": 2},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["mode"], "voice_conversion")
        self.assertEqual(payload["data"]["rvc_vocal_artifact_id"], artifact_id)
        self.assertEqual(payload["data"]["artifact"]["artifact_type"], "rvc_vocal")
        service.run_rvc_voice_conversion.assert_called_once_with(
            self.db,
            user=self.user,
            revision_id=REVISION_ID,
            voice_model_id="voice-a",
            transpose_semitones=2,
        )

    def test_regenerate_exports_endpoint_returns_artifact_ids_and_types(self) -> None:
        service = MagicMock()
        service.regenerate_exports.return_value = {
            "midi": SimpleNamespace(
                id=uuid.uuid4(),
                artifact_type="midi",
                status="available",
                filename="score.mid",
                mime_type="audio/midi",
                file_size_bytes=128,
                checksum=None,
                created_at=None,
                storage_path="must-not-leak.mid",
            ),
            "musicxml": SimpleNamespace(
                id=uuid.uuid4(),
                artifact_type="musicxml",
                status="available",
                filename="score.musicxml",
                mime_type="application/vnd.recordare.musicxml+xml",
                file_size_bytes=256,
                checksum=None,
                created_at=None,
                storage_path="must-not-leak.musicxml",
            ),
        }

        with self._patched_workflow_service(service):
            response = self.client.post(f"/api/score-revisions/{REVISION_ID}/exports/regenerate")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        artifacts = payload["data"]["artifacts"]
        self.assertEqual(set(artifacts), {"midi", "musicxml"})
        self.assertEqual(artifacts["midi"]["artifact_type"], "midi")
        self.assertNotIn("storage_path", artifacts["midi"])
        service.regenerate_exports.assert_called_once_with(
            self.db,
            user=self.user,
            revision_id=REVISION_ID,
        )

    def test_agent_workflow_endpoints_require_login(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)

        response = self.client.post(f"/api/score-revisions/{REVISION_ID}/agent/diagnose")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["error"]["code"], "AUTHENTICATION_ERROR")

    def test_invalid_input_fails_with_existing_validation_style(self) -> None:
        response = self.client.post(
            f"/api/score-revisions/{REVISION_ID}/agent/rvc/prepare",
            json={"voice_model_id": "", "transpose_semitones": 99},
        )

        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("errors", payload["error"]["details"])

    def _patched_workflow_service(self, service: MagicMock):
        module = importlib.import_module("app.api.agents")
        return patch.object(module, "agent_workflow_service", service)


def _sample_audio_analysis_report() -> AudioAnalysisReport:
    return AudioAnalysisReport(
        version="audio_analysis_report_v1",
        project_id=PROJECT_ID,
        revision_id=REVISION_ID,
        status="ok",
        pitch=AudioAnalysisPitch(
            available=True,
            note_count=3,
            pitch_class_histogram={"C": 1, "E": 1, "G": 1},
            most_common_pitch_classes=["C", "E", "G"],
            melodic_direction="ascending_bias",
            evidence="score_ir_notes",
        ),
        expression=AudioAnalysisExpression(available=True, vibrato_segment_count=1, evidence="f0_track_frames"),
        range=AudioAnalysisRange(
            available=True,
            lowest_pitch="C4",
            highest_pitch="G4",
            lowest_pitch_midi=60,
            highest_pitch_midi=67,
            span_semitones=7,
            evidence="score_ir_notes",
        ),
        rhythm=AudioAnalysisRhythm(available=True, bpm=120.0, evidence="rhythm_grid"),
        lyrics=AudioAnalysisLyrics(available=False, status="missing_lyrics", evidence="lyrics_not_provided"),
        summary=AudioAnalysisSummary(
            headline="主旋律音域约为 C4 到 G4。",
            highlights=["主旋律音域约为 C4 到 G4。"],
            confidence=0.8,
            evidence_count=4,
        ),
        warnings=[],
    )


if __name__ == "__main__":
    unittest.main()
