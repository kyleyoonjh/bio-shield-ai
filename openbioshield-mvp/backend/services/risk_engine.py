"""Rule-based variant risk assessment engine."""

from __future__ import annotations

from typing import Literal

RiskLevel = Literal["HIGH", "MEDIUM", "LOW"]


def calculate_risk(
    mismatch_count: int,
    three_prime_mismatch: bool,
    reproducibility_cv: float | None,
) -> RiskLevel:
    """
    Rule-based risk scoring for primer-variant compatibility.

    HIGH:   >= 2 mismatches, OR 3'-end mismatch (critical for extension)
    MEDIUM: 1 mismatch, OR reproducibility CV > 10% (CLSI EP05 threshold)
    LOW:    no mismatches, CV within acceptable range
    """
    if mismatch_count >= 2 or three_prime_mismatch:
        return "HIGH"
    if mismatch_count == 1 or (
        reproducibility_cv is not None and reproducibility_cv > 10
    ):
        return "MEDIUM"
    return "LOW"
