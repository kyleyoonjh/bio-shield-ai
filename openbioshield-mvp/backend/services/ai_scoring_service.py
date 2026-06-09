"""
AI-based primer efficiency scoring.

Uses sequence-derived features (GC content, Tm, positional composition,
dinucleotide bias, 3'-end stability) fed into a rule-based scoring model.

When a trained XGBoost model file is present at models/primer_xgb.json,
it is loaded and used instead of the heuristic rules.
"""

from __future__ import annotations

import logging
import math
import os
from collections import Counter

logger = logging.getLogger(__name__)

_XGB_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "primer_xgb.json")


class AIScoringService:
    def __init__(self):
        self._model = self._try_load_xgb()

    def predict_efficiency(self, candidate: dict) -> dict:
        """
        Returns:
            ai_score (0–100), feature_vector dict
        """
        fwd = candidate.get("forward", "").upper()
        rev = candidate.get("reverse", "").upper()

        feats = self._extract_features(fwd, rev, candidate)

        if self._model is not None:
            score = self._xgb_predict(feats)
        else:
            score = self._heuristic_score(feats)

        return {
            "ai_score":       round(score, 2),
            "feature_vector": feats,
        }

    # ── Feature extraction ─────────────────────────────────────────────────

    @staticmethod
    def _extract_features(fwd: str, rev: str, cand: dict) -> dict:
        def gc(s: str) -> float:
            return (s.count("G") + s.count("C")) / len(s) * 100 if s else 0.0

        def end3_stability(s: str, n: int = 5) -> float:
            tail = s[-n:] if len(s) >= n else s
            return (tail.count("G") + tail.count("C")) / len(tail) * 100

        def dinucleotide_entropy(s: str) -> float:
            if len(s) < 2:
                return 0.0
            pairs = [s[i:i+2] for i in range(len(s)-1)]
            counts = Counter(pairs)
            total  = sum(counts.values())
            return -sum((c/total) * math.log2(c/total) for c in counts.values() if c > 0)

        return {
            "gc_fwd":              gc(fwd),
            "gc_rev":              gc(rev),
            "tm_fwd":              cand.get("tm_fwd", 0.0),
            "tm_rev":              cand.get("tm_rev", 0.0),
            "tm_delta":            abs(cand.get("tm_fwd", 0.0) - cand.get("tm_rev", 0.0)),
            "len_fwd":             len(fwd),
            "len_rev":             len(rev),
            "end3_gc_fwd":         end3_stability(fwd),
            "end3_gc_rev":         end3_stability(rev),
            "dinuc_entropy_fwd":   round(dinucleotide_entropy(fwd), 4),
            "dinuc_entropy_rev":   round(dinucleotide_entropy(rev), 4),
            "product_size":        cand.get("product_size", 0),
            "region_entropy":      cand.get("region_entropy", 1.0),
            "pair_penalty":        cand.get("pair_penalty", 0.0),
            "thermo_score":        cand.get("thermo_score", 50.0),
            "coverage_score":      cand.get("coverage_score", 0.0),
        }

    @staticmethod
    def _heuristic_score(f: dict) -> float:
        """Rule-based AI score proxy using primer design best practices."""
        score = 60.0

        # GC 50% ± 10% is ideal
        for gc_key in ("gc_fwd", "gc_rev"):
            dev = abs(f[gc_key] - 50.0)
            score -= max(0, dev - 10) * 0.8

        # Tm balance (optimal delta < 1°C)
        score -= f["tm_delta"] * 3

        # 3'-end GC clamp (2–3 G/C in last 5 nt)
        for end_key in ("end3_gc_fwd", "end3_gc_rev"):
            pct = f[end_key]
            if pct < 40:
                score -= 8   # too weak
            elif pct > 80:
                score -= 5   # too strong GC clamp

        # High dinucleotide entropy = good sequence complexity
        avg_ent = (f["dinuc_entropy_fwd"] + f["dinuc_entropy_rev"]) / 2
        score += (avg_ent - 2.0) * 3  # 2 bits is typical; bonus for high complexity

        # Product size: 80–200 bp is ideal for qPCR
        ps = f["product_size"]
        if 80 <= ps <= 200:
            score += 5
        elif ps > 250:
            score -= 5

        # Conservation region entropy (low = better)
        score -= f["region_entropy"] * 10

        return max(0.0, min(100.0, score))

    # ── XGBoost model (optional) ───────────────────────────────────────────

    @staticmethod
    def _try_load_xgb():
        if not os.path.exists(_XGB_MODEL_PATH):
            return None
        try:
            import xgboost as xgb  # type: ignore
            model = xgb.Booster()
            model.load_model(_XGB_MODEL_PATH)
            logger.info("[ai_scoring] XGBoost model loaded from %s", _XGB_MODEL_PATH)
            return model
        except ImportError:
            logger.warning("[ai_scoring] xgboost not installed — using heuristic")
            return None
        except Exception as exc:
            logger.warning("[ai_scoring] XGB load failed: %s", exc)
            return None

    def _xgb_predict(self, feats: dict) -> float:
        try:
            import xgboost as xgb  # type: ignore
            import numpy as np

            keys  = sorted(feats.keys())
            arr   = np.array([[feats[k] for k in keys]], dtype=float)
            dmat  = xgb.DMatrix(arr)
            score = float(self._model.predict(dmat)[0]) * 100
            return max(0.0, min(100.0, score))
        except Exception as exc:
            logger.warning("[ai_scoring] XGB predict failed: %s — fallback to heuristic", exc)
            return self._heuristic_score(feats)
