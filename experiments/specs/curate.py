"""Reproducible curation of the public APIs' official OpenAPI documents (see README.md).

    curl -sL -o /tmp/pokeapi.yml https://raw.githubusercontent.com/PokeAPI/pokeapi/master/openapi.yml
    curl -sL -o /tmp/crossref.json https://api.crossref.org/swagger-docs
    python experiments/specs/curate.py pokeapi /tmp/pokeapi.yml experiments/specs/pokeapi.yaml
    python experiments/specs/curate.py crossref /tmp/crossref.json experiments/specs/crossref.json

Only removes things (operations, parameters, unused components); it never edits
what the remaining operations declare, so the specs stay faithful to the vendor's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

POKEAPI_RESOURCES = ["pokemon", "pokemon-species", "type", "ability", "move", "generation", "berry"]
POKEAPI_PATHS = [p for r in POKEAPI_RESOURCES for p in (f"/api/v2/{r}/", f"/api/v2/{r}/{{id}}/")]
POKEAPI_PATHS.append("/api/v2/pokemon/{pokemon_id}/encounters")

# Parameter names dropped per API, with the reason recorded in README.md.
DROP_PARAMS = {
    "pokeapi": {"q"},  # declared, but pokeapi.co answers 403: "only available locally"
    "crossref": {"mailto"},  # identifies a person (polite pool); the executor never sends personal data
}


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            found.add(ref)
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def _lookup(doc: dict[str, Any], ref: str) -> Any:
    node: Any = doc
    for part in ref.removeprefix("#/").split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _prune_components(doc: dict[str, Any]) -> None:
    """Keep only the components reachable from the remaining paths."""
    reachable: set[str] = set()
    pending = _refs(doc["paths"])
    while pending:
        ref = pending.pop()
        if ref in reachable:
            continue
        reachable.add(ref)
        pending |= _refs(_lookup(doc, ref)) - reachable
    for section in ("components", "definitions"):
        if section not in doc:
            continue
        container = doc[section]
        groups = container.items() if section == "components" else [("", container)]
        for group_name, group in list(groups):
            prefix = f"#/components/{group_name}/" if section == "components" else "#/definitions/"
            for name in list(group):
                if prefix + name not in reachable:
                    del group[name]


def _drop_params(doc: dict[str, Any], names: set[str]) -> int:
    dropped = 0
    for item in doc["paths"].values():
        for owner in [item, *(op for op in item.values() if isinstance(op, dict))]:
            params = owner.get("parameters") if isinstance(owner, dict) else None
            if not isinstance(params, list):
                continue
            kept = []
            for p in params:
                resolved = _lookup(doc, p["$ref"]) if "$ref" in p else p
                if resolved.get("name") in names:
                    dropped += 1
                else:
                    kept.append(p)
            owner["parameters"] = kept
    return dropped


def curate(api: str, doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    if api == "pokeapi":
        before = len(doc["paths"])
        doc["paths"] = {p: doc["paths"][p] for p in POKEAPI_PATHS}
        notes.append(f"paths: {before} -> {len(doc['paths'])}")
    notes.append(f"parameters dropped ({', '.join(sorted(DROP_PARAMS[api]))}): {_drop_params(doc, DROP_PARAMS[api])}")
    _prune_components(doc)
    if api == "crossref":
        doc.setdefault("host", "api.crossref.org")
        doc.setdefault("schemes", ["https"])
        notes.append("host/schemes added (absent in the vendor document)")
    return doc, notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("api", choices=sorted(DROP_PARAMS))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()

    raw = args.source.read_bytes()
    doc, notes = curate(args.api, yaml.safe_load(raw))
    if args.target.suffix == ".json":
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    else:
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)
    args.target.write_text(text, encoding="utf-8")
    print(f"source sha256: {hashlib.sha256(raw).hexdigest()}")
    for note in notes:
        print(f"- {note}")
    print(f"written {args.target} ({len(text) / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
