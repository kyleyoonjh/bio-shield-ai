"""
One-time DDL migration via Supabase Management API (HTTPS, port 443).

Direct PostgreSQL connections (psycopg2, port 5432/6543) are blocked by the
company firewall.  The Management API is the only way to run CREATE TABLE
statements without touching the Supabase web dashboard.

Prerequisites
─────────────
1. Generate a Personal Access Token (PAT) at:
       https://supabase.com/dashboard/account/tokens
2. Add to backend/.env:
       SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxxxxxxxxxxxxxx

The PAT is different from the project SUPABASE_SERVICE_ROLE_KEY.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Derived from SUPABASE_URL env var; hard-coded as a stable fallback.
_PROJECT_REF = os.getenv("SUPABASE_URL", "").rstrip("/").split(".")[-3].split("/")[-1] or "lrfaadtnloxcctooiker"
_MGMT_SQL_URL = f"https://api.supabase.com/v1/projects/{_PROJECT_REF}/database/query"

# ─── Migration SQL ─────────────────────────────────────────────────────────────

_SQL = """
CREATE TABLE IF NOT EXISTS primer_experiments (
    id                     UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at             TIMESTAMPTZ  DEFAULT now()             NOT NULL,
    -- Primer metadata (auto-populated from bio-context)
    primer_sequence        TEXT,
    primer_length          SMALLINT,
    gc_percent             NUMERIC(5,2),
    tm_celsius             NUMERIC(5,2),
    dot_bracket            TEXT,
    mfe                    NUMERIC(8,4),
    -- Variant context
    disease_type           TEXT         NOT NULL,
    variant_name           TEXT         NOT NULL DEFAULT 'wild-type',
    mismatch_count         SMALLINT     DEFAULT 0,
    three_prime_mismatch   BOOLEAN      DEFAULT false,
    -- EP05 precision stats
    grand_mean             NUMERIC(10,4),
    repeatability_cv       NUMERIC(8,4),
    reproducibility_cv     NUMERIC(8,4),
    anova_f_value          NUMERIC(12,6),
    anova_p_value          NUMERIC(12,6),
    sample_count           INTEGER,
    -- EP09 method comparison stats
    deming_slope           NUMERIC(10,6),
    bland_altman_mean_diff NUMERIC(10,6),
    pearson_r              NUMERIC(8,6),
    -- Lab context
    instrument             TEXT,
    assay_type             TEXT,
    test_date              DATE,
    guideline              TEXT,
    source_filename        TEXT,
    -- Rule-based risk classification
    risk_level             TEXT         CHECK (risk_level IN ('HIGH', 'MEDIUM', 'LOW'))
);

CREATE TABLE IF NOT EXISTS feedback_records (
    id               UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at       TIMESTAMPTZ DEFAULT now()            NOT NULL,
    experiment_id    UUID        REFERENCES primer_experiments(id) ON DELETE SET NULL,
    feedback_value   TEXT        NOT NULL
                       CHECK (feedback_value IN ('accurate', 'partially_accurate', 'incorrect')),
    guideline        TEXT,
    disease_type     TEXT,
    variant_name     TEXT
);

CREATE TABLE IF NOT EXISTS assay_jobs (
    id            UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at    TIMESTAMPTZ  DEFAULT now()             NOT NULL,
    updated_at    TIMESTAMPTZ  DEFAULT now()             NOT NULL,
    project_name  TEXT         NOT NULL,
    target_name   TEXT         NOT NULL,
    assay_type    TEXT         NOT NULL DEFAULT 'qPCR',
    status        TEXT         NOT NULL DEFAULT 'RUNNING'
                    CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    report_path   TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS assay_primers (
    id                UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at        TIMESTAMPTZ  DEFAULT now()             NOT NULL,
    assay_id          UUID         REFERENCES assay_jobs(id) ON DELETE CASCADE,
    forward_primer    TEXT         NOT NULL,
    reverse_primer    TEXT,
    probe_sequence    TEXT,
    tm                NUMERIC(6,2),
    tm_fwd            NUMERIC(5,2),
    tm_rev            NUMERIC(5,2),
    tm_probe          NUMERIC(5,2),
    probe_center_score NUMERIC(5,1),
    gc                NUMERIC(5,2),
    coverage_score    NUMERIC(6,4),
    specificity_score NUMERIC(6,4),
    thermo_score      NUMERIC(6,2),
    ai_score          NUMERIC(6,2),
    final_score       NUMERIC(8,4),
    final_rank        SMALLINT,
    product_size      INTEGER
);
"""


# ─── Public API ────────────────────────────────────────────────────────────────

def run_migration() -> dict[str, Any]:
    """
    Execute CREATE TABLE IF NOT EXISTS via the Supabase Management API.
    Safe to call multiple times (idempotent due to IF NOT EXISTS).

    Raises
    ------
    ValueError
        SUPABASE_ACCESS_TOKEN not set in .env.
    PermissionError
        Token is invalid or expired (HTTP 401).
    RuntimeError
        Unexpected API failure.
    """
    pat = os.getenv("SUPABASE_ACCESS_TOKEN", "").strip()
    if not pat:
        raise ValueError(
            "SUPABASE_ACCESS_TOKEN is not set. "
            "Go to https://supabase.com/dashboard/account/tokens, "
            "create a Personal Access Token, and add it to backend/.env as:\n"
            "  SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxxxxxxxxxxxxxx"
        )

    logger.info("[migration] Running DDL via Management API → %s", _MGMT_SQL_URL)

    try:
        with httpx.Client(verify=False, timeout=30.0) as client:
            resp = client.post(
                _MGMT_SQL_URL,
                headers={
                    "Authorization": f"Bearer {pat}",
                    "Content-Type":  "application/json",
                },
                json={"query": _SQL},
            )
    except Exception as exc:
        raise RuntimeError(f"HTTP request to Management API failed: {exc}") from exc

    if resp.status_code == 401:
        raise PermissionError(
            "Management API returned 401 — SUPABASE_ACCESS_TOKEN is invalid or expired."
        )
    if not resp.ok:
        raise RuntimeError(
            f"Management API returned HTTP {resp.status_code}: {resp.text[:400]}"
        )

    logger.info("[migration] DDL executed successfully (status %d)", resp.status_code)
    return {
        "status":  "ok",
        "message": "Tables created (primer_experiments, feedback_records, assay_jobs, assay_primers)",
        "project": _PROJECT_REF,
    }


def check_token_configured() -> bool:
    """Return True if SUPABASE_ACCESS_TOKEN is present in environment."""
    return bool(os.getenv("SUPABASE_ACCESS_TOKEN", "").strip())
