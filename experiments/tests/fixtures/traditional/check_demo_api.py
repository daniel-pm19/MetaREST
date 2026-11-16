"""Example "traditional" suite run by the mutant runner (reads the SUT from SUT_BASE_URL). stdlib only."""

import json
import os
from urllib.request import urlopen

BASE = os.environ["SUT_BASE_URL"]


def get(path: str):
    with urlopen(BASE + path, timeout=5) as resp:
        return resp.status, json.load(resp)


def test_health():
    assert get("/health")[0] == 200


def test_item_detail():
    status, item = get("/items/1")
    assert status == 200 and item["name"] == "rock piano #1"


def test_limit_is_respected():
    assert len(get("/search?limit=5")[1]["results"]) <= 5
