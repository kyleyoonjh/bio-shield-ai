"""
Assay Design API router — /api/v3/assay/*

All Supabase operations use REST API (HTTPS, verify=False).
No direct PostgreSQL connections — company firewall blocks 5432/6543.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger("openbioshield.assay")
router = APIRouter(prefix="/api/v3/assay", tags=["Assay Design"])


# ─── Request / Response Models ────────────────────────────────────────────────

class AssayCreateRequest(BaseModel):
    project_name: str
    target_name:  str
    assay_type:   str = "qPCR"          # qPCR | Multiplex qPCR
    advanced_options: dict[str, Any] | None = None


class AssayStatusResponse(BaseModel):
    job_id:       str
    status:       str
    report_path:  str | None = None
    error_message: str | None = None
    primers:      list[dict] | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/design", status_code=202)
async def start_assay_design(
    project_name:     str  = Form(...),
    target_name:      str  = Form(...),
    assay_type:       str  = Form("qPCR"),
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

    # Save uploaded FASTA to temp file (pipeline reads from disk)
    suffix = os.path.splitext(fasta_file.filename or ".fasta")[1] or ".fasta"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        content = await fasta_file.read()
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)
        logger.info("[design] FASTA 저장 완료 | path=%s size=%d bytes", tmp_path, len(content))
    except Exception as exc:
        os.close(tmp_fd)
        logger.error("[design] FASTA 저장 실패: %s", exc)
        raise HTTPException(status_code=400, detail=f"FASTA upload failed: {exc}") from exc

    # Create job record in Supabase
    job_id = await _create_job(project_name, target_name, assay_type)
    logger.info("[design] job 생성 완료 | job_id=%s", job_id)

    # Queue pipeline as background task
    background_tasks.add_task(
        _run_pipeline_task,
        job_id=job_id,
        fasta_path=tmp_path,
        assay_type=assay_type,
        advanced_options=None,
    )
    logger.info("[design] 백그라운드 파이프라인 큐 등록 완료 | job_id=%s", job_id)

    return {
        "job_id":  job_id,
        "status":  "RUNNING",
        "message": "Assay design pipeline started.",
    }


@router.get("/status/{job_id}", response_model=AssayStatusResponse)
async def get_assay_status(job_id: str):
    """Poll pipeline status and results."""
    try:
        from services.supabase_service import _get_client
        client = _get_client()

        job_res = client.table("assay_jobs").select("*").eq("id", job_id).single().execute()
        job     = job_res.data
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        primers = None
        if job.get("status") == "COMPLETED":
            p_res   = (
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
        logger.error("[assay/status] %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/jobs")
async def list_jobs(limit: int = 20) -> list[dict]:
    """Return recent assay jobs."""
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
        return res.data or []
    except Exception as exc:
        logger.warning("[assay/jobs] Supabase unavailable: %s", exc)
        return []


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _create_job(project_name: str, target_name: str, assay_type: str) -> str:
    """Insert a new assay_jobs row and return its UUID."""
    try:
        from services.supabase_service import _get_client
        client = _get_client()
        res = client.table("assay_jobs").insert({
            "project_name": project_name,
            "target_name":  target_name,
            "assay_type":   assay_type,
            "status":       "RUNNING",
        }).execute()
        return res.data[0]["id"]
    except Exception as exc:
        logger.warning("[assay] Supabase unavailable — using ephemeral ID: %s", exc)
        import uuid
        return str(uuid.uuid4())


async def _run_pipeline_task(
    job_id:          str,
    fasta_path:      str,
    assay_type:      str,
    advanced_options: dict | None,
) -> None:
    """Background task: run full orchestrator pipeline."""
    from services.assay_orchestrator import AssayOrchestrator
    import time

    logger.info("[pipeline] ▶ 시작 | job=%s assay_type=%s fasta=%s", job_id, assay_type, fasta_path)
    t0 = time.perf_counter()

    try:
        orchestrator = AssayOrchestrator()
        result = await orchestrator.run_pipeline(
            assay_id=job_id,
            fasta_path=fasta_path,
            assay_type=assay_type,
            advanced_options=advanced_options,
        )
        elapsed = time.perf_counter() - t0
        logger.info(
            "[pipeline] ✅ 완료 | job=%s elapsed=%.1fs primers=%d report=%s",
            job_id, elapsed,
            len(result.get("ranked_primers", [])),
            result.get("report_path"),
        )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.exception("[pipeline] ❌ 실패 | job=%s elapsed=%.1fs error=%s", job_id, elapsed, exc)
    finally:
        try:
            os.unlink(fasta_path)
            logger.debug("[pipeline] temp FASTA 삭제 | %s", fasta_path)
        except OSError:
            pass
