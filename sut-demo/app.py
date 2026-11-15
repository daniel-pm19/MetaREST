"""Deterministic search API with opt-in, deliberately injected logical faults."""

import os
from enum import StrEnum
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


class Sort(StrEnum):
    ID_ASC = "id_asc"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"


class Category(StrEnum):
    VINYL = "vinyl"
    CD = "cd"


class Item(BaseModel):
    id: int = Field(description="Stable unique catalog identifier", examples=[1])
    name: str = Field(examples=["jazz collection 01"])
    category: Category
    price: float


class SearchResponse(BaseModel):
    total: int = Field(description="Number of matching items before pagination", examples=[24])
    results: list[Item] = Field(description="The requested page in deterministic order")


FAULTS = frozenset(
    {
        "filter_or",
        "wrong_total",
        "repeat_page",
        "drop_on_sort",
        "ignore_limit",
        "page_off_by_one",
        "ignore_category",
        "limit_dependent_order",
    }
)
# 24 results per term: enough to exercise the existing two-page example.
ITEMS = tuple(
    Item(
        id=group * 24 + index,
        name=f"{term} collection {index:02d}",
        category=Category.VINYL if index % 2 else Category.CD,
        price=float(((index * 7) % 29) + 10),
    )
    for group, term in enumerate(("jazz", "rock", "blues", "guitar"))
    for index in range(1, 25)
)


def create_app(faults: set[str] | frozenset[str] | None = None) -> FastAPI:
    """Create an isolated SUT; faults are fixed at startup, never set by requests."""
    enabled = (
        frozenset(part.strip() for part in os.getenv("FAULTS", "").split(",") if part.strip())
        if faults is None
        else frozenset(faults)
    )
    if unknown := enabled - FAULTS:
        raise ValueError(f"Unknown FAULTS: {', '.join(sorted(unknown))}")
    api = FastAPI(
        title="MetaREST demo SUT",
        version="0.1.0",
        description="Stable catalog. Filters use AND; total is measured before pagination; ordering is deterministic.",
    )

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/search", response_model=SearchResponse)
    async def search(
        q: Annotated[
            str,
            Query(
                description="Case-insensitive substring of the item name", openapi_examples={"jazz": {"value": "jazz"}}
            ),
        ] = "",
        category: Annotated[
            Category | None,
            Query(
                description="Exact category filter combined with q using AND",
                openapi_examples={"vinyl": {"value": "vinyl"}},
            ),
        ] = None,
        limit: Annotated[
            int,
            Query(
                ge=1,
                le=100,
                description="Maximum number of results per page",
                openapi_examples={"small": {"value": 10}},
            ),
        ] = 20,
        page: Annotated[
            int, Query(ge=1, description="Page number, starting at 1", openapi_examples={"first": {"value": 1}})
        ] = 1,
        sort: Annotated[
            Sort,
            Query(
                description="Sort mode; changing sort preserves all matches before pagination",
                openapi_examples={"stable": {"value": "id_asc"}},
            ),
        ] = Sort.ID_ASC,
    ) -> SearchResponse:
        def matches(item: Item) -> bool:
            term_match = q.casefold() in item.name.casefold()
            category_match = "ignore_category" in enabled or category is None or item.category == category
            if "filter_or" in enabled and q and category is not None:
                return term_match or category_match
            return term_match and category_match

        matches_list = [item for item in ITEMS if matches(item)]
        total = len(matches_list)
        if sort == Sort.ID_ASC:
            matches_list.sort(key=lambda item: item.id)
        else:
            matches_list.sort(key=lambda item: (item.price, item.id), reverse=sort == Sort.PRICE_DESC)
        if "limit_dependent_order" in enabled and sort == Sort.ID_ASC and limit < 15:
            matches_list.reverse()
        if "drop_on_sort" in enabled and sort == Sort.PRICE_DESC:
            matches_list = matches_list[:-1]
        if "wrong_total" in enabled and category is not None:
            total += len(ITEMS)
        size = 20 if "ignore_limit" in enabled else limit
        offset = 0 if "repeat_page" in enabled else (page - 1) * size
        if "page_off_by_one" in enabled:
            offset = page * size
        return SearchResponse(total=total, results=matches_list[offset : offset + size])

    @api.get("/items/{item_id}", response_model=Item)
    async def item(item_id: int) -> Item:
        for entry in ITEMS:
            if entry.id == item_id:
                return entry
        raise HTTPException(status_code=404, detail="Item not found")

    return api
