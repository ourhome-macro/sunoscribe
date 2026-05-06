from __future__ import annotations

import json
from typing import Any, Protocol

from app.utils.errors import ValidationAppError

from .types import AgentRevisionContext, AgentScorePatch


class ScorePatchLLMClient(Protocol):
    def propose_score_patch(self, *, context: AgentRevisionContext, instruction: str) -> AgentScorePatch: ...


class OpenAIScorePatchLLMClient:
    """OpenAI-backed ScorePatch proposer constrained to typed patch JSON."""

    def __init__(self, *, api_key: str, model: str) -> None:
        normalized_key = str(api_key or "").strip()
        normalized_model = str(model or "").strip()
        if not normalized_key:
            raise ValueError("api_key is required")
        if not normalized_model:
            raise ValueError("model is required")
        self.api_key = normalized_key
        self.model = normalized_model

    def propose_score_patch(self, *, context: AgentRevisionContext, instruction: str) -> AgentScorePatch:
        try:
            from openai import OpenAI
        except Exception as exc:
            raise ValidationAppError("openai package is required for LLM score patch proposals") from exc

        client = OpenAI(api_key=self.api_key)
        payload = self._build_payload(context=context, instruction=instruction)
        try:
            response = client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": self._system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                text={"format": {"type": "json_object"}},
            )
        except Exception as exc:
            raise ValidationAppError("OpenAI score patch proposal failed") from exc

        raw_text = str(getattr(response, "output_text", "") or "").strip()
        if not raw_text:
            raise ValidationAppError("OpenAI score patch proposal returned an empty response")
        try:
            proposal = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValidationAppError("OpenAI score patch proposal did not return valid JSON") from exc
        return AgentScorePatch.model_validate(proposal)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You propose small, auditable SunoScribe ScorePatch JSON only. "
            "Return exactly one JSON object matching AgentScorePatch. "
            "Never replace the full score. Never invent note IDs. "
            "Use only these ops: replace_pitch, shift_octave, merge_notes, split_note, "
            "delete_note, adjust_duration, move_note_to_grid, mark_uncertain. "
            "Keep operations minimal and let the server validator reject invalid patches."
        )

    @staticmethod
    def _build_payload(*, context: AgentRevisionContext, instruction: str) -> dict[str, Any]:
        notes = context.score_ir.get("notes") if isinstance(context.score_ir, dict) else []
        measures = context.score_ir.get("measures") if isinstance(context.score_ir, dict) else []
        return {
            "instruction": str(instruction or ""),
            "base_revision_id": context.revision_id,
            "available_note_ids": [
                str(note.get("id"))
                for note in notes or []
                if isinstance(note, dict) and str(note.get("id") or "").strip()
            ],
            "score_ir_excerpt": {
                "meta": context.score_ir.get("meta") if isinstance(context.score_ir, dict) else {},
                "notes": list(notes or [])[:256],
                "measures": list(measures or [])[:64],
                "warnings": context.score_ir.get("warnings") if isinstance(context.score_ir, dict) else [],
            },
            "artifact_summary": [artifact.model_dump(mode="json") for artifact in context.artifacts],
            "context_warnings": list(context.warnings or []),
            "skill_names": context.skill_names(),
        }


def make_openai_score_patch_llm_client(*, api_key: str | None, model: str) -> ScorePatchLLMClient | None:
    if not str(api_key or "").strip():
        return None
    return OpenAIScorePatchLLMClient(api_key=str(api_key), model=model)
