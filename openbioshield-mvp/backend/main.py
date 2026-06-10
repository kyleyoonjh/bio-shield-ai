"""FastAPI entrypoint for OpenBioShield MVP."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Literal

from dotenv import load_dotenv

# load_dotenv() MUST run before any service import so env vars
# (e.g. SUPABASE_SSL_VERIFY) are visible when module-level code executes.
load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.ai_service import generate_report, map_schema, map_schema_ep09
from services.ncbi_service import fetch_bio_context
from services.variant_service import get_mutations, get_variant_list
from services.stats_engine import (
    analyze_method_comparison,
    analyze_precision,
    extract_excel_metadata,
)
from routers.v2 import router as v2_router
from routers.assay import router as assay_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("openbioshield")

app = FastAPI(
    title="OpenBioShield API",
    description="Multi-target clinical R&D statistical validation platform",
    version="2.0.0",
)

cors_origins = os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(v2_router)
app.include_router(assay_router)



@app.on_event("startup")
async def _log_routes():
    routes = [f"  {m:6s} {r.path}" for r in app.routes if hasattr(r, "methods") for m in r.methods]
    logger.info("[startup] 등록된 라우트 %d개:\n%s", len(routes), "\n".join(sorted(routes)))


@app.exception_handler(404)
async def _not_found_handler(request: Request, exc: Exception):
    logger.warning("[404] %s %s — 등록된 경로 없음", request.method, request.url.path)
    return JSONResponse(status_code=404, content={"detail": f"Not Found: {request.method} {request.url.path}"})


SUPPORTED_DISEASES = ("SARS-CoV-2", "HPV", "STI")


# ─── Models ───────────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    stats_data: dict[str, Any]
    language: str = "ko"


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "OpenBioShield API v2",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": "OpenBioShield v2"}


# ─── Bio Context (NCBI real-time) ────────────────────────────────────────────

@app.get("/api/v1/bio-context")
async def get_bio_context(
    disease_type: str = Query(
        default="SARS-CoV-2",
        description="Target disease. One of: SARS-CoV-2, HPV, STI",
    )
):
    logger.info("[bio-context] disease_type=%s", disease_type)
    if disease_type not in SUPPORTED_DISEASES:
        logger.warning("[bio-context] unsupported disease_type=%s", disease_type)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported disease_type '{disease_type}'. Valid: {SUPPORTED_DISEASES}",
        )
    t0 = time.perf_counter()
    context = await fetch_bio_context(disease_type)
    logger.info("[bio-context] done in %.2fs  source=%s", time.perf_counter() - t0, context.get("source"))
    return context


# ─── Variant List ────────────────────────────────────────────────────────────

@app.get("/api/v1/variants")
def list_variants(disease_type: str = Query(...)):
    logger.info("[variants] disease_type=%s", disease_type)
    if disease_type not in SUPPORTED_DISEASES:
        logger.warning("[variants] unsupported disease_type=%s", disease_type)
        raise HTTPException(status_code=400, detail=f"Unsupported disease_type '{disease_type}'")
    variants = get_variant_list(disease_type)
    logger.info("[variants] returning %d variants for %s", len(variants), disease_type)
    return {"disease_type": disease_type, "variants": variants}


# ─── Mutation Delta ───────────────────────────────────────────────────────────

@app.get("/api/v1/mutations")
def list_mutations(
    disease_type: str = Query(...),
    variant: str = Query(...),
):
    logger.info("[mutations] disease_type=%s  variant=%s", disease_type, variant)
    if disease_type not in SUPPORTED_DISEASES:
        logger.warning("[mutations] unsupported disease_type=%s", disease_type)
        raise HTTPException(status_code=400, detail=f"Unsupported disease_type '{disease_type}'")
    mutations = get_mutations(disease_type, variant)
    logger.info("[mutations] returning %d mutations", len(mutations))
    return {
        "disease_type": disease_type,
        "variant": variant,
        "mutations": mutations,
    }


# ─── Upload (schema detection only) ─────────────────────────────────────────

@app.post("/api/v1/upload")
async def upload_excel(
    file: UploadFile = File(...),
    guideline: str = Form(default="EP05"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    allowed = {".xlsx", ".xls", ".csv"}
    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in file.filename else ""
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    logger.info("[upload] filename=%s  guideline=%s  size=%d bytes", file.filename, guideline, len(file_bytes))
    try:
        t0 = time.perf_counter()
        metadata = extract_excel_metadata(file_bytes, file.filename)
        logger.info("[upload] metadata extracted: %d columns, %d rows", metadata.get("column_count", 0), metadata.get("row_preview_count", 0))
        if guideline.upper() == "EP09":
            schema_mapping = map_schema_ep09(metadata)
        else:
            schema_mapping = map_schema(metadata)
        logger.info("[upload] schema mapped in %.2fs: %s", time.perf_counter() - t0, schema_mapping)
    except ValueError as e:
        logger.error("[upload] ValueError: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[upload] unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Schema mapping failed: {e}") from e

    return {"metadata": metadata, "schema_mapping": schema_mapping}


# ─── Analyze EP05 (Precision) ────────────────────────────────────────────────

@app.post("/api/v1/analyze/ep05")
async def analyze_ep05(
    file: UploadFile = File(...),
    schema_mapping: str = Form(...),
):
    """
    CLSI EP05-A3 Precision Analysis.
    schema_mapping JSON: { "target_column": "...", "group_columns": ["..."] }
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        schema = json.loads(schema_mapping)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid schema_mapping JSON") from e

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    logger.info("[ep05] filename=%s  schema=%s", file.filename, schema)
    try:
        t0 = time.perf_counter()
        results = analyze_precision(file_bytes, schema, file.filename)
        logger.info("[ep05] done in %.2fs  samples=%s", time.perf_counter() - t0, results.get("sample_count"))
    except ValueError as e:
        logger.error("[ep05] ValueError: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[ep05] unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"EP05 analysis failed: {e}") from e

    return results


# ─── Analyze EP09 (Method Comparison) ────────────────────────────────────────

@app.post("/api/v1/analyze/ep09")
async def analyze_ep09(
    file: UploadFile = File(...),
    schema_mapping: str = Form(...),
):
    """
    CLSI EP09-A3 Method Comparison Analysis (Deming regression + Bland-Altman).
    schema_mapping JSON: { "reference_column": "...", "test_column": "..." }
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        schema = json.loads(schema_mapping)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid schema_mapping JSON") from e

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    logger.info("[ep09] filename=%s  schema=%s", file.filename, schema)
    try:
        t0 = time.perf_counter()
        results = analyze_method_comparison(file_bytes, schema, file.filename)
        logger.info("[ep09] done in %.2fs  samples=%s", time.perf_counter() - t0, results.get("sample_count"))
    except ValueError as e:
        logger.error("[ep09] ValueError: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[ep09] unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"EP09 analysis failed: {e}") from e

    return results


# ─── Legacy analyze endpoint (kept for backward compatibility) ───────────────

@app.post("/api/v1/analyze")
async def analyze_excel(
    file: UploadFile = File(...),
    schema_mapping: str = Form(...),
):
    return await analyze_ep05(file=file, schema_mapping=schema_mapping)


# ─── AI Report ────────────────────────────────────────────────────────────────

@app.post("/api/v1/report")
async def create_report(request: ReportRequest):
    if request.language not in ("ko", "en"):
        raise HTTPException(status_code=400, detail="language must be 'ko' or 'en'")

    logger.info("[report] language=%s  stats_keys=%s", request.language, list(request.stats_data.keys()))
    try:
        t0 = time.perf_counter()
        report_md = generate_report(request.stats_data, request.language)
        logger.info("[report] generated in %.2fs  length=%d chars", time.perf_counter() - t0, len(report_md))
    except ValueError as e:
        logger.error("[report] ValueError: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[report] unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}") from e

    return {"language": request.language, "report_markdown": report_md}
