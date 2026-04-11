from __future__ import annotations

import json
from typing import Any


class AlignmentLLMClient:
    def generate_json(self, payload: dict) -> str:
        raise NotImplementedError


class StubAlignmentLLMClient(AlignmentLLMClient):
    def __init__(self, response: str | dict, raise_error: bool = False) -> None:
        self.response = response
        self.raise_error = raise_error

    def generate_json(self, payload: dict) -> str:
        if self.raise_error:
            raise RuntimeError("stub llm error")

        if isinstance(self.response, dict):
            return json.dumps(self.response, ensure_ascii=False, sort_keys=True)

        return str(self.response)
