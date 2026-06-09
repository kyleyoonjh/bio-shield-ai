"""
Weighted ranking engine.
Reads weights from config/ranking.yaml and computes:

  Final Score = (w_coverage × Coverage) + (w_thermo × Thermo) + (w_ai × AI)

Specificity is a hard filter — any candidate with specificity_valid=False
is excluded before scoring.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "ranking.yaml"
)


class RankingService:
    def __init__(self, config_path: str = _CONFIG_PATH):
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)["ranking"]
            self.w_coverage = cfg["coverage_weight"]
            self.w_thermo   = cfg["thermo_weight"]
            self.w_ai       = cfg["ai_weight"]
        except Exception as exc:
            logger.warning("[ranking] Config load failed (%s) — using defaults", exc)
            self.w_coverage = 0.6
            self.w_thermo   = 0.2
            self.w_ai       = 0.2

    def calculate_final_rankings(self, candidates: list[dict]) -> list[dict]:
        """
        1. Drop candidates with specificity_valid=False (hard filter).
        2. Compute Final Score.
        3. Sort descending, assign final_rank starting at 1.
        """
        valid = [c for c in candidates if c.get("specificity_valid", True)]

        if len(valid) < len(candidates):
            logger.info(
                "[ranking] %d/%d candidates passed specificity hard filter",
                len(valid), len(candidates),
            )

        for c in valid:
            c["final_score"] = round(
                self.w_coverage * c.get("coverage_score", 0.0)
                + self.w_thermo  * c.get("thermo_score",   0.0)
                + self.w_ai      * c.get("ai_score",       0.0),
                4,
            )

        valid.sort(key=lambda x: x["final_score"], reverse=True)

        for idx, c in enumerate(valid):
            c["final_rank"] = idx + 1

        logger.info("[ranking] %d candidates ranked", len(valid))
        return valid
