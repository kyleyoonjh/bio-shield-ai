"""
Assay Design API router — /api/v3/assay/*

All state persisted to Supabase (REST API, verify=False for company firewall).
No in-memory cache — supports stateless Vercel serverless deployment.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import glob as _glob
import os as _os

logger = logging.getLogger("openbioshield.assay")
router = APIRouter(prefix="/api/v3/assay", tags=["Assay Design"])

MAX_JOBS = 5  # Phase 3 작업 보존 한도 (FIFO 자동 삭제)


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
        logger.info("[design] FASTA 저장 완료 | path=%s size=%d bytes", tmp_path, len(content))
    except Exception as exc:
        os.close(tmp_fd)
        logger.error("[design] FASTA 저장 실패: %s", exc)
        raise HTTPException(status_code=400, detail=f"FASTA upload failed: {exc}") from exc

    # Create job record in Supabase
    job_id = await _create_job(project_name, target_name, assay_type)
    logger.info("[design] job 생성 완료 | job_id=%s", job_id)

    # Queue background pipeline
    background_tasks.add_task(
        _run_pipeline_task,
        job_id=job_id,
        fasta_path=tmp_path,
        assay_type=assay_type,
        advanced_options=None,
    )
    logger.info("[design] 파이프라인 큐 등록 → 202 반환 | job_id=%s", job_id)

    return {"job_id": job_id, "status": "RUNNING", "message": "Assay design pipeline started."}


@router.get("/status/{job_id}", response_model=AssayStatusResponse)
async def get_assay_status(job_id: str):
    """Poll pipeline status and results. Reads directly from Supabase."""
    import asyncio
    try:
        from services.supabase_service import _get_client
        client = _get_client()

        job_res = await asyncio.to_thread(
            lambda: client.table("assay_jobs").select("*").eq("id", job_id).single().execute()
        )
        job = job_res.data
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        primers = None
        if job.get("status") == "COMPLETED":
            p_res = await asyncio.to_thread(
                lambda: client.table("assay_primers")
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
            current_step=job.get("current_step") or 1,
            report_path=job.get("report_path"),
            error_message=job.get("error_message"),
            primers=primers,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[assay/status] Supabase 조회 실패 | job=%s error=%s", job_id, exc)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@router.get("/report/{job_id}")
async def get_report(job_id: str):
    """Serve the HTML report for a completed assay job."""
    import asyncio
    try:
        from services.supabase_service import _get_client
        client = _get_client()
        res = await asyncio.to_thread(
            lambda: client.table("assay_jobs").select("report_html").eq("id", job_id).single().execute()
        )
        html = res.data.get("report_html") if res.data else None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    if not html:
        raise HTTPException(status_code=404, detail="Report not found or not yet generated")
    return HTMLResponse(content=html)


@router.get("/jobs")
async def list_jobs(limit: int = MAX_JOBS) -> list[dict]:
    """Return recent assay jobs from Supabase."""
    import asyncio
    try:
        from services.supabase_service import _get_client
        client = _get_client()
        res = await asyncio.to_thread(
            lambda: client.table("assay_jobs")
            .select("id,project_name,target_name,assay_type,status,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("[assay/jobs] Supabase unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _create_job(project_name: str, target_name: str, assay_type: str) -> str:
    """Insert a new assay_jobs row in Supabase. Raises HTTPException on failure."""
    import asyncio
    try:
        from services.supabase_service import _get_client
        client = _get_client()
        payload = {
            "project_name": project_name,
            "target_name":  target_name,
            "assay_type":   assay_type,
            "status":       "RUNNING",
            "current_step": 1,
        }
        res = await asyncio.to_thread(
            lambda: client.table("assay_jobs").insert(payload).execute()
        )
        job_id = res.data[0]["id"]
        logger.info("[assay] Supabase job 생성 완료 | job_id=%s", job_id)
        await asyncio.to_thread(lambda: _purge_excess_jobs(client))
        return job_id
    except Exception as exc:
        logger.error("[assay] Supabase job 생성 실패: %s", exc)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


def _purge_excess_jobs(client) -> None:
    """FIFO: MAX_JOBS 초과 시 가장 오래된 작업과 관련 파일 삭제."""
    try:
        res = (
            client.table("assay_jobs")
            .select("id")
            .order("created_at", desc=False)
            .execute()
        )
        all_ids = [r["id"] for r in (res.data or [])]
        excess = all_ids[: max(0, len(all_ids) - MAX_JOBS)]
        if not excess:
            return

        report_dir = _os.path.join(_os.path.dirname(__file__), "..", "reports")

        for job_id in excess:
            # Cascade DELETE: assay_primers도 자동 삭제
            client.table("assay_jobs").delete().eq("id", job_id).execute()
            logger.info("[purge] deleted old job %s", job_id)

            # 물리적 리포트 파일 삭제 (로컬 reports/ 및 /tmp)
            for pattern in (
                _os.path.join(report_dir, f"assay_{job_id}_*"),
                f"/tmp/assay_{job_id}_*",
            ):
                for f in _glob.glob(pattern):
                    try:
                        _os.unlink(f)
                        logger.debug("[purge] deleted report file %s", f)
                    except OSError:
                        pass
    except Exception as exc:
        logger.warning("[purge] excess job purge failed: %s", exc)


async def _run_pipeline_task(
    job_id:           str,
    fasta_path:       str,
    assay_type:       str,
    advanced_options: dict | None,
) -> None:
    """Background task: run full orchestrator pipeline."""
    from services.assay_orchestrator import AssayOrchestrator
    import time

    logger.info("[pipeline] ▶ 시작 | job=%s assay_type=%s", job_id, assay_type)
    t0 = time.perf_counter()

    async def _step_progress(step: int, total: int, msg: str) -> None:
        import asyncio as _aio
        try:
            from services.supabase_service import _get_client
            client = _get_client()
            await _aio.to_thread(
                lambda: client.table("assay_jobs").update({"current_step": step}).eq("id", job_id).execute()
            )
        except Exception as exc:
            logger.warning("[pipeline] step progress update failed: %s", exc)

    try:
        orchestrator = AssayOrchestrator()
        await orchestrator.run_pipeline(
            assay_id=job_id,
            fasta_path=fasta_path,
            assay_type=assay_type,
            advanced_options=advanced_options,
            progress_cb=_step_progress,
        )
        logger.info("[pipeline] ✅ 완료 | job=%s elapsed=%.1fs", job_id, time.perf_counter() - t0)

    except Exception as exc:
        logger.exception("[pipeline] ❌ 실패 | job=%s elapsed=%.1fs error=%s", job_id, time.perf_counter() - t0, exc)

    finally:
        try:
            os.unlink(fasta_path)
            logger.debug("[pipeline] temp FASTA 삭제 | %s", fasta_path)
        except OSError:
            pass
