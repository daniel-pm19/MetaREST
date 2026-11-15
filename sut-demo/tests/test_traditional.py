"""Traditional fixed-input assertions; run against the SUT_BASE_URL variant.

No generated MRs, no comparisons between related executions, no access to FAULTS.
These tests may detect the same defects as metamorphic testing; that is a result,
not a reason to weaken the baseline.
"""

import os

import httpx
import pytest


@pytest.fixture
def client():
    base_url = os.getenv("SUT_BASE_URL")
    if not base_url:
        pytest.skip("Configura SUT_BASE_URL para ejecutar la suite tradicional")
    with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
        yield client


def search(client, **params):
    response = client.get("/search", params=params)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["total"], int) and body["total"] >= 0
    assert isinstance(body["results"], list)
    for item in body["results"]:
        assert set(item) == {"id", "name", "category", "price"}
        assert isinstance(item["id"], int)
        assert item["price"] > 0
    return body


def test_health_and_openapi(client):
    assert client.get("/health").status_code == 200
    assert "/search" in client.get("/openapi.json").json()["paths"]


def test_fixed_limit_and_first_page(client):
    body = search(client, q="jazz", limit=5, sort="id_asc", page=1)
    assert [item["id"] for item in body["results"]] == [1, 2, 3, 4, 5]
    assert body["total"] == 24


def test_fixed_second_page(client):
    body = search(client, q="jazz", limit=10, page=2, sort="id_asc")
    assert [item["id"] for item in body["results"]] == list(range(11, 21))


def test_category_and_query_case(client):
    body = search(client, q="JAZZ", category="vinyl", limit=100)
    assert body["total"] == 12
    assert len(body["results"]) == 12
    assert all(item["category"] == "vinyl" and "jazz" in item["name"].lower() for item in body["results"])


def test_sorted_catalog_and_total(client):
    body = search(client, q="guitar", sort="price_desc", limit=100)
    assert len(body["results"]) == body["total"] == 24
    prices = [item["price"] for item in body["results"]]
    assert prices == sorted(prices, reverse=True)


def test_unknown_query_and_missing_item(client):
    body = search(client, q="no-such-catalog-term", limit=100)
    assert body == {"total": 0, "results": []}
    assert client.get("/items/999999").status_code == 404


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"page": 0}, {"sort": "random"}, {"category": "unknown"}]
)
def test_parameter_boundaries(client, params):
    assert client.get("/search", params=params).status_code == 422
