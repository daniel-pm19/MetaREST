"""SUT presets of the experiments: spec file + how hard the executor may hit the API (experiments/specs/README.md)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.pipeline.executor import SUTClient

SPECS = Path(__file__).resolve().parents[1] / "specs"


@dataclass(frozen=True)
class SUTPreset:
    spec: Path
    base_url: str
    max_concurrency: int = 4
    min_interval: float = 0.0
    timeout: float = 10.0

    def client(self) -> SUTClient:
        return SUTClient(
            self.base_url, max_concurrency=self.max_concurrency, min_interval=self.min_interval, timeout=self.timeout
        )


PRESETS = {
    "pokeapi": SUTPreset(SPECS / "pokeapi.yaml", "https://pokeapi.co"),
    "crossref": SUTPreset(SPECS / "crossref.json", "https://api.crossref.org", 1, 1.0, 30.0),
}
