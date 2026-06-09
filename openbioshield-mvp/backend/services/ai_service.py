"""OpenAI integration for schema mapping and clinical report generation."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAY = 1.5  # seconds


def _call_with_retry(fn, *args, **kwargs):
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = fn(*args, **kwargs)
            if attempt > 0:
                logger.info("[ai] retry succeeded on attempt %d", attempt + 1)
            return result
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                logger.warning("[ai] attempt %d failed: %s — retrying in %.1fs", attempt + 1, e, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            else:
                logger.error("[ai] all %d attempts failed. last error: %s", _MAX_RETRIES + 1, e)
    raise last_err

SCHEMA_SYSTEM_PROMPT = """You are a bioinformatics data schema mapper for clinical precision validation studies.
Analyze the provided Excel column metadata and return ONLY a valid JSON object with this exact structure:
{
  "target_column": "<column name containing numeric Ct/measurement values>",
  "group_columns": ["<column1>", "<column2>"]
}

Rules:
- target_column must be the numeric measurement column (e.g., Ct values for qPCR)
- group_columns are categorical grouping variables (e.g., day, machine, lot)
- Use exact column names from the metadata
- Return ONLY JSON, no markdown, no explanation"""

REPORT_SYSTEM_PROMPT = """You are a clinical R&D report writer for SARS-CoV-2 (COVID-19) RdRp gene assay precision validation.
You will receive pre-computed statistical results from a Python stats engine.
Your job is to write a professional interpretation report in the requested language.

CRITICAL RULES:
- NEVER recalculate or modify any numbers. Quote the provided values exactly.
- Reference CLSI EP05-A3 precision study context
- Include sections: Summary, Repeatability, Reproducibility, ANOVA Results, Clinical Interpretation, Recommendations
- Use markdown formatting
- Be concise but thorough"""


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key)


def _get_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


EP09_SCHEMA_SYSTEM_PROMPT = """You are a bioinformatics data schema mapper for CLSI EP09-A3 method comparison studies.
Analyze the provided Excel column metadata and return ONLY a valid JSON object with this exact structure:
{
  "reference_column": "<column name containing established/comparator method values>",
  "test_column": "<column name containing new/candidate method (CFX96) values>"
}

Rules:
- reference_column: the gold-standard or previously validated method
- test_column: the new instrument or method under evaluation
- Use exact column names from the metadata
- Return ONLY JSON, no markdown, no explanation"""


def map_schema(metadata: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to map Excel columns to target and group columns."""
    logger.info("[map_schema] EP05 schema mapping — %d columns", metadata.get("column_count", 0))
    client = _get_client()
    user_content = json.dumps(metadata, ensure_ascii=False, indent=2)

    def _call():
        return client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": SCHEMA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

    response = _call_with_retry(_call)
    result = _parse_json_response(response.choices[0].message.content or "{}")
    if "target_column" not in result:
        raise ValueError("AI response missing target_column")
    if "group_columns" not in result:
        result["group_columns"] = []
    logger.info("[map_schema] result: target=%s  groups=%s", result.get("target_column"), result.get("group_columns"))
    return result


def map_schema_ep09(metadata: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to identify reference_column and test_column for EP09."""
    logger.info("[map_schema_ep09] EP09 schema mapping — %d columns", metadata.get("column_count", 0))
    client = _get_client()
    user_content = json.dumps(metadata, ensure_ascii=False, indent=2)

    def _call():
        return client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": EP09_SCHEMA_SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

    response = _call_with_retry(_call)
    result = _parse_json_response(response.choices[0].message.content or "{}")
    if "reference_column" not in result or "test_column" not in result:
        raise ValueError("AI response missing reference_column or test_column")
    logger.info("[map_schema_ep09] result: ref=%s  test=%s", result.get("reference_column"), result.get("test_column"))
    return result


def generate_report(stats_data: dict[str, Any], language: str = "ko") -> str:
    """Generate clinical interpretation report from pre-computed stats."""
    logger.info("[generate_report] language=%s  stats_keys=%s", language, list(stats_data.keys()))
    client = _get_client()
    lang_label = "Korean (한국어)" if language == "ko" else "English"

    user_content = (
        f"Write the report in {lang_label}.\n\n"
        f"Pre-computed statistical results (DO NOT recalculate):\n"
        f"{json.dumps(stats_data, ensure_ascii=False, indent=2)}"
    )

    def _call():
        return client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
        )

    response = _call_with_retry(_call)
    content = response.choices[0].message.content or ""
    logger.info("[generate_report] done  length=%d chars", len(content))
    return content
