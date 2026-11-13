"""Safe HTTP client for the system under test (SUT).

* Only GET/HEAD — enforced here as well as in the MR contract (defense in depth).
* In-memory response cache keyed by (method, url): identical requests inside a
  run hit the SUT once (mitigates rate limits of public APIs).
* Bounded concurrency and small retry/backoff for 429/5xx and transport errors.
* Auth headers come from the caller (resolved from .env), never from the MR.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.models.mr import HttpExchange, HttpMethod, ParamValue, RequestSpec

RETRY_STATUS = {429, 502, 503, 504}
EXCERPT_LIMIT = 4000


class UnsafeRequestError(ValueError):
    pass


@dataclass(frozen=True)
class FetchResult:
    exchange: HttpExchange
    body: Any | None  # parsed JSON body, None for HEAD / non-JSON / errors

    @property
    def ok(self) -> bool:
        code = self.exchange.status_code
        return self.exchange.error is None and code is not None and 200 <= code < 300


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_url(base_url: str, request: RequestSpec) -> str:
    path = request.path
    for name, value in request.path_params.items():
        path = path.replace("{" + name + "}", quote(_fmt(value), safe=""))
    pairs: list[tuple[str, str]] = []
    for name, value in request.query_params.items():
        values: list[ParamValue] = value if isinstance(value, list) else [value]
        pairs.extend((name, _fmt(v)) for v in values)
    url = base_url.rstrip("/") + path
    return f"{url}?{urlencode(pairs)}" if pairs else url


def _excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class SUTClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        max_concurrency: int = 5,
        max_retries: int = 2,
        backoff: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url
        self.max_retries = max_retries
        self.backoff = backoff
        self._client = httpx.AsyncClient(
            headers=headers or {}, timeout=timeout, transport=transport, follow_redirects=True
        )
        self._sem = asyncio.Semaphore(max_concurrency)
        self._cache: dict[tuple[str, str], FetchResult] = {}
        self._inflight: dict[tuple[str, str], asyncio.Future[FetchResult]] = {}
        self.requests_sent = 0

    async def __aenter__(self) -> SUTClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, request: RequestSpec) -> FetchResult:
        if request.method not in (HttpMethod.GET, HttpMethod.HEAD):
            raise UnsafeRequestError(f"method {request.method} is not allowed against the SUT")
        url = build_url(self.base_url, request)
        key = (request.method.value, url)
        if key in self._cache:
            cached = self._cache[key]
            return FetchResult(cached.exchange.model_copy(update={"from_cache": True}), cached.body)
        if key in self._inflight:  # same request already running concurrently
            result = await asyncio.shield(self._inflight[key])
            return FetchResult(result.exchange.model_copy(update={"from_cache": True}), result.body)

        future: asyncio.Future[FetchResult] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            result = await self._send(request.method, url)
            if result.ok:  # never cache failures: a later retry may succeed
                self._cache[key] = result
            future.set_result(result)
            return result
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # mark as retrieved: waiters (if any) re-raise it themselves
            raise
        finally:
            self._inflight.pop(key, None)

    async def _send(self, method: HttpMethod, url: str) -> FetchResult:
        attempt = 0
        while True:
            start = time.perf_counter()
            try:
                async with self._sem:
                    self.requests_sent += 1
                    resp = await self._client.request(method.value, url)
            except httpx.HTTPError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * attempt)
                    continue
                return FetchResult(
                    HttpExchange(
                        method=method,
                        url=url,
                        elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
                        error=f"{type(exc).__name__}: {exc}"[:1000],
                    ),
                    None,
                )
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                attempt += 1
                await asyncio.sleep(self._retry_after(resp) or self.backoff * attempt)
                continue
            return self._to_result(method, url, resp, elapsed)

    def _retry_after(self, resp: httpx.Response) -> float | None:
        value = resp.headers.get("retry-after")
        try:
            return min(float(value), 5.0) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _to_result(method: HttpMethod, url: str, resp: httpx.Response, elapsed: float) -> FetchResult:
        body: Any | None = None
        error: str | None = None
        text = "" if method is HttpMethod.HEAD else resp.text
        if text:
            try:
                body = json.loads(text)
            except ValueError:
                content_type = resp.headers.get("content-type", "")
                if "json" in content_type:
                    error = "la respuesta declara JSON pero no se pudo parsear"
        return FetchResult(
            HttpExchange(
                method=method,
                url=url,
                status_code=resp.status_code,
                elapsed_ms=elapsed,
                response_excerpt=_excerpt(text) if text else None,
                error=error,
            ),
            body,
        )
