"""Shared fixtures: an in-process fake SUT (catalog search API) with injectable faults.

It mimics the shape assumed in docs/MR_SCHEMA.md §8:
GET /search?q&limit&page&sort&category -> {"total": int, "results": [{"id", "name", "price", "category"}]}
GET /items/{id} -> item
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "mr_examples"

GENRES = ["jazz", "rock", "blues", "pop"]
INSTRUMENTS = ["guitar", "piano", "sax"]
CATEGORIES = ["vinyl", "cd", "cassette"]

CATALOG = [
    {
        "id": i,
        "name": f"{GENRES[i % 4]} {INSTRUMENTS[i % 3]} #{i}",
        "price": round((i * 7) % 50 + 0.99, 2),
        "category": CATEGORIES[i % 3 if i % 5 else 0],
    }
    for i in range(1, 201)
]

FAULTS = {
    "order_depends_on_limit",  # small pages are sorted by name instead of the requested order
    "page_off_by_one",  # offset = page * limit instead of (page - 1) * limit
    "category_or",  # category filter is OR-ed with q instead of AND-ed
    "desc_drops_last",  # sort=price_desc loses one element
}


def _matches(item: dict, terms: list[str]) -> bool:
    return all(t in item["name"] for t in terms)


def search(params: httpx.QueryParams, faults: set[str]) -> dict:
    terms = params.get("q", "").lower().split()
    items = [it for it in CATALOG if _matches(it, terms)]
    category = params.get("category")
    if category:
        if "category_or" in faults:
            items = [it for it in CATALOG if it["category"] == category or _matches(it, terms)]
        else:
            items = [it for it in items if it["category"] == category]
    sort = params.get("sort", "id_asc")
    if sort == "price_asc":
        items.sort(key=lambda it: (it["price"], it["id"]))
    elif sort == "price_desc":
        items.sort(key=lambda it: (-it["price"], it["id"]))
        if "desc_drops_last" in faults:
            items = items[:-1]
    limit = int(params.get("limit", 10))
    page = int(params.get("page", 1))
    total = len(items)
    if "order_depends_on_limit" in faults and limit < 15:
        items = sorted(items, key=lambda it: it["name"])
    offset = page * limit if "page_off_by_one" in faults else (page - 1) * limit
    return {"total": total, "results": items[offset : offset + limit]}


@pytest.fixture
def fake_sut() -> Callable[..., httpx.MockTransport]:
    """Factory: fake_sut(faults=set(), status=None, calls=list) -> MockTransport."""

    def make(
        faults: set[str] | None = None,
        *,
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
        calls: list[httpx.Request] | None = None,
    ) -> httpx.MockTransport:
        active = set(faults or ())
        assert active <= FAULTS, f"unknown faults: {active - FAULTS}"

        def default(request: httpx.Request) -> httpx.Response:
            if request.method not in ("GET", "HEAD"):
                return httpx.Response(405)
            path = request.url.path
            if path == "/search":
                return httpx.Response(200, json=search(request.url.params, active))
            if path.startswith("/items/"):
                item_id = path.rsplit("/", 1)[-1]
                item = next((it for it in CATALOG if str(it["id"]) == item_id), None)
                return httpx.Response(200, json=item) if item else httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(404, json={"detail": "not found"})

        def wrapped(request: httpx.Request) -> httpx.Response:
            if calls is not None:
                calls.append(request)
            return (handler or default)(request)

        return httpx.MockTransport(wrapped)

    return make


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / "specs" / name).read_text(encoding="utf-8"))
