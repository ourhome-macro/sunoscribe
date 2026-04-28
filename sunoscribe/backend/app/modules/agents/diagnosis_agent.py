from __future__ import annotations

from typing import Any

from .types import (
    AgentRevisionContext,
    DiagnosisAction,
    DiagnosisIssue,
    DiagnosisSectionFinding,
    TranscriptionDiagnosis,
)


class DiagnosisAgent:
    """Deterministic post-revision diagnostics over typed artifacts."""

    def run(self, context: AgentRevisionContext) -> TranscriptionDiagnosis:
        notes = self._notes(context)
        measures = self._measures(context)
        analysis_hints = self._analysis_hints(context)
        warnings = list(context.warnings or [])
        issues: list[DiagnosisIssue] = []
        section_findings: list[DiagnosisSectionFinding] = []

        issues.extend(self._issues_from_score_ir(context))
        issues.extend(self._issues_from_artifacts(context))
        issues.extend(self._issues_from_note_shape(notes))
        issues = self._dedupe_issues(issues)

        if measures:
            for measure in measures[: min(6, len(measures))]:
                measure_num = self._safe_int(measure.get("measure_num"), 0)
                note_ids = list(measure.get("note_ids") or [])
                local_tags = [
                    issue.code
                    for issue in issues
                    if measure_num > 0 and issue.evidence.get("measure_num") == measure_num
                ]
                summary = f"measure {measure_num}: {len(note_ids)} notes"
                section_findings.append(
                    DiagnosisSectionFinding(
                        label=f"measure_{measure_num}",
                        summary=summary,
                        measure_start=measure_num if measure_num > 0 else None,
                        measure_end=measure_num if measure_num > 0 else None,
                        issue_tags=local_tags,
                    )
                )

        if not section_findings:
            for section in context.score_ir.get("form_sections") or []:
                if not isinstance(section, dict):
                    continue
                section_findings.append(
                    DiagnosisSectionFinding(
                        label=str(section.get("label") or section.get("id") or "section"),
                        summary="section-level finding requires richer artifacts" if not notes else "section indexed",
                        measure_start=self._safe_optional_int(section.get("measure_start")),
                        measure_end=self._safe_optional_int(section.get("measure_end")),
                        issue_tags=[],
                    )
                )

        actions = self._recommended_actions(issues, analysis_hints, warnings)
        summary = self._build_summary(
            note_count=len(notes),
            measure_count=len(measures),
            issue_count=len(issues),
            warning_count=len(warnings),
        )
        return TranscriptionDiagnosis(
            summary=summary,
            section_findings=section_findings,
            suspected_issues=issues,
            recommended_actions=actions,
        )

    def _issues_from_score_ir(self, context: AgentRevisionContext) -> list[DiagnosisIssue]:
        issues: list[DiagnosisIssue] = []
        for issue in context.score_ir.get("issue_spots") or []:
            if not isinstance(issue, dict):
                continue
            issues.append(
                DiagnosisIssue(
                    code=str(issue.get("type") or "score_ir_issue"),
                    severity=self._severity(issue.get("severity")),
                    summary=str(issue.get("message") or issue.get("type") or "score issue"),
                    note_ids=[str(note_id) for note_id in issue.get("note_ids") or []],
                    evidence={"measure_num": issue.get("measure_num")},
                )
            )
        return issues

    def _issues_from_artifacts(self, context: AgentRevisionContext) -> list[DiagnosisIssue]:
        issues: list[DiagnosisIssue] = []
        if context.f0_track is None:
            issues.append(
                DiagnosisIssue(
                    code="missing_f0_track",
                    severity="medium",
                    summary="F0Track artifact is missing, octave and voicing diagnosis is limited.",
                )
            )
        if context.note_candidates is None:
            issues.append(
                DiagnosisIssue(
                    code="missing_note_candidates",
                    severity="medium",
                    summary="NoteCandidates artifact is missing, candidate-level diagnosis is limited.",
                )
            )
        if context.rhythm_grid is None:
            issues.append(
                DiagnosisIssue(
                    code="missing_rhythm_grid",
                    severity="medium",
                    summary="RhythmGrid artifact is missing, grid alignment diagnosis is limited.",
                )
            )
        if context.vocal_activity is None:
            issues.append(
                DiagnosisIssue(
                    code="missing_vocal_activity",
                    severity="medium",
                    summary="Vocal activity segmentation is missing, segment-boundary diagnosis is limited.",
                )
            )
        return issues

    def _issues_from_note_shape(self, notes: list[dict[str, Any]]) -> list[DiagnosisIssue]:
        if not notes:
            return [
                DiagnosisIssue(
                    code="empty_revision_notes",
                    severity="high",
                    summary="ScoreRevision contains no notes.",
                )
            ]

        issues: list[DiagnosisIssue] = []
        short_count = 0
        low_conf_count = 0
        leap_flags: list[str] = []
        last_pitch: int | None = None

        for note in notes:
            start_time = self._safe_float(note.get("start_time"), 0.0)
            end_time = self._safe_float(note.get("end_time"), start_time)
            duration_sec = max(0.0, end_time - start_time)
            confidence = self._safe_float(note.get("confidence"), 0.0)
            pitch_midi = self._safe_optional_int(note.get("pitch_midi"))
            note_id = str(note.get("id") or "")
            if duration_sec <= 0.09:
                short_count += 1
            if confidence < 0.55:
                low_conf_count += 1
            if last_pitch is not None and pitch_midi is not None and abs(pitch_midi - last_pitch) >= 12:
                leap_flags.append(note_id)
            if pitch_midi is not None:
                last_pitch = pitch_midi

        total = len(notes)
        if short_count >= max(3, int(total * 0.3)):
            issues.append(
                DiagnosisIssue(
                    code="dense_short_notes",
                    severity="medium",
                    summary="High proportion of very short notes may indicate unstable segmentation.",
                    evidence={"short_note_count": short_count, "total_notes": total},
                )
            )
        if low_conf_count >= max(3, int(total * 0.25)):
            issues.append(
                DiagnosisIssue(
                    code="unstable_f0",
                    severity="medium",
                    summary="Many notes have low confidence; F0 may be unstable in parts of the revision.",
                    evidence={"low_confidence_notes": low_conf_count, "total_notes": total},
                )
            )
        if leap_flags:
            issues.append(
                DiagnosisIssue(
                    code="possible_octave_error",
                    severity="medium",
                    summary="Large adjacent pitch jumps suggest possible octave errors or bad transitions.",
                    note_ids=leap_flags[:12],
                )
            )
        return issues

    def _recommended_actions(
        self,
        issues: list[DiagnosisIssue],
        analysis_hints: dict[str, Any],
        warnings: list[str],
    ) -> list[DiagnosisAction]:
        actions: list[DiagnosisAction] = []
        issue_codes = {issue.code for issue in issues}

        if "possible_octave_error" in issue_codes:
            actions.append(
                DiagnosisAction(
                    action="review octave jumps around flagged notes",
                    rationale="Large adjacent leaps are often better handled with a note-level patch than a full retranscription.",
                )
            )
        if "unstable_f0" in issue_codes:
            actions.append(
                DiagnosisAction(
                    action="inspect F0Track and vocal_activity around low-confidence regions",
                    rationale="Low-confidence note clusters usually need artifact-level diagnosis before editing the score.",
                )
            )
        if "missing_rhythm_grid" in issue_codes:
            actions.append(
                DiagnosisAction(
                    action="regenerate typed RhythmGrid artifact",
                    rationale="Grid edits such as move_note_to_grid should only be done against an explicit rhythm grid.",
                )
            )
        if self._safe_float(analysis_hints.get("downbeat_confidence"), 1.0) < 0.35:
            actions.append(
                DiagnosisAction(
                    action="treat measure boundaries as low-confidence",
                    rationale="Weak downbeat confidence makes duration and grid edits more error-prone.",
                )
            )
        if warnings:
            actions.append(
                DiagnosisAction(
                    action="review revision warnings before applying score patches",
                    rationale="Warnings already recorded on the revision often explain whether the issue is pitch, rhythm, or artifact availability.",
                )
            )
        return actions

    def _build_summary(self, *, note_count: int, measure_count: int, issue_count: int, warning_count: int) -> str:
        return (
            f"Diagnosis covers {note_count} notes across {measure_count} measures, "
            f"with {issue_count} suspected issues and {warning_count} warnings."
        )

    def _notes(self, context: AgentRevisionContext) -> list[dict[str, Any]]:
        notes = context.score_ir.get("notes")
        return [note for note in notes if isinstance(note, dict)] if isinstance(notes, list) else []

    def _measures(self, context: AgentRevisionContext) -> list[dict[str, Any]]:
        measures = context.score_ir.get("measures")
        return [measure for measure in measures if isinstance(measure, dict)] if isinstance(measures, list) else []

    def _analysis_hints(self, context: AgentRevisionContext) -> dict[str, Any]:
        hints = context.score_ir.get("analysis_hints")
        return dict(hints) if isinstance(hints, dict) else {}

    def _dedupe_issues(self, issues: list[DiagnosisIssue]) -> list[DiagnosisIssue]:
        deduped: list[DiagnosisIssue] = []
        seen: set[tuple[str, str]] = set()
        for issue in issues:
            key = (issue.code, issue.summary)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(issue)
        return deduped

    def _severity(self, raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if value in {"low", "medium", "high"}:
            return value
        return "medium"

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_optional_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
