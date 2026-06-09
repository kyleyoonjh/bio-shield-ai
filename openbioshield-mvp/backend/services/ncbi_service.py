"""NCBI E-utilities integration + primer3-py for real bioinformatics data."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

try:
    import primer3
    _PRIMER3_AVAILABLE = True
except ImportError:
    _PRIMER3_AVAILABLE = False

try:
    import RNA as _RNA
    _VIENNARNA_AVAILABLE = True
except ImportError:
    _VIENNARNA_AVAILABLE = False

NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
NCBI_TOOL      = "OpenBioShield"
NCBI_EMAIL     = os.getenv("NCBI_EMAIL", "research@openbioshield.ai")
NCBI_API_KEY   = os.getenv("NCBI_API_KEY", "")
NCBI_MAX_TRIES = 2   # consecutive failures before falling back to cache

# SSL verification: disabled by default to work through corporate HTTPS proxies.
# Set NCBI_VERIFY_SSL=true in .env to re-enable strict verification.
NCBI_VERIFY_SSL = os.getenv("NCBI_VERIFY_SSL", "false").lower() == "true"

# Cache directory (backend/cache/)
_CACHE_DIR = pathlib.Path(__file__).parent.parent / "cache"

# ─── Static Fallback Sequences ────────────────────────────────────────────────
# Used when NCBI E-utilities is unreachable. Sequences are representative of
# each target region but are NOT guaranteed to match the reference exactly.
# A "source":"fallback" flag is returned so the UI can show a warning.

_FALLBACK_SEQS: dict[str, str] = {
    "SARS-CoV-2": (
        "CAATGTTGTTTGTGGACGAATGGTGAAATGGTCATGTGTGGCGGTTCACTATATGTTAAAC"
        "CAGGTGGAACCTCATCAGGAGATGCCACAACTGCTTATGCTAATAGTGTTTTTAACATTTG"
        "TCAAGCTGTCACGGCCAATGTGAATGCACTTGGTGTTGAGAATCAGTGTCGTGATGCAGAG"
        "CATTTGTTTTTGGCTAACTTTAACATCAAATTCCAGTTCTGGAAGTTCATGCCACATGGTGT"
        "TTGTTTTGTAAGTTGAAGAATCTTTGGGGATTTAAAATCTTTTTTATAAGGATCCTTATATG"
        "GACATTCAAGAAGGCAAATTACATTTTACTAATCCAATTGGAATTCACCTCAAGCATGGCTT"
        "GGTTTGAAACCATCAGATAAAGTTATTGAATTTGAATTAACCAATGCTGGGTACAATGACAT"
        "CCCTAGTAAATTTGGCAATAAATGGGCAAATCGTCCTTTGGCAAATGATCAAATCAATGTTT"
        "GTGGTTTAAAGCTTCTATCCTTTTTAATGAATCCATTTCAATCATTGCTTTTGTTGCACTTG"
        "ATCCTTCAATTCTTTTTTTTCTCCCTTCGTGTTTGCAGCAAATGTTTATGTCTGCTTTGCAT"
    ),
    "HPV": (
        "CGAAACCGAAGTCAAAGACACTATAATACACATGTTAATGTATGCACTAGATCGGGGCGTATA"
        "TATAAGCAAAGCATGTATTATCTGCCATTATATATGTCCTATTCTTTCTTTGAAAAAATAAATA"
        "TAGGATATATTTTACTCATATGAAAATACCATGCTGTGTGTCCATGCACAATCTCCTTTTGCTG"
        "ATCCAGCTTTTGGCTTCATGCGAGCACGCTCTCCAAGAAGCCCTAAATACACATTTCTGCAAAG"
        "CAAGTTAAAAAACAAGGAGCACCCAGAAGTAAGACGATACATCAACATAACAGAGAAACAACCCA"
        "TGCAAATAAACAGATGCCAGTGGCAAATGCAAATCACTGCACAGCATACGGCGACGATCGTTGA"
    ),
    "STI": (
        "GCTGAAGAGCAAAGCATGGGTCAAGTGTCATCAAGTCTGCTTCTGCAACTTCAGCAACTTCTCC"
        "AGCATCTCCAGCCTCTCCAGCTTCTCAAGCTAGTACAGGAGAAACTCAACCTGCTCCAGCACCT"
        "AATGCAGAAACTCCAGCACCACCAGCACAACCTACTGCAGAAACTCAAGCTCCACCAGCACCAAC"
        "TGCAAATACTCAAGCTCCTCCAGCACCAGCAGCTACTCCAGCAATGCAAACTCCAGCAACTGCAG"
        "CTCCTCAAGTGGCTCCAGCAGCAACCGCAGAGGCACTTCAAGTGGCTCAAGCAGCTCCAGCAGCA"
        "GCTACTGCTCCTCCAGCAGCAGCAACTGCTGCTGCACAAGCAGCAACAGCAGCTCCTGGAGCTGC"
        "TAGTGCAGCTCCAGCAGCATCTGTGGCATCAGCTGCTGCACAATCACCAGCAGCAGCTGCTCAAGT"
        "GACAGCACCAGCATCTGCAGCAGCAGCAGCTGCTGCAGCAACTCAAGATGCAGCTGCTGCAGCAAG"
    ),
}

# ─── Disease Target Configurations ───────────────────────────────────────────
# Primer coordinates are 1-based absolute positions in the reference genome.
# The fetch window (seq_start / seq_stop) defines the region pulled from NCBI.
# Relative annotation positions are computed at runtime: rel = abs_start - seq_start

DISEASE_TARGETS: dict[str, dict[str, Any]] = {
    "SARS-CoV-2": {
        "accession": "NC_045512.2",
        "gene": "RdRp (nsp12)",
        "organism": "SARS-CoV-2",
        "assay_type": "RT-qPCR",
        "standard": "WHO EUL 09.232.01",
        "seq_start": 15400,
        "seq_stop": 16000,
        "primers": [
            {
                "name": "RdRp_Fwd",
                "sequence": "GTGARATGGTCATGTGTGGCGG",
                "abs_start": 15431,
                "color": "#4CAF50",
                "strand": 1,
            },
            {
                "name": "RdRp_Probe",
                "sequence": "CAGGTGGAACCTCATCAGGAGATGC",
                "abs_start": 15460,
                "color": "#FF9800",
                "strand": 1,
            },
            {
                "name": "RdRp_Rev",
                "sequence": "CARATGTTAAASACACTATTAGCATA",
                "abs_start": 15506,
                "color": "#2196F3",
                "strand": -1,
            },
        ],
    },
    "HPV": {
        "accession": "NC_001526.4",
        "gene": "E7 Oncogene",
        "organism": "Human Papillomavirus Type 16",
        "assay_type": "PCR",
        "standard": "CLSI EP05-A3",
        "seq_start": 540,
        "seq_stop": 900,
        "primers": [
            {
                "name": "E7_Fwd",
                "sequence": "CGAAACCGAAGTCAAAGACAC",
                "abs_start": 562,
                "color": "#4CAF50",
                "strand": 1,
            },
            {
                "name": "E7_Probe",
                "sequence": "TGTGGAATGTGTGTCAGTTTTGTC",
                "abs_start": 600,
                "color": "#FF9800",
                "strand": 1,
            },
            {
                "name": "E7_Rev",
                "sequence": "GCAGTGCTGCATTTCTGTTTC",
                "abs_start": 820,
                "color": "#2196F3",
                "strand": -1,
            },
        ],
    },
    "STI": {
        "accession": "AE001273.1",
        "gene": "ompA (MOMP)",
        "organism": "Chlamydia trachomatis D/UW-3",
        "assay_type": "RT-qPCR",
        "standard": "CLSI EP05-A3",
        "seq_start": 400,
        "seq_stop": 900,
        "primers": [
            {
                "name": "ompA_Fwd",
                "sequence": "GCTGAAGAGCAAAGCATGGGT",
                "abs_start": 410,
                "color": "#4CAF50",
                "strand": 1,
            },
            {
                "name": "ompA_Probe",
                "sequence": "TGCAAGCTGCAGAATTTGCCGGA",
                "abs_start": 448,
                "color": "#FF9800",
                "strand": 1,
            },
            {
                "name": "ompA_Rev",
                "sequence": "GAAACGAGCTTCCTGCTTGAG",
                "abs_start": 680,
                "color": "#2196F3",
                "strand": -1,
            },
        ],
    },
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_fasta(text: str) -> str:
    """Strip FASTA header line(s) and return upper-case sequence."""
    lines = text.strip().splitlines()
    return "".join(ln for ln in lines if not ln.startswith(">")).upper()


def _gc_percent(seq: str) -> float:
    clean = re.sub(r"[^ACGT]", "", seq.upper())
    if not clean:
        return 0.0
    return round((clean.count("G") + clean.count("C")) / len(clean) * 100, 2)


def _calc_tm(sequence: str) -> float | None:
    """Return melting temperature via primer3-py, or None if unavailable."""
    if not _PRIMER3_AVAILABLE:
        return None
    clean = re.sub(r"[^ACGT]", "A", sequence.upper())
    try:
        return round(float(primer3.calc_tm(clean)), 1)
    except Exception:
        return None


def _fold_sequence(sequence: str) -> tuple[str | None, float | None]:
    """Return (dot_bracket, mfe_kcal) via ViennaRNA, or (None, None)."""
    if not _VIENNARNA_AVAILABLE:
        return None, None
    # Replace IUPAC ambiguous bases; ViennaRNA accepts DNA directly
    clean = re.sub(r"[^ACGT]", "A", sequence.upper())
    try:
        structure, mfe = _RNA.fold(clean)
        return structure, round(float(mfe), 2)
    except Exception:
        return None, None


# ─── Main Public Function ─────────────────────────────────────────────────────

def _build_response(
    disease_type: str,
    config: dict[str, Any],
    raw_sequence: str,
    source: str,
) -> dict[str, Any]:
    """Assemble the BioContext response dict from a fetched or fallback sequence."""
    seq_start = config["seq_start"]
    fwd = config["primers"][0]
    fwd_seq = fwd["sequence"]

    annotations: list[dict[str, Any]] = []
    for p in config["primers"]:
        rel_start = p["abs_start"] - seq_start
        rel_end   = rel_start + len(p["sequence"])
        if 0 <= rel_start < len(raw_sequence) and rel_end <= len(raw_sequence):
            annotations.append({
                "name":   p["name"],
                "start":  rel_start,
                "end":    rel_end,
                "color":  p["color"],
                "strand": p["strand"],
            })

    dot_bracket, mfe = _fold_sequence(fwd_seq)

    return {
        "disease_type": disease_type,
        "accession":    config["accession"],
        "rdrp_sequence": raw_sequence,
        "seq_start":     config["seq_start"],   # absolute genomic start of rdrp_sequence[0]
        "annotations":   annotations,
        "primer_structure": {
            "sequence":    fwd_seq,
            "length":      len(fwd_seq),
            "abs_start":   fwd["abs_start"],    # absolute genomic start of the forward primer
            "tm_celsius":  _calc_tm(fwd_seq),
            "gc_percent":  _gc_percent(fwd_seq),
            "dot_bracket": dot_bracket,
            "mfe":         mfe,
        },
        "assay_info": {
            "target_gene": config["gene"],
            "organism":    config["organism"],
            "assay_type":  config["assay_type"],
            "standard":    config["standard"],
            "accession":   config["accession"],
        },
        "source": source,  # "ncbi" | "fallback"
    }


# ─── Disk Cache ───────────────────────────────────────────────────────────────

def _cache_path(disease_type: str) -> pathlib.Path:
    safe = disease_type.replace("/", "_").replace(" ", "_")
    return _CACHE_DIR / f"{safe}.json"


def _save_cache(disease_type: str, data: dict[str, Any]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(disease_type).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Saved NCBI cache → %s", _cache_path(disease_type))
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", disease_type, e)


def _load_cache(disease_type: str) -> dict[str, Any] | None:
    p = _cache_path(disease_type)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        logger.info("Loaded cache for %s from %s", disease_type, p)
        return data
    except Exception as e:
        logger.warning("Cache load failed for %s: %s", disease_type, e)
        return None


# ─── Main Fetch Function ──────────────────────────────────────────────────────

async def fetch_bio_context(disease_type: str) -> dict[str, Any]:
    """
    Fetch genome context for the given disease type.
    Strategy:
      1. Try NCBI E-utilities (up to NCBI_MAX_TRIES attempts, SSL verify off for corporate proxies).
      2. On success → save result to disk cache, return with source="ncbi".
      3. On NCBI_MAX_TRIES failures → load from disk cache (source="cache").
      4. No cache → hardcoded representative sequences (source="fallback").
    """
    config = DISEASE_TARGETS.get(disease_type)
    if not config:
        raise ValueError(
            f"Unsupported disease type: {disease_type!r}. "
            f"Valid options: {list(DISEASE_TARGETS)}"
        )

    accession = config["accession"]
    params: dict[str, Any] = {
        "db":        "nuccore",
        "id":        accession,
        "rettype":   "fasta",
        "retmode":   "text",
        "seq_start": config["seq_start"],
        "seq_stop":  config["seq_stop"],
        "tool":      NCBI_TOOL,
        "email":     NCBI_EMAIL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    # ── 1. Try NCBI (up to NCBI_MAX_TRIES) ───────────────────────────────
    last_exc: Exception | None = None
    for attempt in range(1, NCBI_MAX_TRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=NCBI_VERIFY_SSL) as client:
                resp = await client.get(NCBI_EFETCH_URL, params=params)
                resp.raise_for_status()
            raw_seq = _parse_fasta(resp.text)
            if not raw_seq:
                raise ValueError("NCBI returned empty FASTA")

            result = _build_response(disease_type, config, raw_seq, source="ncbi")
            _save_cache(disease_type, result)   # ── 2. persist on success
            logger.info("NCBI fetch OK for %s (attempt %d)", accession, attempt)
            return result

        except Exception as exc:
            last_exc = exc
            logger.warning(
                "NCBI fetch attempt %d/%d failed for %s: %s",
                attempt, NCBI_MAX_TRIES, accession, exc,
            )

    # ── 3. Load from disk cache ───────────────────────────────────────────
    cached = _load_cache(disease_type)
    if cached is not None:
        cached["source"] = "cache"
        logger.info("Serving cached data for %s", disease_type)
        return cached

    # ── 4. Hardcoded fallback ─────────────────────────────────────────────
    logger.warning("No cache for %s — serving built-in fallback", disease_type)
    return _build_response(disease_type, config, _FALLBACK_SEQS[disease_type], source="fallback")
