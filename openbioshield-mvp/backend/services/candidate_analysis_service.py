"""
Primer3-based primer candidate generation.
Uses primer3-py (already in requirements) to design primer pairs
from conserved regions detected by ConservationService.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import primer3 as _primer3
    _PRIMER3_AVAILABLE = True
except ImportError:
    _primer3 = None  # type: ignore
    _PRIMER3_AVAILABLE = False
    logger.warning("[candidate] primer3-py not installed — candidate generation will return empty list")

# Load Primer3 defaults from ranking.yaml if available
_DEFAULT_P3 = {
    "PRIMER_OPT_SIZE":       20,
    "PRIMER_MIN_SIZE":       18,
    "PRIMER_MAX_SIZE":       25,
    "PRIMER_OPT_TM":         60.0,
    "PRIMER_MIN_TM":         57.0,
    "PRIMER_MAX_TM":         63.0,
    "PRIMER_MIN_GC":         40.0,
    "PRIMER_MAX_GC":         65.0,
    "PRIMER_MAX_SELF_ANY_TH": 45.0,
    "PRIMER_MAX_SELF_END_TH": 35.0,
    "PRIMER_MAX_HAIRPIN_TH":  24.0,
    "PRIMER_PRODUCT_SIZE_RANGE": [[80, 250]],
}


class CandidateAnalysisService:
    def __init__(self, num_return: int = 10):
        self.num_return = num_return

    def generate_primers(
        self,
        conserved_regions: list[dict],
        advanced_options: dict[str, Any] | None = None,
    ) -> list[dict]:
        """
        Run Primer3 on each conserved region and return flattened candidate list.

        Each candidate dict:
            forward, reverse, product_size, tm_fwd, tm_rev,
            gc_fwd, gc_rev, region_start, region_entropy
        """
        all_candidates: list[dict] = []

        p3_global = {**_DEFAULT_P3}
        if advanced_options:
            p3_global.update({
                k.upper(): v for k, v in advanced_options.items()
                if k.upper() in _DEFAULT_P3
            })
        p3_global["PRIMER_NUM_RETURN"] = self.num_return

        if not _PRIMER3_AVAILABLE:
            logger.warning("[candidate] primer3 unavailable — returning empty candidate list")
            return []

        for region in conserved_regions:
            seq = region.get("consensus_seq", "")
            if len(seq) < 40:
                continue

            try:
                result = _primer3.design_primers(
                    seq_args={
                        "SEQUENCE_ID":       f"region_{region['start']}",
                        "SEQUENCE_TEMPLATE": seq,
                    },
                    global_args=p3_global,
                )
            except Exception as exc:
                logger.warning("[candidate] Primer3 error at region %d: %s", region["start"], exc)
                continue

            n = result.get("PRIMER_PAIR_NUM_RETURNED", 0)
            for i in range(n):
                fwd = result.get(f"PRIMER_LEFT_{i}_SEQUENCE",  "")
                rev = result.get(f"PRIMER_RIGHT_{i}_SEQUENCE", "")
                if not fwd or not rev:
                    continue

                all_candidates.append({
                    "forward":        fwd,
                    "reverse":        rev,
                    "product_size":   result.get(f"PRIMER_PAIR_{i}_PRODUCT_SIZE", 0),
                    "tm_fwd":         round(result.get(f"PRIMER_LEFT_{i}_TM",  0.0), 2),
                    "tm_rev":         round(result.get(f"PRIMER_RIGHT_{i}_TM", 0.0), 2),
                    "gc_fwd":         round(result.get(f"PRIMER_LEFT_{i}_GC_PERCENT",  0.0), 2),
                    "gc_rev":         round(result.get(f"PRIMER_RIGHT_{i}_GC_PERCENT", 0.0), 2),
                    "region_start":   region["start"],
                    "region_end":     region["end"],
                    "region_entropy": region["mean_entropy"],
                    "pair_penalty":   round(result.get(f"PRIMER_PAIR_{i}_PENALTY", 0.0), 4),
                })

        logger.info(
            "[candidate] %d primer pairs generated from %d regions",
            len(all_candidates), len(conserved_regions),
        )
        return all_candidates
