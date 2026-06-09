"""
Assay Design API router — /api/v3/assay/*

All Supabase operations use REST API (HTTPS, verify=False).
No direct PostgreSQL connections — company firewall blocks 5432/6543.
Falls back to in-memory cache when Supabase tables are unavailable.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger("openbioshield.assay")
router = APIRouter(prefix="/api/v3/assay", tags=["Assay Design"])

# In-memory cache — survives across requests within the same process lifetime.
# Keyed by job_id. Stores full AssayStatusResponse-compatible dicts.
_JOB_CACHE: dict[str, dict] = {}


# ─── Request / Response Models ────────────────────────────────────────────────

class AssayStatusResponse(BaseModel):
    job_id:        str
    status:        str
    current_step:  int = 1
    report_path:   str | None = None
    error_message: str | None = None
    primers:       list[dict] | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/design", status_code=202)
async def start_assay_design(
    project_name:     str        = Form(...),
    target_name:      str        = Form(...),
    assay_type:       str        = Form("qPCR"),
    fasta_file:       UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Upload a FASTA file and start the 9-step assay design pipeline.
    Returns immediately with a job_id; poll /status/{job_id} for results.
    """
    logger.info(
        "[design] ▶ 요청 수신 | project=%s target=%s assay_type=%s fasta=%s",
        project_name, target_name, assay_type, fasta_file.filename,
    )

    # Save uploaded FASTA to temp file
    suffix = os.path.splitext(fasta_file.filename or ".fasta")[1] or ".fasta"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        content = await fasta_file.read()
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)
        logger.info("[design] STEP 1/3 FASTA 저장 완료 | path=%s size=%d bytes", tmp_path, len(content))
    except Exception as exc:
        os.close(tmp_fd)
        logger.error("[design] STEP 1/3 FAILED FASTA 저장 실패: %s", exc)
        raise HTTPException(status_code=400, detail=f"FASTA upload failed: {exc}") from exc

    # Create job record (Supabase + in-memory cache)
    logger.info("[design] STEP 2/3 — job 생성")
    job_id = await _create_job(project_name, target_name, assay_type)
    logger.info("[design] STEP 2/3 완료 | job_id=%s", job_id)

    # Queue background pipeline
    logger.info("[design] STEP 3/3 — 파이프라인 큐 등록 | job_id=%s", job_id)
    background_tasks.add_task(
        _run_pipeline_task,
        job_id=job_id,
        fasta_path=tmp_path,
        assay_type=assay_type,
        advanced_options=None,
    )
    logger.info("[design] STEP 3/3 완료 → 202 반환 | job_id=%s", job_id)

    return {"job_id": job_id, "status": "RUNNING", "message": "Assay design pipeline started."}


