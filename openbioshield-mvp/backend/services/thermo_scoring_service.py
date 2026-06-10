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


PROBE_OPT_TM  = 69.0
PROBE_TM_TOL  = 3.0   # ±3 °C from optimal probe Tm
MAX_CROSS_DG  = -6.0  # kcal/mol — cross-dimer rejection threshold


class ThermoScoringService:
    def evaluate_kinetics_with_probe(self, forward: str, reverse: str, probe: str) -> dict:
        """
        Full thermodynamic evaluation for a 3-component TaqMan set.

        Adds on top of evaluate_kinetics():
          - Probe Tm deviation from 69 °C
          - Probe self-hairpin and self-dimer
          - Fwd↔Probe and Rev↔Probe cross-dimer
        """
        result = self.evaluate_kinetics(forward, reverse)
        probe_upper = probe.upper()

        tm_probe        = self._calc_tm(probe_upper)
        probe_hair_dg   = self._hairpin_dg(probe_upper)
        probe_dimer_dg  = self._self_dimer_dg(probe_upper)
        fwd_probe_dg    = self._hetero_dimer_dg(forward.upper(), probe_upper)
        rev_probe_dg    = self._hetero_dimer_dg(reverse.upper(), probe_upper)

        penalties = [r for r in result["penalty_reason"].split("; ") if r and r != "Pass"]
        score = result["thermo_score"]

        tm_probe_dev = abs(tm_probe - PROBE_OPT_TM)
        if tm_probe_dev > PROBE_TM_TOL:
            penalty = min(20, (tm_probe_dev - PROBE_TM_TOL) * 6)
            score  -= penalty
            penalties.append(f"Probe Tm dev {tm_probe_dev:.1f}°C")

        if probe_hair_dg < MAX_HAIR_DG:
            score -= 10
            penalties.append(f"Probe hairpin ΔG {probe_hair_dg:.1f}")

        if probe_dimer_dg < MAX_DIMER_DG:
            score -= 10
            penalties.append(f"Probe self-dimer ΔG {probe_dimer_dg:.1f}")

        if fwd_probe_dg < MAX_CROSS_DG:
            score -= 12
            penalties.append(f"Fwd↔Probe ΔG {fwd_probe_dg:.1f}")

        if rev_probe_dg < MAX_CROSS_DG:
            score -= 12
            penalties.append(f"Rev↔Probe ΔG {rev_probe_dg:.1f}")

        score = max(0.0, min(100.0, score))
        result.update({
            "thermo_score":    round(score, 2),
            "tm_probe":        round(tm_probe, 2),
            "probe_hairpin_dg": round(probe_hair_dg, 2),
            "probe_dimer_dg":  round(probe_dimer_dg, 2),
            "fwd_probe_dg":    round(fwd_probe_dg, 2),
            "rev_probe_dg":    round(rev_probe_dg, 2),
            "penalty_reason":  "; ".join(penalties) if penalties else "Pass",
        })
        return result

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

    @staticmethod
    def _hetero_dimer_dg(seq1: str, seq2: str) -> float:
        """Heterodimer ΔG between two sequences in kcal/mol."""
        if _PRIMER3_AVAILABLE:
            try:
                result = _primer3.calc_heterodimer(
                    seq1, seq2, mv_conc=50.0, dv_conc=1.5, dntp_conc=0.2, dna_conc=250.0
                )
                return result.dg / 1000.0
            except Exception:
                pass
        return 0.0
