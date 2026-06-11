"""
Variant coverage analysis.
Calculates what fraction of input sequences a primer pair can amplify,
accounting for mismatches within the primer binding regions.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_ALLOWED_MISMATCHES = 2  # primers with >2 mismatches against a target are considered non-amplifiable


class CoverageService:
    def calculate_coverage_batch(
        self,
        candidates: list[dict],
        fasta_path: str,
        max_mismatches: int = MAX_ALLOWED_MISMATCHES,
    ) -> list[dict]:
        """Load FASTA once, then compute coverage for all candidates in-place."""
        sequences = self._load_fasta(fasta_path)
        if not sequences:
            for cand in candidates:
                cand["coverage_score"] = 0.0
            return candidates
        cleaned = [{"id": r["id"], "seq": r["sequence"].replace("-", "")} for r in sequences]
        total = len(cleaned)
        for cand in candidates:
            fwd_upper = cand["forward"].upper()
            rev_rc    = self._reverse_complement(cand["reverse"].upper())
            covered   = sum(
                1 for r in cleaned
                if self._find_primer(fwd_upper, r["seq"], max_mismatches)
                and self._find_primer(rev_rc,   r["seq"], max_mismatches)
            )
            cand["coverage_score"] = round((covered / total) * 100.0, 2) if total else 0.0
        logger.debug("[coverage] batch done | candidates=%d sequences=%d", len(candidates), total)
        return candidates

    def calculate_coverage(
        self,
        forward: str,
        reverse: str,
        fasta_path: str,
        max_mismatches: int = MAX_ALLOWED_MISMATCHES,
    ) -> dict:
        """
        For each sequence in the FASTA, check whether both primers bind
        with ≤ max_mismatches.  Coverage = fraction of sequences covered.
        """
        sequences = self._load_fasta(fasta_path)
        if not sequences:
            return {"coverage_score": 0.0, "covered": 0, "total": 0}

        fwd_upper = forward.upper()
        rev_rc    = self._reverse_complement(reverse.upper())

        covered = 0
        for rec in sequences:
            seq = rec["sequence"].replace("-", "")
            fwd_ok = self._find_primer(fwd_upper, seq, max_mismatches)
            rev_ok = self._find_primer(rev_rc,    seq, max_mismatches)
            if fwd_ok and rev_ok:
                covered += 1

        total          = len(sequences)
        coverage_score = round((covered / total) * 100.0, 2) if total else 0.0

        logger.debug(
            "[coverage] fwd=%s… covered=%d/%d (%.1f%%)",
            forward[:10], covered, total, coverage_score,
        )
        return {
            "coverage_score": coverage_score,
            "covered":        covered,
            "total":          total,
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _load_fasta(path: str) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        current_id  = None
        current_seq: list[str] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if current_id:
                        records.append({"id": current_id, "sequence": "".join(current_seq)})
                    current_id  = line[1:].split()[0]
                    current_seq = []
                elif line:
                    current_seq.append(line.upper())
        if current_id:
            records.append({"id": current_id, "sequence": "".join(current_seq)})
        return records

    @staticmethod
    def _reverse_complement(seq: str) -> str:
        comp = {"A": "T", "T": "A", "G": "C", "C": "G", "N": "N"}
        return "".join(comp.get(b, "N") for b in reversed(seq))

    @staticmethod
    def _find_primer(primer: str, seq: str, max_mm: int) -> bool:
        """Sliding-window search: return True if primer hits seq with ≤ max_mm mismatches."""
        plen = len(primer)
        for i in range(len(seq) - plen + 1):
            window = seq[i : i + plen]
            mm = sum(1 for a, b in zip(primer, window) if a != b and a != "N" and b != "N")
            if mm <= max_mm:
                return True
        return False
