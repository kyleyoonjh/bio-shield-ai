"""
Advanced primer candidate generation.

Features:
  - primer3-py nearest-neighbor thermodynamics (Tm, hairpin, homodimer)
  - IUPAC mixed-base support: expands degenerate codes into all A/T/G/C variants
    and uses worst-case thermodynamics across all combinations
  - Target-gene-specific design: slice full genome by gene coordinates from
    ranking.yaml (rdrp_gene, n_gene, e_gene …) instead of entire conserved region
  - Falls back to rule-based design when primer3-py is unavailable
"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── primer3 availability ───────────────────────────────────────────────────────
try:
    import primer3 as _primer3
    _PRIMER3_AVAILABLE = True
except ImportError:
    _primer3 = None          # type: ignore
    _PRIMER3_AVAILABLE = False
    logger.warning("[candidate] primer3-py not installed — falling back to rule-based design")

# ── IUPAC table ───────────────────────────────────────────────────────────────
_IUPAC: dict[str, list[str]] = {
    "R": ["A", "G"], "Y": ["C", "T"], "S": ["G", "C"], "W": ["A", "T"],
    "K": ["G", "T"], "M": ["A", "C"], "B": ["C", "G", "T"], "D": ["A", "G", "T"],
    "H": ["A", "C", "T"], "V": ["A", "G", "C"], "N": ["A", "T", "G", "C"],
}

# ── config path ───────────────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "ranking.yaml")


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


# Default Primer3 global args (overridden by ranking.yaml primer3_config section)
_DEFAULT_P3: dict[str, Any] = {
    "PRIMER_OPT_SIZE":            20,
    "PRIMER_MIN_SIZE":            18,
    "PRIMER_MAX_SIZE":            24,   # 24 to capture 22-nt WHO-standard primers
    "PRIMER_OPT_TM":              62.0,
    "PRIMER_MIN_TM":              58.0,
    "PRIMER_MAX_TM":              65.0,
    "PRIMER_MIN_GC":              40.0,
    "PRIMER_MAX_GC":              65.0,
    "PRIMER_MAX_SELF_ANY_TH":     45.0,
    "PRIMER_MAX_SELF_END_TH":     35.0,
    "PRIMER_MAX_HAIRPIN_TH":      24.0,
    # Wider product range so probe has room between primer binding sites
    "PRIMER_PRODUCT_SIZE_RANGE":  [[80, 300]],
}

# Probe (internal oligo) settings added when assay_type == "qPCR"
_PROBE_P3: dict[str, Any] = {
    "PRIMER_PICK_INTERNAL_OLIGO":       1,
    "PRIMER_INTERNAL_OPT_SIZE":         22,
    "PRIMER_INTERNAL_MIN_SIZE":         18,
    "PRIMER_INTERNAL_MAX_SIZE":         28,
    # Probe Tm must be 8-10°C above primer Tm (primers ~62°C → probe ~70°C)
    "PRIMER_INTERNAL_OPT_TM":          70.0,
    "PRIMER_INTERNAL_MIN_TM":          65.0,
    "PRIMER_INTERNAL_MAX_TM":          75.0,
    # Wider GC range to reduce false-reject rate
    "PRIMER_INTERNAL_MIN_GC":          35.0,
    "PRIMER_INTERNAL_MAX_GC":          70.0,
    "PRIMER_INTERNAL_MAX_SELF_ANY_TH": 45.0,
    "PRIMER_INTERNAL_MAX_HAIRPIN_TH":  24.0,
    # Relax poly-X to 5 (default 4 is very strict for viral sequences)
    "PRIMER_INTERNAL_MAX_POLY_X":       5,
}


class CandidateAnalysisService:
    """
    Drop-in replacement for the original service.
    Keeps the existing ``generate_primers(conserved_regions, advanced_options)``
    signature used by the orchestrator, and adds:
      - ``generate_primers_for_target_gene()`` for gene-coordinate-based design
      - ``calculate_thermo_with_iupac()`` for IUPAC worst-case thermodynamics
    """

    def __init__(self, num_return: int = 10):
        self.num_return = num_return
        cfg = _load_config()
        self._target_coords: dict[str, dict] = cfg.get("target_coordinates", {})
        p3cfg = cfg.get("primer3_config", {})
        self._p3_global = {**_DEFAULT_P3}
        if p3cfg:
            _map = {
                "primer_opt_size":  "PRIMER_OPT_SIZE",
                "primer_min_size":  "PRIMER_MIN_SIZE",
                "primer_max_size":  "PRIMER_MAX_SIZE",
                "primer_opt_tm":    "PRIMER_OPT_TM",
                "primer_min_tm":    "PRIMER_MIN_TM",
                "primer_max_tm":    "PRIMER_MAX_TM",
                "primer_min_gc":    "PRIMER_MIN_GC",
                "primer_max_gc":    "PRIMER_MAX_GC",
                "product_size_min": None,   # handled below
                "product_size_max": None,
            }
            ps_min = p3cfg.get("product_size_min", 100)
            ps_max = p3cfg.get("product_size_max", 250)
            self._p3_global["PRIMER_PRODUCT_SIZE_RANGE"] = [[ps_min, ps_max]]
            for yaml_key, p3_key in _map.items():
                if p3_key and yaml_key in p3cfg:
                    self._p3_global[p3_key] = p3cfg[yaml_key]

    # ── Public: existing orchestrator interface ───────────────────────────────

    def generate_primers(
        self,
        conserved_regions: list[dict],
        advanced_options: dict[str, Any] | None = None,
        assay_type: str = "",
    ) -> list[dict]:
        """
        Run Primer3 on each conserved region and return a flat candidate list.

        Each candidate dict contains:
            forward, reverse, product_size, tm_fwd, tm_rev, gc_fwd, gc_rev,
            region_start, region_end, region_entropy, pair_penalty
        When assay_type == "qPCR", also adds: probe, tm_probe, gc_probe
        """
        all_candidates: list[dict] = []

        probe_mode = assay_type.upper() in ("QPCR", "Q-PCR", "RTPCR", "RT-PCR")
        p3_global = {**self._p3_global, "PRIMER_NUM_RETURN": self.num_return}
        if probe_mode:
            p3_global.update(_PROBE_P3)
        if advanced_options:
            p3_global.update(
                {k.upper(): v for k, v in advanced_options.items() if k.upper() in _DEFAULT_P3}
            )

        if not _PRIMER3_AVAILABLE:
            logger.warning("[candidate] primer3 unavailable — using rule-based fallback")
            return self._fallback_design(conserved_regions)

        for region in conserved_regions:
            seq = region.get("consensus_seq", "")
            if len(seq) < 40:
                continue
            cands = self._run_primer3(seq, region, p3_global, probe_mode=probe_mode)
            all_candidates.extend(cands)

        logger.info(
            "[candidate] %d primer pairs generated from %d regions (probe_mode=%s)",
            len(all_candidates), len(conserved_regions), probe_mode,
        )
        return all_candidates

    # ── Public: gene-coordinate-based design ─────────────────────────────────

    def generate_primers_for_target_gene(
        self,
        full_genome: str,
        target_start: int,
        target_end: int,
        gene_name: str = "",
        advanced_options: dict | None = None,
    ) -> list[dict]:
        """
        Slice ``full_genome[target_start:target_end]`` and run Primer3 on it.
        ``target_start`` / ``target_end`` can be read from ranking.yaml
        ``target_coordinates`` section.

        Returns candidates in the same format as ``generate_primers()``.
        """
        if not _PRIMER3_AVAILABLE:
            logger.warning("[candidate] primer3 unavailable — cannot run gene-specific design")
            return []

        target_seq = full_genome[target_start:target_end]
        logger.info(
            "[candidate] gene-specific design | gene=%s coords=%d-%d len=%d",
            gene_name, target_start, target_end, len(target_seq),
        )

        region_meta = {
            "start":         target_start,
            "end":           target_end,
            "mean_entropy":  0.0,
            "consensus_seq": target_seq,
        }

        p3_global = {**self._p3_global, "PRIMER_NUM_RETURN": self.num_return}
        if advanced_options:
            p3_global.update(
                {k.upper(): v for k, v in advanced_options.items() if k.upper() in _DEFAULT_P3}
            )

        return self._run_primer3(target_seq, region_meta, p3_global, genomic_offset=target_start)

    # ── Public: IUPAC worst-case thermodynamics ───────────────────────────────

    def calculate_thermo_with_iupac(
        self, forward: str, reverse: str
    ) -> dict[str, Any]:
        """
        Expand IUPAC degenerate bases into all A/T/G/C variants and compute
        worst-case (most penalising) thermodynamics across all combinations.

        Caps expansion at 256 combinations per primer to avoid exponential blowup.
        """
        fwd_variants = self._expand_iupac(forward)[:256]
        rev_variants = self._expand_iupac(reverse)[:256]

        worst_tm_diff   =  0.0
        min_fwd_tm      = 99.0
        max_hairpin_tm  = -99.0

        for f_seq in fwd_variants:
            for r_seq in rev_variants:
                if _PRIMER3_AVAILABLE:
                    try:
                        f_tm = _primer3.calc_tm(f_seq, mv_conc=50, dv_conc=1.5, dntp_conc=0.2, dna_conc=250)
                        r_tm = _primer3.calc_tm(r_seq, mv_conc=50, dv_conc=1.5, dntp_conc=0.2, dna_conc=250)
                        hp_f = _primer3.calc_hairpin(f_seq, mv_conc=50, dv_conc=1.5, dntp_conc=0.2, dna_conc=250).tm
                        hp_r = _primer3.calc_hairpin(r_seq, mv_conc=50, dv_conc=1.5, dntp_conc=0.2, dna_conc=250).tm
                    except Exception:
                        continue
                else:
                    f_tm = self._tm(f_seq)
                    r_tm = self._tm(r_seq)
                    hp_f = hp_r = 0.0

                min_fwd_tm     = min(min_fwd_tm, f_tm)
                max_hairpin_tm = max(max_hairpin_tm, hp_f, hp_r)
                worst_tm_diff  = max(worst_tm_diff, abs(f_tm - r_tm))

        thermo_score = 100.0
        if worst_tm_diff   > 2.0:  thermo_score -= 15.0   # Tm imbalance
        if max_hairpin_tm  > 45.0: thermo_score -= 20.0   # hairpin risk

        return {
            "thermo_score":    max(0.0, thermo_score),
            "estimated_tm":    round(min_fwd_tm, 1),
            "tm_difference":   round(worst_tm_diff, 1),
            "max_hairpin_tm":  round(max_hairpin_tm, 1),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _expand_iupac(seq: str) -> list[str]:
        """Expand IUPAC ambiguous bases into all concrete A/T/G/C sequences."""
        combos: list[str] = [""]
        for base in seq.upper():
            alts = _IUPAC.get(base, [base])
            combos = [prefix + alt for prefix in combos for alt in alts]
            if len(combos) > 65536:   # hard cap to prevent memory explosion
                logger.warning("[candidate] IUPAC expansion capped at 65536 variants")
                break
        return combos

    def _run_primer3(
        self,
        template: str,
        region: dict,
        p3_global: dict,
        genomic_offset: int = 0,
        probe_mode: bool = False,
    ) -> list[dict]:
        """Call primer3.design_primers and return normalised candidate dicts."""
        try:
            result = _primer3.design_primers(
                seq_args={
                    "SEQUENCE_ID":       f"region_{region.get('start', 0)}",
                    "SEQUENCE_TEMPLATE": template,
                },
                global_args=p3_global,
            )
        except Exception as exc:
            logger.warning("[candidate] Primer3 error at region %s: %s", region.get("start"), exc)
            return []

        n = result.get("PRIMER_PAIR_NUM_RETURNED", 0)
        if n == 0:
            logger.debug(
                "[candidate] Primer3 0 pairs | region=%s explain_fwd=%s explain_pair=%s",
                region.get("start"),
                result.get("PRIMER_LEFT_EXPLAIN", ""),
                result.get("PRIMER_PAIR_EXPLAIN", ""),
            )
        candidates = []
        for i in range(n):
            fwd = result.get(f"PRIMER_LEFT_{i}_SEQUENCE",  "")
            rev = result.get(f"PRIMER_RIGHT_{i}_SEQUENCE", "")
            if not fwd or not rev:
                continue

            # Absolute genomic position of the forward primer
            left_pos_tuple = result.get(f"PRIMER_LEFT_{i}", (0, 0))
            genomic_pos    = genomic_offset + left_pos_tuple[0]

            cand: dict[str, Any] = {
                "forward":        fwd,
                "reverse":        rev,
                "product_size":   result.get(f"PRIMER_PAIR_{i}_PRODUCT_SIZE", 0),
                "tm_fwd":         round(result.get(f"PRIMER_LEFT_{i}_TM",          0.0), 2),
                "tm_rev":         round(result.get(f"PRIMER_RIGHT_{i}_TM",         0.0), 2),
                "gc_fwd":         round(result.get(f"PRIMER_LEFT_{i}_GC_PERCENT",  0.0), 2),
                "gc_rev":         round(result.get(f"PRIMER_RIGHT_{i}_GC_PERCENT", 0.0), 2),
                "region_start":   region.get("start",        0),
                "region_end":     region.get("end",          0),
                "region_entropy": region.get("mean_entropy", 0.0),
                "pair_penalty":   round(result.get(f"PRIMER_PAIR_{i}_PENALTY", 0.0), 4),
                "genomic_pos":    genomic_pos,
            }

            if probe_mode:
                probe_seq = result.get(f"PRIMER_INTERNAL_{i}_SEQUENCE", "")
                if probe_seq:
                    probe_upper = probe_seq.upper()
                    # Rule 1: 5' G → fluorescence self-quenching
                    # Rule 2: homopolymer run (≥4) inhibits hybridisation / signal
                    probe_ok = (
                        probe_upper[0] != "G"
                        and "GGGGG" not in probe_upper
                        and "CCCCC" not in probe_upper
                    )
                    if not probe_ok:
                        logger.debug("[candidate] probe failed quality filter (pair %d): %s", i, probe_seq[:12])
                    else:
                        # Rule 3: probe centrality score (ideal = centre of amplicon)
                        internal_pos = result.get(f"PRIMER_INTERNAL_{i}", (0, 0))
                        left_pos     = result.get(f"PRIMER_LEFT_{i}",     (0, 0))
                        right_pos    = result.get(f"PRIMER_RIGHT_{i}",    (0, 0))
                        amp_start    = left_pos[0]
                        # right_pos[0] = 3'-end of right primer (0-based inclusive);
                        # +1 makes it an exclusive end consistent with product_size calculation.
                        amp_end      = right_pos[0] + 1
                        amp_len      = max(amp_end - amp_start, 1)
                        # internal_pos[0] = 5'-start of probe, internal_pos[1] = length
                        probe_center = (internal_pos[0] + internal_pos[1] / 2) - amp_start
                        amp_center   = amp_len / 2
                        offset_pct   = abs(probe_center - amp_center) / amp_len
                        # 100 at centre, 0 at > 40% offset from centre
                        probe_center_score = max(0.0, round(100.0 - offset_pct * 250.0, 1))

                        cand["probe"]              = probe_seq
                        cand["tm_probe"]           = round(result.get(f"PRIMER_INTERNAL_{i}_TM",        0.0), 2)
                        cand["gc_probe"]           = round(result.get(f"PRIMER_INTERNAL_{i}_GC_PERCENT", 0.0), 2)
                        cand["probe_center_score"] = probe_center_score
                # Pair is always included even if no valid probe found

            candidates.append(cand)
        return candidates

    # ── Rule-based fallback (no primer3) ─────────────────────────────────────

    @staticmethod
    def _rc(seq: str) -> str:
        comp = {"A": "T", "T": "A", "G": "C", "C": "G"}
        return "".join(comp.get(b.upper(), "N") for b in reversed(seq))

    @staticmethod
    def _tm(seq: str) -> float:
        s = seq.upper()
        return 4.0 * (s.count("G") + s.count("C")) + 2.0 * (s.count("A") + s.count("T"))

    @staticmethod
    def _gc(seq: str) -> float:
        s = seq.upper()
        return (s.count("G") + s.count("C")) / len(s) * 100 if seq else 0.0

    def _fallback_design(self, conserved_regions: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for region in conserved_regions:
            seq = region.get("consensus_seq", "")
            if len(seq) < 60:
                continue
            for fwd_len in (20, 22, 18):
                fwd = seq[:fwd_len]
                tm_f = self._tm(fwd)
                gc_f = self._gc(fwd)
                if not (57 <= tm_f <= 67 and 40 <= gc_f <= 65):
                    continue
                for rev_len in (20, 22, 18):
                    rev_rc = self._rc(seq[-rev_len:])
                    tm_r   = self._tm(rev_rc)
                    gc_r   = self._gc(rev_rc)
                    if not (57 <= tm_r <= 67 and 40 <= gc_r <= 65):
                        continue
                    product = len(seq) - fwd_len - rev_len
                    if product < 60:
                        continue
                    candidates.append({
                        "forward":        fwd,
                        "reverse":        rev_rc,
                        "product_size":   product,
                        "tm_fwd":         round(tm_f, 2),
                        "tm_rev":         round(tm_r, 2),
                        "gc_fwd":         round(gc_f, 2),
                        "gc_rev":         round(gc_r, 2),
                        "region_start":   region["start"],
                        "region_end":     region["end"],
                        "region_entropy": region["mean_entropy"],
                        "pair_penalty":   0.0,
                        "genomic_pos":    region["start"],
                    })
                    break
                if candidates and candidates[-1]["region_start"] == region["start"]:
                    break

        logger.info("[candidate] fallback: %d primer pairs from %d regions", len(candidates), len(conserved_regions))
        return candidates
