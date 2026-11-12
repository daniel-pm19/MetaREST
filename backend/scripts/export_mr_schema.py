"""Export the MR JSON Schemas to docs/schemas/.

Run from backend/:  python -m scripts.export_mr_schema
Re-run (and commit the output) every time app/models/mr.py changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models.mr import json_schemas

OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, schema in json_schemas().items():
        path = OUT_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
