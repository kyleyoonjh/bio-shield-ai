"""Phase 2 API — /api/v2/* endpoints for data collection and risk scoring."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ncbi_service import fetch_bio_context
from services.risk_engine import calculate_risk
from services.supabase_service import (
    get_dataset_stats,
    insert_experiment,
    insert_feedback,
)
from services.migration_service import run_migration, check_token_configured
from services.initial_risk_engine import calculate_position_risk
from services.pfps_engine import calculate_pfps, explain_pfps

logger = logging.getLogger("openbioshield.v2")
router = APIRouter(prefix="/api/v2", tags=["Phase 2"])


# ─── Request / Response Models ────────────────────────────────────────────────

class CollectRequest(BaseModel):
    disease_type: str
    variant_name: str = "wild-type"
    mismatch_count: int = 0
    three_prime_mismatch: bool = False
    # EP05 stats
    grand_mean: float | None = None
    repeatability_cv: float | None = None
    reproducibility_cv: float | None = None
    anova_f_value: float | None = None
    anova_p_value: float | None = None
    sample_count: int | None = None
    # EP09 stats
    deming_slope: float | None = None
    bland_altman_mean_diff: float | None = None
    pearson_r: float | None = None
    # Lab context (optional)
    instrument: str | None = None
    assay_type: str | None = None
    test_date: str | None = None
    guideline: str | None = None
    source_filename: str | None = None


class CollectResponse(BaseModel):
    id: str
    risk_level: Literal["HIGH", "MEDIUM", "LOW"]
    message: str


class PositionRiskRequest(BaseModel):
    mutations: list[dict[str, Any]]
    primer_start_pos: int
    primer_end_pos: int
    reproducibility_cv: float | None = None


class PfpsMutationItem(BaseModel):
    position: int
    gene: str = "Unknown"
    ref: str = "?"
    alt: str = "?"
    effect: str = ""
    # Optional override fields (compatible with legacy variant-string schema)
    variant: str | None = None
    type: str = "SNP"
    mismatch_type: str | None = None


class PfpsRequest(BaseModel):
    mutations: list[PfpsMutationItem]
    primer_position: dict[str, int]   # {"primer_start_pos": int, "primer_end_pos": int}
    reproducibility_cv: float = 0.0


class FeedbackRequest(BaseModel):
    experiment_id: str | None = None
    feedback_value: Literal["accurate", "partially_accurate", "incorrect"]
    guideline: str | None = None
    disease_type: str | None = None
    variant_name: str | None = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/collect", response_model=CollectResponse)
@router.post("/save-dataset", response_model=CollectResponse, include_in_schema=False)
async def collect_experiment(request: CollectRequest) -> CollectResponse:
    """Auto-collect analysis data into Supabase after EP05/EP09 analysis."""

    # Fetch primer info from bio context (uses disk cache — fast)
    ps: dict[str, Any] = {}
    try:
        bio_ctx = await fetch_bio_context(request.disease_type)
        ps = bio_ctx.get("primer_structure", {}) or {}
    except Exception as exc:
        logger.warning("[v2/collect] bio_context fetch failed (non-fatal): %s", exc)

    # Calculate rule-based risk
    risk = calculate_risk(
        request.mismatch_count,
        request.three_prime_mismatch,
        request.reproducibility_cv,
    )

    payload = _strip_none({
        "disease_type":        request.disease_type,
        "variant_name":        request.variant_name,
        "mismatch_count":      request.mismatch_count,
        "three_prime_mismatch": request.three_prime_mismatch,
        # Primer info from bio context
        "primer_sequence": ps.get("sequence"),
        "primer_length":   ps.get("length"),
        "gc_percent":      ps.get("gc_percent"),
        "tm_celsius":      ps.get("tm_celsius"),
        "dot_bracket":     ps.get("dot_bracket"),
        "mfe":             ps.get("mfe"),
        # Experimental stats
        "grand_mean":         request.grand_mean,
        "repeatability_cv":   request.repeatability_cv,
        "reproducibility_cv": request.reproducibility_cv,
        "anova_f_value":      request.anova_f_value,
        "anova_p_value":      request.anova_p_value,
        "sample_count":       request.sample_count,
        "deming_slope":           request.deming_slope,
        "bland_altman_mean_diff": request.bland_altman_mean_diff,
        "pearson_r":              request.pearson_r,
        # Lab context
        "instrument":      request.instrument,
        "assay_type":      request.assay_type,
        "test_date":       request.test_date,
        "guideline":       request.guideline,
        "source_filename": request.source_filename,
        "risk_level": risk,
    })

    loop = asyncio.get_running_loop()
    try:
        record = await loop.run_in_executor(None, insert_experiment, payload)
        logger.info(
            "[v2/collect] saved id=%s risk=%s disease=%s variant=%s",
            record.get("id"), risk, request.disease_type, request.variant_name,
        )
        return CollectResponse(
            id=record["id"],
            risk_level=risk,
            message="Collected successfully",
        )
    except Exception as exc:
        logger.error("[v2/collect] Supabase insert failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Data collection temporarily unavailable",
        ) from exc


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict[str, str]:
    """Store researcher feedback on AI report accuracy."""
    payload = _strip_none({
        "experiment_id":  request.experiment_id,
        "feedback_value": request.feedback_value,
        "guideline":      request.guideline,
        "disease_type":   request.disease_type,
        "variant_name":   request.variant_name,
    })
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, insert_feedback, payload)
        logger.info("[v2/feedback] saved value=%s", request.feedback_value)
        return {"message": "Feedback recorded"}
    except Exception as exc:
        logger.error("[v2/feedback] Supabase insert failed: %s", exc)
        raise HTTPException(status_code=503, detail="Feedback storage unavailable") from exc


_EMPTY_STATS: dict[str, Any] = {
    "total_records": 0,
    "fine_tuning_threshold": 5000,
    "readiness_percent": 0.0,
    "is_ready": False,
    "by_disease": {"SARS-CoV-2": 0, "HPV": 0, "STI": 0},
    "by_risk": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
    "by_guideline": {"EP05": 0, "EP09": 0},
    "recent_30d": 0,
    "_status": "ok",
}


@router.post("/pfps")
async def pfps_risk(request: PfpsRequest) -> dict[str, Any]:
    """
    PFPS two-layer pipeline:
      Layer 1 — calculate_pfps()  : deterministic rule engine (100% reproducible)
      Layer 2 — explain_pfps()    : GPT-4o narrates the result (explanation only)

    GPT-4o NEVER changes risk_level or score — it is a narrator, not a decision maker.
    """
    mutations_list = [m.model_dump() for m in request.mutations]

    loop = asyncio.get_running_loop()

    # Layer 1: deterministic (fast, synchronous)
    risk_result = await loop.run_in_executor(
        None,
        lambda: calculate_pfps(
            mutations=mutations_list,
            primer_position=request.primer_position,
            reproducibility_cv=request.reproducibility_cv,
        ),
    )

    # Layer 2: GPT-4o explanation (may take several seconds)
    reason = await loop.run_in_executor(
        None,
        lambda: explain_pfps(
            risk_result=risk_result,
            reproducibility_cv=request.reproducibility_cv,
        ),
    )

    return {
        "risk_level": risk_result["risk_level"],
        "score":      risk_result["score"],
        "reason":     reason,
        "meta_metrics": {
            "is_critical_override":  risk_result["is_critical_override"],
            "cv_escalated":          risk_result["cv_escalated"],
            "trigger_rule_summary":  risk_result["trigger_reason"],
        },
    }


@router.post("/position-risk")
async def position_risk(request: PositionRiskRequest) -> dict[str, Any]:
    """
    Distance-weighted primer-variant risk assessment.

    Scores mutations by their distance from the primer 3' end:
      Critical (0–3 bp)  → immediate HIGH
      Warning  (4–15 bp) → +3 score each
      Normal   (16+ bp)  → +1 score each

    HIGH if: critical variant present  OR  score >= 5  OR  CV > 10%
    MEDIUM if: score 3–4
    LOW   if: score <= 2
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: calculate_position_risk(
            mutations=request.mutations,
            primer_start_pos=request.primer_start_pos,
            primer_end_pos=request.primer_end_pos,
            reproducibility_cv=request.reproducibility_cv,
        ),
    )
    return result


@router.post("/setup-tables")
async def setup_tables() -> dict[str, str]:
    """
    Create primer_experiments and feedback_records tables via the Supabase
    Management API.  Idempotent (uses CREATE TABLE IF NOT EXISTS).

    Requires SUPABASE_ACCESS_TOKEN (personal access token) in backend/.env.
    Generate one at https://supabase.com/dashboard/account/tokens.
    """
    if not check_token_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "SUPABASE_ACCESS_TOKEN is not set in backend/.env. "
                "Generate a Personal Access Token at "
                "https://supabase.com/dashboard/account/tokens and add it."
            ),
        )
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, run_migration)
        logger.info("[v2/setup-tables] Migration completed: %s", result)
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[v2/setup-tables] Migration failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dataset/stats")
async def dataset_stats() -> dict[str, Any]:
    """Return aggregated dataset statistics for the Data Collection dashboard."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, get_dataset_stats)
    except Exception as exc:
        # Supabase not configured or tables not created yet — return empty stats
        logger.warning("[v2/dataset/stats] Supabase unavailable, returning empty stats: %s", exc)
        return {**_EMPTY_STATS, "_status": "supabase_unavailable", "_error": str(exc)}
