"""Scripted provider for tests and CI: never calls a real LLM."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.pipeline.llm.base import LLMRequest, LLMResponse, TokenUsage

Script = Any | LLMResponse | Exception | Callable[[LLMRequest], Any]


class FakeLLMProvider:
    """Returns scripted responses in order and records every request.

    Each script item can be:
    * a JSON-serializable value -> returned as ``data`` (stop_reason ``end_turn``)
    * an ``LLMResponse``         -> returned as is
    * an ``Exception``           -> raised
    * a callable(request)        -> its return value is handled as above
    The last item is reused when the script runs out.
    """

    name = "fake"

    def __init__(self, *script: Script, usage: TokenUsage | None = None):
        if not script:
            raise ValueError("FakeLLMProvider needs at least one scripted response")
        self._script = list(script)
        self._usage = usage or TokenUsage(input_tokens=100, output_tokens=50)
        self.requests: list[LLMRequest] = []

    async def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._script) - 1)
        item = self._script[index]
        if callable(item) and not isinstance(item, LLMResponse):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(
            data=item,
            raw_text=json.dumps(item, ensure_ascii=False),
            model=request.model,
            provider=self.name,
            stop_reason="end_turn",
            usage=self._usage,
        )
