"""Write a run of the platform (with the QA decisions applied) as the JSON the experiments read.

Same content as ``GET /candidates/export?run_id=...`` (``{settings, report, candidates}``), but read directly from
Mongo, so no login token is needed in the shell. With the Docker Compose stack, from the repository root:

    docker compose --env-file backend/.env -f infra/docker-compose.yml exec -T backend \\
      python -m scripts.export_run demo_run1 > experiments/raw/demo_run1_reviewed.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.models.platform import RunRecord
from app.services import candidates_for_run


async def export_run(run_id: str) -> dict[str, Any]:
    run = await RunRecord.get(run_id)
    if run is None:
        raise SystemExit(f"no existe el run {run_id!r}")
    return {
        "settings": run.settings.model_dump(mode="json"),
        "report": run.report.model_dump(mode="json"),
        "candidates": [c.model_dump(mode="json") for c in await candidates_for_run(run_id)],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    args = parser.parse_args()

    from app.config import Settings
    from app.db import initialize_database

    client = await initialize_database(Settings())
    try:
        payload = await export_run(args.run_id)
    finally:
        client.close()
    print(json.dumps(payload, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