@router.get("/status/{job_id}", response_model=AssayStatusResponse)
async def get_assay_status(job_id: str):
    """Poll pipeline status and results. Checks in-memory cache first, then Supabase."""

    # ── 1. In-memory cache (always available) ─────────────────────────────────
    cached = _JOB_CACHE.get(job_id)
    if cached:
        logger.info("[assay/status] cache hit | job=%s status=%s", job_id, cached["status"])
        return AssayStatusResponse(**cached)

    # ── 2. Supabase fallback ───────────────────────────────────────────────────
    logger.info("[assay/status] cache miss — querying Supabase | job=%s", job_id)
    try:
        from services.supabase_service import _get_client
        client = _get_client()

        job_res = client.table("assay_jobs").select("*").eq("id", job_id).single().execute()
        job = job_res.data
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        primers = None
        if job.get("status") == "COMPLETED":
            p_res = (
                client.table("assay_primers")
                .select("*")
                .eq("assay_id", job_id)
                .order("final_rank")
                .limit(10)
                .execute()
            )
            primers = p_res.data or []

        return AssayStatusResponse(
            job_id=job_id,
            status=job["status"],
            report_path=job.get("report_path"),
            error_message=job.get("error_message"),
            primers=primers,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[assay/status] Supabase 조회 실패 | job=%s error=%s", job_id, exc)
        # Job was created (we queued it) but Supabase has no table yet → still RUNNING
        if job_id in _JOB_CACHE:
            return AssayStatusResponse(**_JOB_CACHE[job_id])
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@router.get("/jobs")
async def list_jobs(limit: int = 20) -> list[dict]:
    """Return recent assay jobs. Merges Supabase results with in-memory cache."""
    # Collect from cache
    cache_jobs = [
        {
            "id":           v["job_id"],
            "project_name": v.get("project_name", ""),
            "target_name":  v.get("target_name", ""),
            "assay_type":   v.get("assay_type", ""),
            "status":       v["status"],
            "created_at":   v.get("created_at", ""),
        }
        for v in sorted(_JOB_CACHE.values(), key=lambda x: x.get("created_at", ""), reverse=True)
    ]

    try:
        from services.supabase_service import _get_client
        client = _get_client()
        res = (
            client.table("assay_jobs")
            .select("id,project_name,target_name,assay_type,status,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        db_jobs = res.data or []
        # Merge: DB takes precedence, cache fills in anything not in DB
        db_ids = {j["id"] for j in db_jobs}
        extra  = [j for j in cache_jobs if j["id"] not in db_ids]
        return (db_jobs + extra)[:limit]
    except Exception as exc:
        logger.warning("[assay/jobs] Supabase unavailable — returning cache only: %s", exc)
        return cache_jobs[:limit]


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _create_job(project_name: str, target_name: str, assay_type: str) -> str:
    """Insert a new assay_jobs row, fall back to ephemeral UUID on failure."""
    now = datetime.now(timezone.utc).isoformat()
    job_id: str | None = None

    try:
        from services.supabase_service import _get_client
        client = _get_client()
        res = client.table("assay_jobs").insert({
            "project_name": project_name,
            "target_name":  target_name,
            "assay_type":   assay_type,
            "status":       "RUNNING",
        }).execute()
        job_id = res.data[0]["id"]
        logger.info("[assay] Supabase job 생성 완료 | job_id=%s", job_id)
    except Exception as exc:
        job_id = str(uuid.uuid4())
        logger.warning("[assay] Supabase INSERT 실패 — ephemeral ID 사용 | job_id=%s error=%s", job_id, exc)

    # Always cache regardless of Supabase success
    _JOB_CACHE[job_id] = {
        "job_id":        job_id,
        "status":        "RUNNING",
        "current_step":  1,
        "project_name":  project_name,
        "target_name":   target_name,
        "assay_type":    assay_type,
        "created_at":    now,
        "report_path":   None,
        "error_message": None,
        "primers":       None,
    }
    return job_id


async def _run_pipeline_task(
    job_id:           str,
    fasta_path:       str,
    assay_type:       str,
    advanced_options: dict | None,
) -> None:
    """Background task: run full orchestrator pipeline and update cache."""
    from services.assay_orchestrator import AssayOrchestrator
    import time

    logger.info("[pipeline] ▶ 시작 | job=%s assay_type=%s fasta=%s", job_id, assay_type, fasta_path)
    t0 = time.perf_counter()

    async def _step_progress(step: int, total: int, msg: str) -> None:
        if job_id in _JOB_CACHE:
            _JOB_CACHE[job_id]["current_step"] = step

    try:
        orchestrator = AssayOrchestrator()
        result = await orchestrator.run_pipeline(
            assay_id=job_id,
            fasta_path=fasta_path,
            assay_type=assay_type,
            advanced_options=advanced_options,
            progress_cb=_step_progress,
        )
        elapsed = time.perf_counter() - t0
        primers = result.get("ranked_primers", [])
        report  = result.get("report_path")

        logger.info(
            "[pipeline] ✅ 완료 | job=%s elapsed=%.1fs primers=%d report=%s",
            job_id, elapsed, len(primers), report,
        )

        # Map internal field names → frontend/Supabase field names
        mapped_primers = [
            {
                "id":                str(i + 1),
                "assay_id":          job_id,
                "forward_primer":    p.get("forward", ""),
                "reverse_primer":    p.get("reverse", ""),
                "tm":                round((p.get("tm_fwd", 0) + p.get("tm_rev", 0)) / 2, 2),
                "gc":                round((p.get("gc_fwd", 0) + p.get("gc_rev", 0)) / 2, 2),
                "coverage_score":    p.get("coverage_score", 0),
                "specificity_score": p.get("specificity_score", 0),
                "thermo_score":      p.get("thermo_score", 0),
                "ai_score":          p.get("ai_score", 0),
                "final_score":       p.get("final_score", 0),
                "final_rank":        p.get("final_rank", i + 1),
                "product_size":      p.get("product_size", 0),
            }
            for i, p in enumerate(primers)
        ]

        # Update in-memory cache
        if job_id in _JOB_CACHE:
            _JOB_CACHE[job_id].update({
                "status":      "COMPLETED",
                "report_path": report,
                "primers":     mapped_primers,
            })

    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.exception("[pipeline] ❌ 실패 | job=%s elapsed=%.1fs error=%s", job_id, elapsed, exc)

        # Update in-memory cache
        if job_id in _JOB_CACHE:
            _JOB_CACHE[job_id].update({
                "status":        "FAILED",
                "error_message": str(exc),
            })

    finally:
        try:
            os.unlink(fasta_path)
            logger.debug("[pipeline] temp FASTA 삭제 | %s", fasta_path)
        except OSError:
            pass
