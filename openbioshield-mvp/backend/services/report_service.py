"""
Automated assay design report generator.
Produces a structured JSON summary; HTML/PDF export can be added later.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)

_REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")


class ReportService:
    def __init__(self, report_dir: str = _REPORT_DIR):
        self.report_dir = report_dir
        os.makedirs(report_dir, exist_ok=True)

    def generate_summary(self, assay_id: int | str, ranked_primers: list[dict]) -> str:
        """
        Write a JSON report and return the file path.
        Top 5 candidates are included in full; the rest summarised.
        """
        top5    = ranked_primers[:5]
        summary = {
            "assay_id":      assay_id,
            "generated_at":  datetime.utcnow().isoformat() + "Z",
            "total_candidates": len(ranked_primers),
            "top_candidates": [
                {
                    "rank":           c.get("final_rank"),
                    "forward":        c.get("forward"),
                    "reverse":        c.get("reverse"),
                    "final_score":    round(c.get("final_score", 0.0), 4),
                    "coverage_score": c.get("coverage_score"),
                    "thermo_score":   c.get("thermo_score"),
                    "ai_score":       c.get("ai_score"),
                    "tm_fwd":         c.get("tm_fwd"),
                    "tm_rev":         c.get("tm_rev"),
                    "gc_fwd":         c.get("gc_fwd"),
                    "gc_rev":         c.get("gc_rev"),
                    "product_size":   c.get("product_size"),
                    "specificity":    c.get("specificity_score"),
                    "penalty_reason": c.get("penalty_reason", ""),
                }
                for c in top5
            ],
            "score_weights": {
                "coverage": 0.6,
                "thermo":   0.2,
                "ai":       0.2,
            },
        }

        fname = f"assay_{assay_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        path  = os.path.join(self.report_dir, fname)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info("[report] Written → %s", path)
        return path
