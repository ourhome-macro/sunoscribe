from __future__ import annotations

from typing import List, Optional

from ..score_ir.types import ScoreIR
from .llm_client import AlignmentLLMClient
from .llm_parser import AlignmentLLMParser
from .llm_payload import AlignmentLLMPayloadBuilder
from .refine_policy import AlignmentRefinePolicy
from .refine_types import (
    AlignmentRefineDebugInfo,
    AlignmentRefineRequest,
    AlignmentRefineResponse,
)
from .types import AlignmentDraft
from .validator import AlignmentValidator


class AlignmentRefineService:
    def __init__(
        self,
        validator: AlignmentValidator,
        payload_builder: AlignmentLLMPayloadBuilder,
        parser: AlignmentLLMParser,
        llm_client: AlignmentLLMClient,
        policy: AlignmentRefinePolicy | None = None,
        include_debug: bool = False,
    ) -> None:
        self.validator = validator
        self.payload_builder = payload_builder
        self.parser = parser
        self.llm_client = llm_client
        self.policy = policy or AlignmentRefinePolicy()
        self.include_debug = include_debug

    def refine(self, request: AlignmentRefineRequest) -> AlignmentRefineResponse:
        score_ir = request.score_ir
        original_draft = request.draft

        warnings_before = self._safe_validate(score_ir, original_draft)
        warnings_for_llm = warnings_before if request.use_validator_warnings else []

        debug = AlignmentRefineDebugInfo() if self.include_debug else None
        flow_warnings: List[str] = []

        payload = self.payload_builder.build(score_ir, original_draft, warnings_for_llm)
        if debug is not None:
            debug.payload = payload

        try:
            raw_output = self.llm_client.generate_json(payload)
            if debug is not None:
                debug.llm_raw_output = raw_output
        except Exception as exc:
            if debug is not None:
                debug.exception_message = self._short_exception(exc)

            flow_warnings = self._warning_list(flow_warnings, "llm_error")
            return self._build_fallback_response(
                source="llm_error_fallback" if request.allow_fallback_to_original else "llm_error_original",
                score_ir=score_ir,
                original_draft=original_draft,
                warnings_before=warnings_before,
                flow_warnings=flow_warnings,
                accepted=False,
                debug=debug,
            )

        try:
            llm_result = self.parser.parse(raw_output)
            refined_draft = llm_result.to_alignment_draft(method="llm_refine")
        except ValueError as exc:
            if debug is not None:
                debug.parser_error = self._short_exception(exc)

            flow_warnings = self._warning_list(flow_warnings, "parse_error")
            return self._build_fallback_response(
                source="parse_error_fallback" if request.allow_fallback_to_original else "parse_error_original",
                score_ir=score_ir,
                original_draft=original_draft,
                warnings_before=warnings_before,
                flow_warnings=flow_warnings,
                accepted=False,
                debug=debug,
            )
        except Exception as exc:
            if debug is not None:
                debug.exception_message = self._short_exception(exc)

            flow_warnings = self._warning_list(flow_warnings, "refine_exception")
            return self._build_fallback_response(
                source="refine_exception_fallback" if request.allow_fallback_to_original else "refine_exception_original",
                score_ir=score_ir,
                original_draft=original_draft,
                warnings_before=warnings_before,
                flow_warnings=flow_warnings,
                accepted=False,
                debug=debug,
            )

        warnings_after = self._safe_validate(score_ir, refined_draft)

        accepted, reasons = self.policy.should_accept(
            score_ir=score_ir,
            original_draft=original_draft,
            refined_draft=refined_draft,
            warnings_before=warnings_before,
            warnings_after=warnings_after,
        )

        if debug is not None:
            debug.policy_reasons = reasons

        if accepted:
            flow_warnings = self._warning_list(flow_warnings, "llm_refine_accepted")
            return self._build_success_response(
                draft=refined_draft,
                source="llm_refined",
                flow_warnings=flow_warnings,
                warnings_before=warnings_before,
                warnings_after=warnings_after,
                debug=debug,
            )

        flow_warnings = self._warning_list(flow_warnings, "policy_rejected")
        if reasons:
            flow_warnings = self._warning_list(flow_warnings, *[f"policy:{r}" for r in reasons])

        if request.allow_fallback_to_original:
            return self._build_fallback_response(
                source="policy_rejected_fallback",
                score_ir=score_ir,
                original_draft=original_draft,
                warnings_before=warnings_before,
                flow_warnings=flow_warnings,
                accepted=False,
                debug=debug,
            )

        return self._build_success_response(
            draft=refined_draft,
            source="llm_refined_rejected",
            flow_warnings=flow_warnings,
            warnings_before=warnings_before,
            warnings_after=warnings_after,
            debug=debug,
            accepted=False,
        )

    def _build_success_response(
        self,
        draft: AlignmentDraft,
        source: str,
        flow_warnings: List[str],
        warnings_before: List[str],
        warnings_after: List[str],
        debug: AlignmentRefineDebugInfo | None,
        accepted: bool = True,
    ) -> AlignmentRefineResponse:
        return AlignmentRefineResponse(
            draft=draft,
            accepted=accepted,
            source=source,
            warnings=self._warning_list(*[flow_warnings]),
            validator_warnings_before=list(warnings_before),
            validator_warnings_after=list(warnings_after),
            debug=debug,
        )

    def _build_fallback_response(
        self,
        source: str,
        score_ir: ScoreIR,
        original_draft: AlignmentDraft,
        warnings_before: List[str],
        flow_warnings: List[str],
        accepted: bool,
        debug: AlignmentRefineDebugInfo | None,
    ) -> AlignmentRefineResponse:
        warnings_after = self._safe_validate(score_ir, original_draft)
        return AlignmentRefineResponse(
            draft=original_draft,
            accepted=accepted,
            source=source,
            warnings=self._warning_list(*[flow_warnings]),
            validator_warnings_before=list(warnings_before),
            validator_warnings_after=list(warnings_after),
            debug=debug,
        )

    def _safe_validate(self, score_ir: ScoreIR, draft: AlignmentDraft) -> List[str]:
        try:
            return list(self.validator.validate(score_ir, draft) or [])
        except Exception:
            return ["validator_exception"]

    def _warning_list(self, *items: object) -> List[str]:
        merged: List[str] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, list):
                for sub in item:
                    text = str(sub).strip()
                    if text and text not in merged:
                        merged.append(text)
                continue
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
        return merged

    def _short_exception(self, exc: Exception) -> str:
        message = str(exc).strip()
        if not message:
            return exc.__class__.__name__
        if len(message) > 240:
            return message[:240]
        return message
