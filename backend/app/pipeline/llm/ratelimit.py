"""Client-side rate limiting per model, plus waiting when the provider says how long to wait.

Free tiers (e.g. Gemini: 15 requests/min on Flash-Lite, 5 on larger models) reject bursts with 429; the
filters then fall back to rules-only scores (docs/LLM.md D11), which would silently weaken the filter.
Spacing requests avoids most 429s; a retriable error that carries ``retry_after`` (a per-minute quota) is
retried after that delay. Per-day quota errors are not retriable and surface immediately.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.pipeline.llm.base import LLMProvider, LLMProviderError, LLMRequest, LLMResponse


class RateLimitedProvider:
    def __init__(
        self,
        inner: LLMProvider,
        requests_per_minute: int,
        *,
        retries: int = 3,
        max_wait: float = 90.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.inner = inner
        self.name = inner.name
        self.interval = 60.0 / requests_per_minute
        self.retries = retries
        self.max_wait = max_wait
        self._clock = clock
        self._sleep = sleep
        self._next: dict[str, float] = {}  # model -> earliest time of its next request
        self._lock = asyncio.Lock()

    async def _acquire(self, model: str) -> None:
        async with self._lock:  # reserve a slot; the wait itself happens outside the lock
            now = self._clock()
            slot = max(now, self._next.get(model, now))
            self._next[model] = slot + self.interval
        if slot > now:
            await self._sleep(slot - now)

    async def complete_json(self, request: LLMRequest) -> LLMResponse:
        for attempt in range(self.retries + 1):
            await self._acquire(request.model)
            try:
                return await self.inner.complete_json(request)
            except LLMProviderError as exc:
                wait = exc.retry_after
                if not exc.retriable or wait is None or wait > self.max_wait or attempt == self.retries:
                    raise
                await self._sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover
