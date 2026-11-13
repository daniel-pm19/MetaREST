"""Tiny catalog API with injectable faults, stdlib only (test double for sut-demo; NOT the real demo API).

In process: ``respond(path, params, faults)``.  As a server: ``FAULTS=a,b python demo_sut.py --port 8100``.
Shape: GET /search?q&limit&page&sort&category -> {"total", "results": [{"id","name","price","category"}]},
GET /items/{id}, GET /health.
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

GENRES = ["jazz", "rock", "blues", "pop"]
INSTRUMENTS = ["guitar", "piano", "sax"]
CATEGORIES = ["vinyl", "cd", "cassette"]
CATALOG = [
    {
        "id": i,
        "name": f"{GENRES[i % 4]} {INSTRUMENTS[i % 3]} #{i}",
        "price": round((i * 7) % 50 + 0.99, 2),
        "category": CATEGORIES[i % 3],
    }
    for i in range(1, 121)
]
FAULTS = {"page_off_by_one", "category_or", "desc_drops_last", "wrong_item_name"}


def search(params: dict[str, str], faults: set[str]) -> dict:
    terms = params.get("q", "").lower().split()
    items = [it for it in CATALOG if all(t in it["name"] for t in terms)]
    category = params.get("category")
    if category:
        if "category_or" in faults:
            items = [it for it in CATALOG if it["category"] == category or all(t in it["name"] for t in terms)]
        else:
            items = [it for it in items if it["category"] == category]
    sort = params.get("sort", "id_asc")
    if sort == "price_asc":
        items.sort(key=lambda it: (it["price"], it["id"]))
    elif sort == "price_desc":
        items.sort(key=lambda it: (-it["price"], it["id"]))
        if "desc_drops_last" in faults:
            items = items[:-1]
    limit, page = int(params.get("limit", 10)), int(params.get("page", 1))
    offset = page * limit if "page_off_by_one" in faults else (page - 1) * limit
    return {"total": len(items), "results": items[offset : offset + limit]}


def respond(path: str, params: dict[str, str], faults: set[str]) -> tuple[int, dict]:
    if path == "/health":
        return 200, {"status": "ok"}
    if path == "/search":
        return 200, search(params, faults)
    if path.startswith("/items/"):
        item = next((it for it in CATALOG if str(it["id"]) == path.rsplit("/", 1)[-1]), None)
        if item is None:
            return 404, {"detail": "not found"}
        if "wrong_item_name" in faults:
            item = {**item, "name": item["name"].upper()}
        return 200, item
    return 404, {"detail": "not found"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    port = parser.parse_args().port
    faults = {f for f in os.environ.get("FAULTS", "").split(",") if f}
    assert faults <= FAULTS, f"unknown faults: {faults - FAULTS}"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            url = urlsplit(self.path)
            status, body = respond(url.path, dict(parse_qsl(url.query)), faults)
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
