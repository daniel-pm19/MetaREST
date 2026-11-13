"""Experiment tooling for the MetaREST paper (RQ1–RQ3 and coverage).

Run from ``experiments/`` with ``python -m mrexp <command>`` (see experiments/README.md).
The pipeline code lives in ``backend/app``; it is imported from there, never copied.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
