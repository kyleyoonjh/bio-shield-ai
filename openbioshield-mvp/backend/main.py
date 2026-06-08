"""FastAPI entrypoint for OpenBioShield MVP."""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.ai_service import generate_report, map_schema
from services.stats_engine import analyze_precision, extract_excel_metadata

load_dotenv()

app = FastAPI(
    title="OpenBioShield API",
    description="SARS-CoV-2 RdRp assay precision validation platform",
    version="1.0.0",
)

cors_origins = os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SARS-CoV-2 RdRp target region (WHO E-gene/RdRp assay region fragment)
RDRP_SEQUENCE = (
    "AAATTTTGGGGACCAGGAACAAATTACAATACAGAGCAGTAAACAATTTAGAAAAAAGGATACCCAGCCC"
    "ATTCACGTTTAAGACATTTGAAATTTTGGCTACACTGGAAAGTGCCTTTCCGTGTGACTTTTCCATTAT"
    "GTAGTGCTGATGCAATTACAACAGGCAGCATGCATATGTACATATGAGGTTGAAAAGAACAGAAACAGT"
    "ACCTTTAAAGAAAACCCTCAGTACAAAGAAATAGTACAGGAGACAACAATTCTTTAAACAGGTTAAGAGG"
    "AACCTTTATAGAGGCAGAATCAATGAGGAAAGCAGGTAAATAGGAGAAATTACTTCTTATTTACTGCTG"
    "TAACACTTGCTCAGTAACATTTTGTAATCAGAGGTTCAATTGCTCATCTGAAATCACATGTCTTATCAGA"
    "TTCTTTCCCCCCATGACCAGATAGGGATAATGCAACAATGTCTGCCAACTGGCACACACTTTGTAGATG"
    "TCATGCTGGATGCTGACCTTTTTGCGAGAGTGTTTTGATCCTGGCTCACTGCTGCTTCGCAGTCAATATG"
    "GCTGTCAATGTTGCAATTCACTTGTGTAGCTGATCATCAAATGTACGGTGGATGCCTCATGTGTGGCAT"
    "ATACACAAATGGAAAAGTGCTTTTCTGTGCTCATTCAATTATGCAGATGATAATCATTTTCAACAATATA"
    "CTTATATCACTGGCAGCTGTAGACATGGTGACAATTGTGGCCACTTACACTTTGAAGATGTGTGTGCATC"
    "AAAGGTAATTTTGGGGTACCTGTTCTGTTATAAACAATGTTCTTAAACACACCAATTTTGTGCGCATCTT"
    "GTTCTTGCTCGCAAAGTATTAAGACACACTAACTTTCCGATCCATCACAGATGCTGTTACTACGAAAGAA"
    "CTCTTCACTACCAGGTGTGATTGTTGTGGCAGTGCAGAGTGACATGCAGCTCGTAGCTGATGCAATGCTT"
    "CAGGATGAGGCTTTCTATGCAGAATGTGACATATCAGGAGCAGGCAGAGATGCTATGGTGCGGCTCCCT"
    "AGTTTGATGCAGGCTTAGCCAATGGTGATGCACTTGGCATGGGATGAGCTGATTAAATTAACTGCTGCT"
    "GATAAGCTGCAGGTGGCTCTCCAGGAAGCCATGAATGTTCTGACTGAGCTGAGGTTTGATGCTGCAGGTG"
    "CAGAGTGGAGATTTACTTTGATAACGAGCAGGCTGTAGCTTCTGGCTTAGTAAAGAACCTGCAGCCTTGT"
    "GCTGATGGGTGCTACTAGAGTGCTGGGATTACAGGCGTGAGCCACCGTGCTCGGCCTAGCATTTGCTTTT"
    "ACAGATGCAATACATAACAAGCGGCTGTTAAATAGAGCCAGCAGCATATAATTGCAGGAGTGCACACCCA"
    "AGACGTGTAGCAGAAGAAGTCGTTGAACAGGGTCTTTATGAGGGAGCTGTATCTGCAAAGGAATAGGTAG"
    "ATGAAGTGGTGATGGCAGGAGTCAGAAAAAGAGCCAAAAAAGGCTATGGCAGCGGCGGCGGAGCGGCGGC"
    "GGCAGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCG"
)

BIO_CONTEXT = {
    "rdrp_sequence": RDRP_SEQUENCE[:300],
    "annotations": [
        {"name": "Forward_Primer", "start": 45, "end": 64, "color": "#4CAF50", "strand": 1},
        {"name": "Probe", "start": 72, "end": 95, "color": "#FF9800", "strand": 1},
        {"name": "Reverse_Primer", "start": 120, "end": 140, "color": "#2196F3", "strand": -1},
    ],
    "primer_structure": {
        "sequence": "AAATTTTGGGGACCAGGAACAA",
        "dot_bracket": "((((...))))((((...))))",
        "melting_temp_c": 60.0,
        "delta_g_kcal": -1.2,
        "gc_percent": 45.5,
        "length": 22,
    },
    "assay_info": {
        "target_gene": "RdRp",
        "organism": "SARS-CoV-2",
        "assay_type": "qPCR",
        "standard": "CLSI EP05-A3",
    },
}


class ReportRequest(BaseModel):
    stats_data: dict[str, Any]
    language: str = "ko"


class AnalyzeRequest(BaseModel):
    schema_mapping: dict[str, Any]


@app.get("/")
def root():
    return {
        "service": "OpenBioShield API",
        "message": "Use the frontend at http://localhost:5173",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": "OpenBioShield"}


@app.get("/api/v1/bio-context")
def get_bio_context():
    return BIO_CONTEXT


@app.post("/api/v1/upload")
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    allowed = {".xlsx", ".xls", ".csv"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        metadata = extract_excel_metadata(file_bytes, file.filename)
        schema_mapping = map_schema(metadata)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schema mapping failed: {e}") from e

    return {
        "metadata": metadata,
        "schema_mapping": schema_mapping,
    }


@app.post("/api/v1/analyze")
async def analyze_excel(
    file: UploadFile = File(...),
    schema_mapping: str = Form(...),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        schema = json.loads(schema_mapping)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid schema_mapping JSON") from e

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        results = analyze_precision(file_bytes, schema, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}") from e

    return results


@app.post("/api/v1/report")
async def create_report(request: ReportRequest):
    if request.language not in ("ko", "en"):
        raise HTTPException(status_code=400, detail="language must be 'ko' or 'en'")

    try:
        report_md = generate_report(request.stats_data, request.language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}") from e

    return {
        "language": request.language,
        "report_markdown": report_md,
    }
