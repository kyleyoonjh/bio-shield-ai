"""
PFPS (Primer Failure Prediction Score) pipeline.

Architecture
───────────────────────────────────────────────────
Layer 1 — Decision (Deterministic):
    calculate_pfps()  →  100% reproducible rule engine
    Target: IEC 62304 / ISO 14971 validation docs, DHF

Layer 2 — Explanation (AI Narrator):
    explain_pfps()  →  OpenAI GPT-4o clinical report
    Role: human-readable interpretation ONLY.
          GPT-4o NEVER changes risk level or score.
───────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

# Lazy singleton — created on first use to avoid startup errors if key absent
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


# ─── Layer 1: Deterministic Rule Engine ──────────────────────────────────────

def calculate_pfps(
    mutations: list[dict[str, Any]],
    primer_position: dict[str, int],
    reproducibility_cv: float,
) -> dict[str, Any]:
    """
    Pure Python deterministic PFPS calculation.
    Returns identical results for identical inputs — guaranteed.

    Distance weights (from primer 3' end):
      Critical 0–3 bp  → immediate HIGH (Critical Override)
      Warning  4–15 bp → +3 per mutation
      Normal   16–22 bp → +1 per mutation

    Grade cutoffs:
      Critical Override OR CV > 10% OR score >= 5 → HIGH
      3 <= score < 5                               → MEDIUM
      score < 3                                    → LOW
    """
    primer_end   = primer_position["primer_end_pos"]
    total_score  = 0

    critical_hits: list[dict] = []
    warning_hits:  list[dict] = []
    normal_hits:   list[dict] = []
    processed:     list[dict] = []

    for mut in mutations:
        pos  = int(mut.get("position", 0))
        gene = str(mut.get("gene", "Unknown"))
        ref  = str(mut.get("ref", "?"))
        alt  = str(mut.get("alt", "?"))

        # Build human-readable variant label
        variant = mut.get("variant") or f"{gene} {ref}>{alt}"
        mut_type = mut.get("type") or (
            "InDel" if len(ref) != len(alt) else "SNP"
        )
        mismatch_type = mut.get("mismatch_type") or f"{ref}:{alt}"

        distance = abs(primer_end - pos)

        entry = {
            "variant":              variant,
            "position":             pos,
            "type":                 mut_type,
            "mismatch_type":        mismatch_type,
            "distance_to_3prime":   distance,
        }

        if 0 <= distance <= 3:
            critical_hits.append(entry)
        elif 4 <= distance <= 15:
            total_score += 3
            warning_hits.append(entry)
        elif 16 <= distance <= 22:
            total_score += 1
            normal_hits.append(entry)

        processed.append(entry)

    # ── Decision hierarchy ────────────────────────────────────────────────────

    # Rule 1: Critical Override
    if critical_hits:
        hit = critical_hits[0]
        return {
            "risk_level":         "HIGH",
            "score":              999,
            "is_critical_override": True,
            "cv_escalated":       False,
            "processed_mutations": processed,
            "trigger_reason": (
                f"Critical Override: {hit['variant']} 변이가 "
                f"프라이머 3′ 말단에서 {hit['distance_to_3prime']}bp 거리(pos {hit['position']:,})에 위치 "
                f"— DNA polymerase extension 출발점 직격, 증폭 실패 확률 최고조"
            ),
        }

    # Rule 2: CV Escalation
    if reproducibility_cv > 10.0:
        return {
            "risk_level":         "HIGH",
            "score":              total_score,
            "is_critical_override": False,
            "cv_escalated":       True,
            "processed_mutations": processed,
            "trigger_reason": (
                f"CV Escalation: 재현성 오차율 {reproducibility_cv:.1f}% > 허용 기준 10.0% "
                f"— 통계적 불확실성에 의한 HIGH 에스컬레이션"
            ),
        }

    # Rule 3: Score cutoff
    if total_score >= 5:
        risk_level = "HIGH"
        trigger = (
            f"누적 PFPS {total_score}pt ≥ 5pt 임계치 "
            f"(Warning {len(warning_hits)}개×3pt + Normal {len(normal_hits)}개×1pt)"
        )
    elif total_score >= 3:
        risk_level = "MEDIUM"
        trigger = (
            f"누적 PFPS {total_score}pt — Warning 구역 변이 영향 "
            f"(MEDIUM 등급, 3pt ≤ score < 5pt)"
        )
    else:
        risk_level = "LOW"
        trigger = (
            f"누적 PFPS {total_score}pt — Critical 및 Warning 구역 변이 없음 "
            f"(LOW 등급, score < 3pt)"
        )

    return {
        "risk_level":         risk_level,
        "score":              total_score,
        "is_critical_override": False,
        "cv_escalated":       False,
        "processed_mutations": processed,
        "trigger_reason":     trigger,
    }


# ─── Layer 2: AI Explanation (Narrator Only) ─────────────────────────────────

_SYSTEM_PROMPT = """\
당신은 분자진단 기기 전문 임상 평가 위원이자 OpenBioShield의 AI 리포터입니다.
당신의 역할은 '이미 결정론적 계산기(Rule Engine)가 도출한 계산 결과'를 바탕으로 \
임상 검사원과 규제 당국(식약처, FDA)이 납득할 수 있는 고품질의 국문 해설 리포트를 작성하는 것입니다.

절대로 임의로 위험도 등급(HIGH/MEDIUM/LOW)이나 스코어 숫자를 변경하거나 재산산하지 마십시오. \
오직 주어진 결과를 생물학적·실험 통계학적 근거로 풀어서 설명해야 합니다.

[작성 서식]
1. 총평: 최종 등급과 점수를 명시하고 전체 안전 유무 요약.
2. 분자생물학적 변이 분석: 3′ 말단 거리가 미치는 정량적 영향력 설명 (InDel/미스매치 언급).
3. 실험 시스템 안정성: 입력된 reproducibility_cv 값과 시스템 연동성 분석.
4. 검사 권고사항: 현장 검사원이 취해야 할 가이드라인 제시.
"""


def explain_pfps(risk_result: dict[str, Any], reproducibility_cv: float) -> str:
    """
    Layer 2: GPT-4o narrates the deterministic result.
    Never mutates risk_level or score — explanation only.
    """
    user_content = (
        f"[분석 결과 데이터]\n"
        f"- 최종 판정 위험도 (Risk Level): {risk_result['risk_level']}\n"
        f"- 산정 룰 스코어 (PFPS Score): {risk_result['score']}\n"
        f"- 규칙 엔진 판정 근거: {risk_result['trigger_reason']}\n"
        f"- 입력된 재현성 오차 (CV %): {reproducibility_cv}%\n"
        f"- 변이 상세 내역 (JSON):\n"
        f"{json.dumps(risk_result['processed_mutations'], ensure_ascii=False, indent=2)}\n\n"
        "위 데이터를 바탕으로 검사원 가이드용 임상 설명 리포트를 한글로 신중하고 전문적인 어조로 작성해 주십시오."
    )

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("[pfps/explain] OpenAI call failed: %s", exc)
        return (
            f"OpenAI 해설 엔진 연동 오류 — 정량 근거만 표기합니다.\n\n"
            f"판정 근거: {risk_result['trigger_reason']}"
        )
