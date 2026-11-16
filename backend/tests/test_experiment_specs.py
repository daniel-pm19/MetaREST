"""The curated public-API specs (experiments/specs/) must stay usable by the pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.context_extractor import extract_context

SPECS = Path(__file__).resolve().parents[2] / "experiments" / "specs"


@pytest.mark.parametrize(
    "file, title, server, operations",
    [
        ("pokeapi.yaml", "PokéAPI", "https://pokeapi.co", 15),
        ("crossref.json", "Crossref REST API", "https://api.crossref.org", 18),
    ],
)
def test_curated_spec_extracts(file, title, server, operations):
    ctx = extract_context((SPECS / file).read_text(encoding="utf-8"))
    assert (ctx.title, ctx.servers, len(ctx.operations)) == (title, [server], operations)
    assert all(op.response_fields for op in ctx.operations)  # selectors can be checked everywhere
    names = {p.name for op in ctx.operations for p in op.parameters}
    assert not names & {"q", "mailto"}  # removed on purpose, see experiments/specs/README.md
    assert len(ctx.to_prompt_text()) < 60_000  # keeps the generation prompt affordable
