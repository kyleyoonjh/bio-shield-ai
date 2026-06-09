"""Supabase CRUD operations for Phase 2 data collection."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ─── Company firewall / SSL workaround ───────────────────────────────────────
# Set SUPABASE_SSL_VERIFY=false in .env to bypass SSL certificate validation.
# Patches ssl.create_default_context so httpx (and all libraries) skip verification.
# This approach survives "from httpx import Client" captures at import time.
if os.getenv("SUPABASE_SSL_VERIFY", "true").lower() in ("false", "0", "no"):
    import ssl as _ssl
    try:
        import urllib3  # type: ignore
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    _orig_ctx = _ssl.create_default_context

    def _insecure_ctx(*args: Any, **kwargs: Any) -> _ssl.SSLContext:
        ctx = _orig_ctx(*args, **kwargs)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return ctx

    _ssl.create_default_context = _insecure_ctx  # type: ignore[assignment]
    logger.warning("[supabase] SSL verification disabled via ssl.create_default_context patch (SUPABASE_SSL_VERIFY=false)")

# ─── Client singleton ─────────────────────────────────────────────────────────

try:
    from supabase import create_client, Client  # type: ignore

    _client: "Client | None" = None

    def _get_client() -> "Client":
        global _client
        if _client is None:
            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
            if not url or not key:
                raise ValueError(
                    "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
                )
            _client = create_client(url, key)
            logger.info("[supabase] client initialised → %s", url.split(".")[0])
        return _client

    _SUPABASE_AVAILABLE = True

except ImportError:
    _SUPABASE_AVAILABLE = False
    logger.warning("[supabase] supabase package not installed — data collection disabled")


# ─── Public API ───────────────────────────────────────────────────────────────

def insert_experiment(payload: dict[str, Any]) -> dict[str, Any]:
    if not _SUPABASE_AVAILABLE:
        raise RuntimeError("supabase package not installed")
    client = _get_client()
    logger.info(
        "[supabase] insert_experiment disease=%s variant=%s risk=%s",
        payload.get("disease_type"),
        payload.get("variant_name"),
        payload.get("risk_level"),
    )
    response = client.table("primer_experiments").insert(payload).execute()
    if not response.data:
        raise ValueError("Supabase insert returned no data")
    return response.data[0]


def insert_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    if not _SUPABASE_AVAILABLE:
        raise RuntimeError("supabase package not installed")
    client = _get_client()
    logger.info(
        "[supabase] insert_feedback value=%s experiment_id=%s",
        payload.get("feedback_value"),
        payload.get("experiment_id"),
    )
    response = client.table("feedback_records").insert(payload).execute()
    if not response.data:
        raise ValueError("Supabase insert returned no data")
    return response.data[0]


def get_dataset_stats() -> dict[str, Any]:
    if not _SUPABASE_AVAILABLE:
        raise RuntimeError("supabase package not installed")
    client = _get_client()

    # Total count
    total_res = (
        client.table("primer_experiments").select("id", count="exact").execute()
    )
    total: int = total_res.count or 0

    # By disease
    by_disease: dict[str, int] = {}
    for d in ("SARS-CoV-2", "HPV", "STI"):
        r = (
            client.table("primer_experiments")
            .select("id", count="exact")
            .eq("disease_type", d)
            .execute()
        )
        by_disease[d] = r.count or 0

    # By risk level
    by_risk: dict[str, int] = {}
    for level in ("HIGH", "MEDIUM", "LOW"):
        r = (
            client.table("primer_experiments")
            .select("id", count="exact")
            .eq("risk_level", level)
            .execute()
        )
        by_risk[level] = r.count or 0

    # By guideline
    by_guideline: dict[str, int] = {}
    for g in ("EP05", "EP09"):
        r = (
            client.table("primer_experiments")
            .select("id", count="exact")
            .eq("guideline", g)
            .execute()
        )
        by_guideline[g] = r.count or 0

    # Recent 30 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    r30 = (
        client.table("primer_experiments")
        .select("id", count="exact")
        .gte("created_at", cutoff)
        .execute()
    )
    recent_30d: int = r30.count or 0

    threshold = 5000
    readiness = round(min(total / threshold * 100, 100), 1) if total > 0 else 0.0

    logger.info("[supabase] dataset_stats total=%d readiness=%.1f%%", total, readiness)
    return {
        "total_records": total,
        "fine_tuning_threshold": threshold,
        "readiness_percent": readiness,
        "is_ready": total >= threshold,
        "by_disease": by_disease,
        "by_risk": by_risk,
        "by_guideline": by_guideline,
        "recent_30d": recent_30d,
    }
