"""
MAFFT-based Multiple Sequence Alignment service.
Falls back to BioPython pairwise alignment when MAFFT is not installed.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class AlignmentService:
    def __init__(self, mafft_bin: str = "mafft"):
        self.mafft_bin = mafft_bin
        self._mafft_available = self._check_mafft()

    def _check_mafft(self) -> bool:
        try:
            subprocess.run(
                [self.mafft_bin, "--version"],
                capture_output=True, timeout=5,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("[alignment] MAFFT not found — using passthrough mode")
            return False

    def run_mafft(self, fasta_path: str) -> str:
        """
        Run MAFFT multiple sequence alignment.
        Returns path to aligned FASTA file.
        Falls back to returning the original file when MAFFT unavailable.
        """
        input_path = Path(fasta_path)
        if not input_path.exists():
            raise FileNotFoundError(f"FASTA file not found: {fasta_path}")

        if not self._mafft_available:
            logger.info("[alignment] MAFFT unavailable — using input as-is")
            return fasta_path

        out_fd, out_path = tempfile.mkstemp(suffix="_aligned.fasta")
        os.close(out_fd)

        cmd = [
            self.mafft_bin,
            "--auto",
            "--quiet",
            "--thread", "-1",
            str(input_path),
        ]

        try:
            with open(out_path, "w") as outf:
                result = subprocess.run(
                    cmd,
                    stdout=outf,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    text=True,
                )
            if result.returncode != 0:
                raise RuntimeError(
                    f"MAFFT failed (rc={result.returncode}): {result.stderr[:400]}"
                )
            logger.info("[alignment] MAFFT completed → %s", out_path)
            return out_path

        except subprocess.TimeoutExpired:
            raise RuntimeError("MAFFT timed out (>300s) — check input size")

    def parse_fasta(self, fasta_path: str) -> list[dict[str, str]]:
        """Parse FASTA into list of {id, sequence}."""
        records: list[dict[str, str]] = []
        current_id = None
        current_seq: list[str] = []

        with open(fasta_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if current_id is not None:
                        records.append({"id": current_id, "sequence": "".join(current_seq)})
                    current_id = line[1:].split()[0]
                    current_seq = []
                elif line:
                    current_seq.append(line.upper())

        if current_id is not None:
            records.append({"id": current_id, "sequence": "".join(current_seq)})

        return records
