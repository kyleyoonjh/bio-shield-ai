"""
Assay Design API router — /api/v3/assay/*

All state persisted to Supabase (REST API, verify=False for company firewall).
No in-memory cache — supports stateless Vercel serverless deployment.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
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
    t0 = time.perf_counter()
    logger.info(
        "[design] ▶ START | project=%s target=%s assay_type=%s fasta=%s",
        project_name, target_name, assay_type, fasta_file.filename,
    )

    # Save uploaded FASTA to temp file
    suffix = os.path.splitext(fasta_file.filename or ".fasta")[1] or ".fasta"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        content = await fasta_file.read()
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)
        logger.info("[design] FASTA saved | path=%s size=%d bytes elapsed=%.3fs",
                    tmp_path, len(content), time.perf_counter() - t0)
    except Exception as exc:
        os.close(tmp_fd)
        logger.error("[design] FASTA save FAILED | error=%s elapsed=%.3fs", exc, time.perf_counter() - t0)
        raise HTTPException(status_code=400, detail=f"FASTA upload failed: {exc}") from exc

    # Create job record in Supabase
    job_id = await _create_job(project_name, target_name, assay_type)

    # Queue background pipeline
    background_tasks.add_task(
        _run_pipeline_task,
        job_id=job_id,
        fasta_path=tmp_path,
        assay_type=assay_type,
        advanced_options=None,
    )
    logger.info("[design] ✅ 202 返 | job=%s total_elapsed=%.3fs", job_id, time.perf_counter() - t0)

    return {"job_id": job_id, "status": "RUNNING", "message": "Assay design pipeline started."}


@router.get("/status/{job_id}", response_model=AssayStatusResponse)
async def get_assay_status(job_id: str):
    """Poll pipeline status and results. Reads directly from Supabase."""
    t0 = time.perf_counter()
    try:
        from services.supabase_service import _get_client
        client = _get_client()

        t_sb = time.perf_counter()
        job_res = await asyncio.to_thread(
            lambda: client.table("assay_jobs").select("*").eq("id", job_id).single().execute()
        )
        sb_ms = (time.perf_counter() - t_sb) * 1000
        job = job_res.data
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        status = job["status"]
        step   = job.get("current_step") or 1

        primers = None
        if status == "COMPLETED":
            t_sb2 = time.perf_counter()
            p_res = await asyncio.to_thread(
                lambda: client.table("assay_primers")
                .select("*")
                .eq("assay_id", job_id)
                .order("final_rank")
                .limit(10)
                .execute()
            )
            sb_ms2 = (time.perf_counter() - t_sb2) * 1000
            primers = p_res.data or []
            logger.info(
                "[status] COMPLETED | job=%s primers=%d job_query=%.0fms primer_query=%.0fms total=%.0fms",
                job_id, len(primers), sb_ms, sb_ms2, (time.perf_counter() - t0) * 1000,
            )
        elif status == "FAILED":
            logger.warning(
                "[status] FAILED | job=%s error=%s sb=%.0fms",
                job_id, job.get("error_message", "")[:120], sb_ms,
            )
        else:
            logger.debug(
                "[status] RUNNING step=%d | job=%s sb=%.0fms",
                step, job_id, sb_ms,
            )

        return AssayStatusResponse(
            job_id=job_id,
            status=status,
            current_step=step,
            report_path=job.get("report_path"),
            error_message=job.get("error_message"),
            primers=primers,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[status] Supabase ERROR | job=%s error=%s elapsed=%.0fms",
                     job_id, exc, (time.perf_counter() - t0) * 1000)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@router.get("/report/{job_id}")
async def get_report(job_id: str):
    """Serve the HTML report for a completed assay job."""
    t0 = time.perf_counter()
    logger.info("[report] GET | job=%s", job_id)
    try:
        from services.supabase_service import _get_client
        client = _get_client()
        res = await asyncio.to_thread(
            lambda: client.table("assay_jobs").select("report_html").eq("id", job_id).single().execute()
        )
        html = res.data.get("report_html") if res.data else None
        html_kb = len(html) // 1024 if html else 0
        logger.info("[report] Supabase query done | job=%s html_kb=%d elapsed=%.0fms",
                    job_id, html_kb, (time.perf_counter() - t0) * 1000)
    except Exception as exc:
        logger.error("[report] Supabase ERROR | job=%s error=%s elapsed=%.0fms",
                     job_id, exc, (time.perf_counter() - t0) * 1000)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    if not html:
        logger.warning("[report] NOT FOUND | job=%s", job_id)
        raise HTTPException(status_code=404, detail="Report not found or not yet generated")
    return HTMLResponse(content=html)


@router.get("/jobs")
async def list_jobs(limit: int = MAX_JOBS) -> list[dict]:
    """Return recent assay jobs from Supabase."""
    t0 = time.perf_counter()
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
        jobs = res.data or []
        logger.info("[jobs] listed %d jobs | elapsed=%.0fms", len(jobs), (time.perf_counter() - t0) * 1000)
        return jobs
    except Exception as exc:
        logger.warning("[jobs] Supabase ERROR | error=%s elapsed=%.0fms",
                       exc, (time.perf_counter() - t0) * 1000)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _create_job(project_name: str, target_name: str, assay_type: str) -> str:
    """Insert a new assay_jobs row in Supabase. Raises HTTPException on failure."""
    t0 = time.perf_counter()
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
        logger.info("[create_job] INSERT OK | job=%s elapsed=%.0fms",
                    job_id, (time.perf_counter() - t0) * 1000)
        await asyncio.to_thread(lambda: _purge_excess_jobs(client))
        return job_id
    except Exception as exc:
        logger.error("[create_job] INSERT FAILED | error=%s elapsed=%.0fms",
                     exc, (time.perf_counter() - t0) * 1000)
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

        logger.info("[purge] deleting %d excess jobs (total=%d, limit=%d)",
                    len(excess), len(all_ids), MAX_JOBS)
        report_dir = _os.path.join(_os.path.dirname(__file__), "..", "reports")

        for job_id in excess:
            client.table("assay_jobs").delete().eq("id", job_id).execute()
            logger.info("[purge] deleted job %s", job_id)

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
        logger.warning("[purge] FAILED | error=%s", exc)


async def _run_pipeline_task(
    job_id:           str,
    fasta_path:       str,
    assay_type:       str,
    advanced_options: dict | None,
) -> None:
    """Background task: run full orchestrator pipeline."""
    from services.assay_orchestrator import AssayOrchestrator

    t0 = time.perf_counter()
    logger.info("[pipeline] ▶ START | job=%s assay_type=%s", job_id, assay_type)

    async def _step_progress(step: int, total: int, msg: str) -> None:
        t_sb = time.perf_counter()
        try:
            from services.supabase_service import _get_client
            client = _get_client()
            await asyncio.to_thread(
                lambda: client.table("assay_jobs").update({"current_step": step}).eq("id", job_id).execute()
            )
            logger.debug("[pipeline] step_progress UPDATE | job=%s step=%d/%d sb=%.0fms",
                         job_id, step, total, (time.perf_counter() - t_sb) * 1000)
        except Exception as exc:
            logger.warning("[pipeline] step_progress FAILED | job=%s step=%d error=%s sb=%.0fms",
                           job_id, step, exc, (time.perf_counter() - t_sb) * 1000)

    try:
        orchestrator = AssayOrchestrator()
        await orchestrator.run_pipeline(
            assay_id=job_id,
            fasta_path=fasta_path,
            assay_type=assay_type,
            advanced_options=advanced_options,
            progress_cb=_step_progress,
        )
        logger.info("[pipeline] ✅ DONE | job=%s total=%.1fs", job_id, time.perf_counter() - t0)

    except Exception as exc:
        logger.exception("[pipeline] ❌ FAILED | job=%s total=%.1fs error=%s",
                         job_id, time.perf_counter() - t0, exc)

    finally:
        try:
            os.unlink(fasta_path)
            logger.debug("[pipeline] temp FASTA deleted | %s", fasta_path)
        except OSError:
            pass
