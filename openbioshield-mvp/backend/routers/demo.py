"""
Demo mode router.
Serves pre-built mock data for all Phase 1/2 features so the app works
without external API keys (NCBI, OpenAI, Supabase).

Activated by: DEMO_MODE=true in backend/.env
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])

_DATA_DIR = pathlib.Path(__file__).parent.parent / "demo_data"

DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"


def _load(filename: str) -> Any:
    path = _DATA_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"Demo data file missing: {filename}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Mode check ────────────────────────────────────────────────────────────────

@router.get("/mode")
def get_demo_mode():
    return {"demo_mode": DEMO_MODE}


# ── COVID data (disease.sh proxy) ─────────────────────────────────────────────

@router.get("/covid-global")
def covid_global():
    return _load("covid_global.json")


@router.get("/covid-countries")
def covid_countries():
    return _load("covid_countries.json")


@router.get("/covid-historical")
def covid_historical():
    """Synthetic 180-day cumulative-case timeline for global data."""
    import math
    base_cases = 695000000
    base_deaths = 6980000

    days = []
    cases: dict[str, int] = {}
    deaths: dict[str, int] = {}
    recovered: dict[str, int] = {}

    for i in range(180, 0, -1):
        from datetime import date, timedelta
        d = date(2024, 6, 11) - timedelta(days=i)
        key = d.strftime("%-m/%-d/%y") if os.name != "nt" else f"{d.month}/{d.day}/{str(d.year)[2:]}"
        # gentle daily growth curve
        factor = 1 - math.exp(-0.01 * (180 - i))
        daily = int(12000 * (0.8 + 0.4 * factor))
        base_cases += daily
        daily_d = int(90 * (0.8 + 0.4 * factor))
        base_deaths += daily_d
        cases[key] = base_cases
        deaths[key] = base_deaths
        recovered[key] = int(base_cases * 0.959)

    return {"cases": cases, "deaths": deaths, "recovered": recovered}
