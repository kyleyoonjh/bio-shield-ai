"""
Shannon Entropy-based conserved region detection.
Identifies low-entropy (conserved) windows across a multiple sequence alignment.
"""

from __future__ import annotations

import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)

# Entropy < threshold → conserved
ENTROPY_THRESHOLD = 0.5
MIN_REGION_LEN    = 18   # min nt for a valid primer region
WINDOW_SIZE       = 30   # scanning window


class ConservationService:
    def __init__(
        self,
        entropy_threshold: float = ENTROPY_THRESHOLD,
        min_region_len: int     = MIN_REGION_LEN,
        window_size: int        = WINDOW_SIZE,
    ):
        self.entropy_threshold = entropy_threshold
        self.min_region_len    = min_region_len
        self.window_size       = window_size

    # ── Public API ─────────────────────────────────────────────────────────

    def find_regions(self, aligned_fasta_path: str) -> list[dict]:
        """
        Scan the MSA for conserved windows.

        Returns list of:
            {start, end, mean_entropy, consensus_seq}
        sorted by mean_entropy ascending (most conserved first).
        """
        records = self._load_aligned_fasta(aligned_fasta_path)
        if not records:
            raise ValueError("No sequences found in aligned FASTA")

        aln_len = len(records[0]["sequence"])
        col_entropies = [
            self._column_entropy(records, col)
            for col in range(aln_len)
        ]

        conserved_regions = self._sliding_window_scan(col_entropies, records, aln_len)

        logger.info(
            "[conservation] %d conserved regions found in %d-nt alignment",
            len(conserved_regions), aln_len,
        )
        return conserved_regions

    # ── Internals ──────────────────────────────────────────────────────────

    def _load_aligned_fasta(self, path: str) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        current_id = None
        current_seq: list[str] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if current_id is not None:
                        records.append({"id": current_id, "sequence": "".join(current_seq)})
                    current_id = line[1:].split()[0]
                    current_seq = []
                elif line:
                    current_seq.append(line.upper())
        if current_id:
            records.append({"id": current_id, "sequence": "".join(current_seq)})
        return records

    @staticmethod
    def _column_entropy(records: list[dict], col: int) -> float:
        bases = [r["sequence"][col] for r in records if col < len(r["sequence"])]
        bases = [b for b in bases if b not in ("-", "N")]
        if not bases:
            return 2.0  # fully gapped → max entropy
        counts = Counter(bases)
        total  = len(bases)
        entropy = -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)
        return entropy

    def _sliding_window_scan(
        self,
        col_entropies: list[float],
        records: list[dict],
        aln_len: int,
    ) -> list[dict]:
        results: list[dict] = []
        i = 0
        while i <= aln_len - self.window_size:
            window_ent = col_entropies[i : i + self.window_size]
            mean_ent   = sum(window_ent) / self.window_size

            if mean_ent < self.entropy_threshold:
                # Extend the region as far as it stays conserved
                end = i + self.window_size
                while end < aln_len and col_entropies[end] < self.entropy_threshold:
                    end += 1

                region_len = end - i
                if region_len >= self.min_region_len:
                    consensus = self._consensus(records, i, end)
                    results.append({
                        "start":        i,
                        "end":          end,
                        "length":       region_len,
                        "mean_entropy": round(mean_ent, 4),
                        "consensus_seq": consensus,
                    })
                i = end  # skip scanned region
            else:
                i += 1

        results.sort(key=lambda r: r["mean_entropy"])
        return results

    @staticmethod
    def _consensus(records: list[dict], start: int, end: int) -> str:
        consensus = []
        for col in range(start, end):
            bases = [
                r["sequence"][col]
                for r in records
                if col < len(r["sequence"]) and r["sequence"][col] not in ("-", "N")
            ]
            if not bases:
                consensus.append("N")
                continue
            most_common = Counter(bases).most_common(1)[0][0]
            consensus.append(most_common)
        return "".join(consensus)
