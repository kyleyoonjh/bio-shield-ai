"""
Position-based primer-variant risk engine.

Weights mismatches by distance from the primer 3' end (primer_end_pos):

  Critical (distance 0–3 bp) : immediate HIGH — DNA polymerase extension origin
  Warning  (distance 4–15 bp): +3 score each
  Normal   (distance 16–22 bp): +1 score each

Final determination:
  HIGH   : any critical-area variant  OR  accumulated score >= 5  OR  CV > 10%
  MEDIUM : score 3–4
  LOW    : score <= 2

The old calculate_risk() in risk_engine.py is kept for the /collect endpoint
(backwards-compat). This module drives the new /position-risk endpoint.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

RiskLevel = Literal["HIGH", "MEDIUM", "LOW"]

CRITICAL_MAX_DIST = 3    # bp from 3' end  (distance 0-3  → last 4 bases)
WARNING_MAX_DIST  = 15   # bp from 3' end  (distance 4-15 → middle section)

SCORE_HIGH_THRESHOLD   = 5
SCORE_MEDIUM_THRESHOLD = 3

WARNING_SCORE = 3
NORMAL_SCORE  = 1


class ZonedMutation(TypedDict):
    position: int
    distance: int     # from primer 3' end (abs)
    ref: str
    alt: str
    gene: str
    effect: str
    zone: str         # "critical" | "warning" | "normal"
    score: int        # score contribution (0 for critical — triggers immediate HIGH)


class PositionRiskResult(TypedDict):
    risk_level: RiskLevel
    score: int
    reasons: list[str]
    zone_details: dict[str, list[ZonedMutation]]
    cv_triggered: bool


# ─── Core algorithm ───────────────────────────────────────────────────────────

def calculate_position_risk(
    mutations: list[dict[str, Any]],
    primer_start_pos: int,
    primer_end_pos: int,
    reproducibility_cv: float | None = None,
) -> PositionRiskResult:
    """
    Calculate variant risk based on distance from primer 3' end.

    Parameters
    ----------
    mutations        : List of dicts with keys: position, ref, alt, gene, effect
    primer_start_pos : Absolute genomic position of primer 5' end
    primer_end_pos   : Absolute genomic position of primer 3' end
    reproducibility_cv : EP05 reproducibility CV (%) — None if unavailable
    """
    zone_details: dict[str, list[ZonedMutation]] = {
        "critical": [],
        "warning":  [],
        "normal":   [],
    }

    score = 0
    cv_triggered = reproducibility_cv is not None and reproducibility_cv > 10

    for m in mutations:
        pos    = int(m.get("position", 0))
        ref    = str(m.get("ref", "?"))
        alt    = str(m.get("alt", "?"))
        gene   = str(m.get("gene", "Unknown"))
        effect = str(m.get("effect", ""))

        if pos < primer_start_pos or pos > primer_end_pos:
            continue

        distance = abs(primer_end_pos - pos)

        if distance <= CRITICAL_MAX_DIST:
            zone    = "critical"
            contrib = 0
        elif distance <= WARNING_MAX_DIST:
            zone    = "warning"
            contrib = WARNING_SCORE
            score  += contrib
        else:
            zone    = "normal"
            contrib = NORMAL_SCORE
            score  += contrib

        zone_details[zone].append(
            ZonedMutation(
                position=pos, distance=distance,
                ref=ref, alt=alt, gene=gene, effect=effect,
                zone=zone, score=contrib,
            )
        )

    critical = zone_details["critical"]
    warning  = zone_details["warning"]
    normal_  = zone_details["normal"]
    reasons: list[str] = []

    # ── Risk level determination ─────────────────────────────────────────────

    if critical:
        risk_level: RiskLevel = "HIGH"
        for zm in critical:
            reasons.append(
                f"[{zm['gene']}] {zm['ref']}→{zm['alt']} 변이가 프라이머 3′ 말단에서 "
                f"{zm['distance']}bp 거리 (pos {zm['position']:,})에 위치 "
                f"— DNA polymerase extension 출발점 차단, 위음성 위험 매우 높음"
            )
        if warning or normal_:
            reasons.append(
                f"추가로 Warning 구역 {len(warning)}개 / Normal 구역 {len(normal_)}개 변이 존재 "
                f"(누적 점수 {score}점) — 전체 프라이머 결합 안정성 복합 저하"
            )
        reasons.append("즉시 변이 특이적 프라이머 재설계 및 임상 검증 프로토콜 재개 권장")

    elif score >= SCORE_HIGH_THRESHOLD or cv_triggered:
        risk_level = "HIGH"
        if score >= SCORE_HIGH_THRESHOLD:
            reasons.append(
                f"Warning 구역 변이 {len(warning)}개 (×{WARNING_SCORE}점) + "
                f"Normal 구역 변이 {len(normal_)}개 (×{NORMAL_SCORE}점) "
                f"→ 누적 위험 점수 {score}pt ≥ 임계치 {SCORE_HIGH_THRESHOLD}pt "
                f"— 프라이머 중심부 결합력 복합 저하, 위음성 위험 높음"
            )
            for zm in warning:
                reasons.append(
                    f"[{zm['gene']}] {zm['ref']}→{zm['alt']} "
                    f"3′ 말단에서 {zm['distance']}bp (Warning 구역 +{WARNING_SCORE}점)"
                )
        if cv_triggered:
            reasons.append(
                f"Reproducibility CV {reproducibility_cv:.1f}% > 허용 기준 10% "
                f"— CLSI EP05 재현성 기준 초과"
            )
        reasons.append("False Negative 위험 높음 — 프라이머 재설계 또는 추가 검증 데이터 수집 즉시 검토")

    elif score >= SCORE_MEDIUM_THRESHOLD:
        risk_level = "MEDIUM"
        reasons.append(
            f"누적 위험 점수 {score}pt (3–4점 구간) — 프라이머 결합 친화력 부분 저하"
        )
        for zm in warning + normal_:
            zone_label = "Warning" if zm["zone"] == "warning" else "Normal"
            reasons.append(
                f"[{zm['gene']}] {zm['ref']}→{zm['alt']} "
                f"3′ 말단에서 {zm['distance']}bp ({zone_label} 구역, +{zm['score']}pt)"
            )
        if cv_triggered:
            reasons.append(
                f"Reproducibility CV {reproducibility_cv:.1f}% > 10% — 추가 재현성 검증 권장"
            )
        reasons.append("추가 검증 데이터 (n ≥ 20) 수집 후 임상 판단 권장")

    else:
        risk_level = "LOW"
        if not warning and not normal_ and not critical:
            reasons.append(
                "프라이머 구간 내 변이 없음 — 현재 변이주 대상 프라이머 특이성 완전 유지"
            )
        else:
            reasons.append(
                f"누적 위험 점수 {score}pt (≤ 2점) "
                f"— Normal 구역 저위험 변이만 존재, 프라이머 3′ 말단 영역 정상"
            )
            for zm in normal_:
                reasons.append(
                    f"[{zm['gene']}] {zm['ref']}→{zm['alt']} "
                    f"3′ 말단에서 {zm['distance']}bp (Normal 구역 +{zm['score']}pt) "
                    f"— 결합 영향 최소"
                )
        if cv_triggered:
            risk_level = "MEDIUM"
            reasons.append(
                f"Reproducibility CV {reproducibility_cv:.1f}% > 10% "
                f"— 서열 위험 없으나 통계 재현성 기준 초과 (MEDIUM 상향)"
            )
        reasons.append("WHO 신규 변이 업데이트 정기 모니터링 지속 권장")

    return PositionRiskResult(
        risk_level=risk_level,
        score=score,
        reasons=reasons,
        zone_details=zone_details,
        cv_triggered=cv_triggered,
    )
