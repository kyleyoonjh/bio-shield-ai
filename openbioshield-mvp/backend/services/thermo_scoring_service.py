"""
Thermodynamic scoring using primer3-py.
Evaluates Tm, GC%, self-dimer, and hairpin for each primer pair.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

try:
    import primer3 as _primer3
    _PRIMER3_AVAILABLE = True
except ImportError:
    _primer3 = None  # type: ignore
    _PRIMER3_AVAILABLE = False
    logger.warning("[thermo] primer3-py not installed — using formula fallbacks")

OPTIMAL_TM   = 60.0
TM_TOLERANCE = 3.0   # ±3 °C from optimal
MAX_TM_DELTA = 2.0   # max Tm difference between Fwd and Rev
MAX_GC       = 65.0
MIN_GC       = 40.0
MAX_DIMER_DG = -6.0  # kcal/mol
MAX_HAIR_DG  = -2.0  # kcal/mol


class ThermoScoringService:
    def evaluate_kinetics(self, forward: str, reverse: str) -> dict:
        """
        Returns:
            thermo_score (0–100), tm_fwd, tm_rev, gc_fwd, gc_rev,
            self_dimer_dg_fwd, hairpin_dg_fwd, penalty_reason
        """
        fwd = forward.upper()
        rev = reverse.upper()

        tm_fwd = self._calc_tm(fwd)
        tm_rev = self._calc_tm(rev)
        gc_fwd = self._gc(fwd)
        gc_rev = self._gc(rev)

        dimer_dg_fwd  = self._self_dimer_dg(fwd)
        hairpin_dg_fwd = self._hairpin_dg(fwd)
        dimer_dg_rev  = self._self_dimer_dg(rev)

        penalties: list[str] = []
        score = 100.0

        # Tm deviation penalty
        tm_dev_fwd = abs(tm_fwd - OPTIMAL_TM)
        tm_dev_rev = abs(tm_rev - OPTIMAL_TM)
        if tm_dev_fwd > TM_TOLERANCE:
            penalty = min(30, (tm_dev_fwd - TM_TOLERANCE) * 8)
            score  -= penalty
            penalties.append(f"Fwd Tm deviation {tm_dev_fwd:.1f}°C")
        if tm_dev_rev > TM_TOLERANCE:
            penalty = min(30, (tm_dev_rev - TM_TOLERANCE) * 8)
            score  -= penalty
            penalties.append(f"Rev Tm deviation {tm_dev_rev:.1f}°C")

        # Tm balance
        tm_delta = abs(tm_fwd - tm_rev)
        if tm_delta > MAX_TM_DELTA:
            score -= (tm_delta - MAX_TM_DELTA) * 5
            penalties.append(f"Tm delta {tm_delta:.1f}°C")

        # GC penalty
        for label, gc in (("Fwd", gc_fwd), ("Rev", gc_rev)):
            if gc < MIN_GC or gc > MAX_GC:
                score -= 15
                penalties.append(f"{label} GC {gc:.1f}% out of range")

        # Self-dimer penalty
        if dimer_dg_fwd < MAX_DIMER_DG:
            score -= 10
            penalties.append(f"Fwd self-dimer ΔG {dimer_dg_fwd:.1f}")
        if dimer_dg_rev < MAX_DIMER_DG:
            score -= 10
            penalties.append(f"Rev self-dimer ΔG {dimer_dg_rev:.1f}")

        # Hairpin penalty
        if hairpin_dg_fwd < MAX_HAIR_DG:
            score -= 8
            penalties.append(f"Fwd hairpin ΔG {hairpin_dg_fwd:.1f}")

        score = max(0.0, min(100.0, score))

        return {
            "thermo_score":     round(score, 2),
            "tm_fwd":           round(tm_fwd, 2),
            "tm_rev":           round(tm_rev, 2),
            "gc_fwd":           round(gc_fwd, 2),
            "gc_rev":           round(gc_rev, 2),
            "self_dimer_dg":    round(dimer_dg_fwd, 2),
            "hairpin_dg":       round(hairpin_dg_fwd, 2),
            "penalty_reason":   "; ".join(penalties) if penalties else "Pass",
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_tm(seq: str) -> float:
        """Nearest-neighbor Tm with standard PCR conditions (SantaLucia 1998)."""
        if _PRIMER3_AVAILABLE:
            try:
                return _primer3.calc_tm(
                    seq,
                    mv_conc=50.0,    # 50 mM monovalent (K+/Na+)
                    dv_conc=1.5,     # 1.5 mM Mg2+
                    dntp_conc=0.2,   # 0.2 mM dNTPs
                    dna_conc=250.0,  # 250 nM primer
                    tm_method="santalucia",
                    salt_corrections_method="santalucia",
                )
            except Exception:
                pass
        # Salt-corrected formula fallback (Howley 1979)
        gc = (seq.count("G") + seq.count("C")) / len(seq)
        return 81.5 + 16.6 * math.log10(0.05) + 41.0 * gc - 675.0 / len(seq)

    @staticmethod
    def _gc(seq: str) -> float:
        return (seq.count("G") + seq.count("C")) / len(seq) * 100

    @staticmethod
    def _self_dimer_dg(seq: str) -> float:
        """Self-dimer ΔG in kcal/mol (negative = more stable = worse)."""
        if _PRIMER3_AVAILABLE:
            try:
                result = _primer3.calc_homodimer(
                    seq, mv_conc=50.0, dv_conc=1.5, dntp_conc=0.2, dna_conc=250.0
                )
                return result.dg / 1000.0  # cal/mol → kcal/mol
            except Exception:
                pass
        return 0.0

    @staticmethod
    def _hairpin_dg(seq: str) -> float:
        """Hairpin ΔG in kcal/mol."""
        if _PRIMER3_AVAILABLE:
            try:
                result = _primer3.calc_hairpin(
                    seq, mv_conc=50.0, dv_conc=1.5, dntp_conc=0.2, dna_conc=250.0
                )
                return result.dg / 1000.0  # cal/mol → kcal/mol
            except Exception:
                pass
        return 0.0
