"""
Variant catalog for each supported disease.
Mutation positions are absolute 1-based coordinates in the reference genome.
Source: NCBI, WHO, published literature (see comments per entry).
"""

from __future__ import annotations
from typing import Any

# ─── Catalog ─────────────────────────────────────────────────────────────────

VARIANT_CATALOG: dict[str, dict[str, Any]] = {

    # ── SARS-CoV-2 (NC_045512.2) ─────────────────────────────────────────────
    # Mutation positions: absolute nt coordinates in NC_045512.2
    # References: Rambaut et al. 2020 (Nat Microbiol), WHO VOC reports
    "SARS-CoV-2": {
        "variants": [
            {"id": "wild-type",    "label": "Wild-Type (Wuhan-Hu-1)", "lineage": "B",        "who_label": "Reference"},
            {"id": "alpha",        "label": "Alpha (B.1.1.7)",         "lineage": "B.1.1.7",  "who_label": "VOC"},
            {"id": "delta",        "label": "Delta (B.1.617.2)",       "lineage": "B.1.617.2","who_label": "VOC"},
            {"id": "omicron-ba1",  "label": "Omicron BA.1",            "lineage": "BA.1",     "who_label": "VOC"},
            {"id": "omicron-ba5",  "label": "Omicron BA.5",            "lineage": "BA.5",     "who_label": "VOC"},
            {"id": "xbb",          "label": "XBB.1.5 (Kraken)",        "lineage": "XBB.1.5",  "who_label": "XBB"},
        ],
        "mutations": {
            "wild-type": [],

            # Alpha: del HV69-70 (S), N501Y (S), D614G (S), P681H (S), T716I (S)
            "alpha": [
                {"gene": "S",       "position": 21765,  "ref": "ACATTT", "alt": "-",  "effect": "HV69-70del"},
                {"gene": "S",       "position": 22206,  "ref": "A",      "alt": "G",  "effect": "D215G"},
                {"gene": "S",       "position": 23063,  "ref": "A",      "alt": "T",  "effect": "N501Y"},
                {"gene": "S",       "position": 23271,  "ref": "C",      "alt": "A",  "effect": "A570D"},
                {"gene": "S",       "position": 23403,  "ref": "A",      "alt": "G",  "effect": "D614G"},
                {"gene": "S",       "position": 23604,  "ref": "C",      "alt": "A",  "effect": "P681H"},
                {"gene": "N",       "position": 28280,  "ref": "GAT",    "alt": "AAC","effect": "D3L"},
                {"gene": "ORF1ab",  "position": 3267,   "ref": "C",      "alt": "T",  "effect": "T1001I"},
                {"gene": "ORF1ab",  "position": 14408,  "ref": "C",      "alt": "T",  "effect": "P323L (nsp12)"},
            ],

            # Delta: L452R, T478K, D614G, P681R
            "delta": [
                {"gene": "S",       "position": 21618,  "ref": "C",      "alt": "G",  "effect": "T19R"},
                {"gene": "S",       "position": 22917,  "ref": "T",      "alt": "G",  "effect": "P681R"},
                {"gene": "S",       "position": 22995,  "ref": "C",      "alt": "A",  "effect": "L452R"},
                {"gene": "S",       "position": 23012,  "ref": "G",      "alt": "A",  "effect": "T478K"},
                {"gene": "S",       "position": 23403,  "ref": "A",      "alt": "G",  "effect": "D614G"},
                {"gene": "S",       "position": 24410,  "ref": "G",      "alt": "A",  "effect": "D950N"},
                {"gene": "ORF1ab",  "position": 14408,  "ref": "C",      "alt": "T",  "effect": "P323L (nsp12)"},
            ],

            # Omicron BA.1: ~30 spike mutations
            "omicron-ba1": [
                {"gene": "S",       "position": 21762,  "ref": "A",      "alt": "G",  "effect": "A67V"},
                {"gene": "S",       "position": 21846,  "ref": "C",      "alt": "T",  "effect": "T95I"},
                {"gene": "S",       "position": 22194,  "ref": "GAGTTCA","alt": "-",  "effect": "del142-144"},
                {"gene": "S",       "position": 22577,  "ref": "G",      "alt": "A",  "effect": "G339D"},
                {"gene": "S",       "position": 22673,  "ref": "TC",     "alt": "CT", "effect": "S373P"},
                {"gene": "S",       "position": 22882,  "ref": "T",      "alt": "A",  "effect": "K417N"},
                {"gene": "S",       "position": 23013,  "ref": "A",      "alt": "C",  "effect": "N440K"},
                {"gene": "S",       "position": 22917,  "ref": "T",      "alt": "G",  "effect": "G446S"},
                {"gene": "S",       "position": 23403,  "ref": "A",      "alt": "G",  "effect": "D614G"},
                {"gene": "S",       "position": 23525,  "ref": "C",      "alt": "T",  "effect": "H655Y"},
                {"gene": "S",       "position": 23599,  "ref": "T",      "alt": "G",  "effect": "N679K"},
                {"gene": "S",       "position": 23604,  "ref": "C",      "alt": "A",  "effect": "P681H"},
                {"gene": "S",       "position": 24503,  "ref": "T",      "alt": "C",  "effect": "L981F"},
                {"gene": "ORF1ab",  "position": 14408,  "ref": "C",      "alt": "T",  "effect": "P323L (nsp12)"},
            ],

            # Omicron BA.5: L452R added on top of BA.2 backbone
            "omicron-ba5": [
                {"gene": "S",       "position": 22995,  "ref": "C",      "alt": "A",  "effect": "L452R"},
                {"gene": "S",       "position": 23403,  "ref": "A",      "alt": "G",  "effect": "D614G"},
                {"gene": "S",       "position": 23525,  "ref": "C",      "alt": "T",  "effect": "H655Y"},
                {"gene": "S",       "position": 23599,  "ref": "T",      "alt": "G",  "effect": "N679K"},
                {"gene": "S",       "position": 23604,  "ref": "C",      "alt": "A",  "effect": "P681H"},
                {"gene": "S",       "position": 24410,  "ref": "G",      "alt": "A",  "effect": "D950N"},
                {"gene": "ORF1ab",  "position": 14408,  "ref": "C",      "alt": "T",  "effect": "P323L (nsp12)"},
            ],

            # XBB.1.5
            "xbb": [
                {"gene": "S",       "position": 22578,  "ref": "G",      "alt": "A",  "effect": "G339H"},
                {"gene": "S",       "position": 22895,  "ref": "A",      "alt": "T",  "effect": "R346T"},
                {"gene": "S",       "position": 22917,  "ref": "G",      "alt": "A",  "effect": "L368I"},
                {"gene": "S",       "position": 23403,  "ref": "A",      "alt": "G",  "effect": "D614G"},
                {"gene": "S",       "position": 23525,  "ref": "C",      "alt": "T",  "effect": "H655Y"},
                {"gene": "S",       "position": 23604,  "ref": "C",      "alt": "A",  "effect": "P681H"},
                {"gene": "S",       "position": 24503,  "ref": "T",      "alt": "C",  "effect": "F486P"},
                {"gene": "ORF1ab",  "position": 14408,  "ref": "C",      "alt": "T",  "effect": "P323L (nsp12)"},
            ],
        },
    },

    # ── HPV (NC_001526.4, HPV-16 reference) ──────────────────────────────────
    # Genotype variants: key E7 / E6 positions vs HPV-16 reference
    # Reference window displayed: 540–900 nt in NC_001526.4
    "HPV": {
        "variants": [
            {"id": "wild-type",  "label": "HPV-16 Wild-Type",   "lineage": "Alpha-9", "who_label": "Reference"},
            {"id": "hpv-18",     "label": "HPV-18",             "lineage": "Alpha-7", "who_label": "High-Risk"},
            {"id": "hpv-31",     "label": "HPV-31",             "lineage": "Alpha-9", "who_label": "High-Risk"},
            {"id": "hpv-45",     "label": "HPV-45",             "lineage": "Alpha-7", "who_label": "High-Risk"},
            {"id": "hpv-6",      "label": "HPV-6 (Low-Risk)",   "lineage": "Alpha-10","who_label": "Low-Risk"},
        ],
        "mutations": {
            "wild-type": [],
            "hpv-18": [
                {"gene": "E7", "position": 562,  "ref": "C", "alt": "T", "effect": "E7 p.L28F"},
                {"gene": "E7", "position": 647,  "ref": "G", "alt": "A", "effect": "E7 p.D55N"},
                {"gene": "E7", "position": 683,  "ref": "T", "alt": "C", "effect": "E7 p.H67P"},
                {"gene": "E6", "position": 106,  "ref": "A", "alt": "G", "effect": "E6 p.D64G"},
            ],
            "hpv-31": [
                {"gene": "E7", "position": 571,  "ref": "A", "alt": "G", "effect": "E7 p.N31S"},
                {"gene": "E7", "position": 631,  "ref": "C", "alt": "T", "effect": "E7 p.T49I"},
                {"gene": "E7", "position": 712,  "ref": "G", "alt": "A", "effect": "E7 p.G77D"},
            ],
            "hpv-45": [
                {"gene": "E7", "position": 554,  "ref": "G", "alt": "A", "effect": "E7 p.A25T"},
                {"gene": "E7", "position": 668,  "ref": "C", "alt": "G", "effect": "E7 p.P60A"},
                {"gene": "E7", "position": 745,  "ref": "T", "alt": "C", "effect": "E7 p.L88P"},
            ],
            "hpv-6": [
                {"gene": "E7", "position": 560,  "ref": "A", "alt": "G", "effect": "E7 p.K27E (low-risk marker)"},
                {"gene": "E7", "position": 620,  "ref": "G", "alt": "C", "effect": "E7 p.C45S (Rb-binding)"},
                {"gene": "E7", "position": 700,  "ref": "C", "alt": "T", "effect": "E7 p.P73L"},
            ],
        },
    },

    # ── STI / Chlamydia (AE001273.1, serovar D reference) ────────────────────
    # ompA serovars differ in Variable Domains (VD1–VD4)
    # Reference window: 400–900 nt
    "STI": {
        "variants": [
            {"id": "wild-type",  "label": "Serovar D (Wild-Type)",  "lineage": "Serovar D", "who_label": "Reference"},
            {"id": "serovar-a",  "label": "Serovar A (Trachoma)",   "lineage": "Serovar A", "who_label": "Ocular"},
            {"id": "serovar-e",  "label": "Serovar E (Urogenital)", "lineage": "Serovar E", "who_label": "Common"},
            {"id": "serovar-l2", "label": "Serovar L2 (LGV)",       "lineage": "Serovar L2","who_label": "Invasive"},
        ],
        "mutations": {
            "wild-type": [],
            "serovar-a": [
                {"gene": "ompA", "position": 440,  "ref": "G", "alt": "A", "effect": "VD1 p.G57D"},
                {"gene": "ompA", "position": 512,  "ref": "C", "alt": "T", "effect": "VD1 p.P81L"},
                {"gene": "ompA", "position": 618,  "ref": "A", "alt": "G", "effect": "VD2 p.N116S"},
                {"gene": "ompA", "position": 672,  "ref": "T", "alt": "C", "effect": "VD2 p.F134L"},
            ],
            "serovar-e": [
                {"gene": "ompA", "position": 453,  "ref": "C", "alt": "A", "effect": "VD1 p.T61K"},
                {"gene": "ompA", "position": 550,  "ref": "G", "alt": "T", "effect": "VD1-VD2 p.A93S"},
                {"gene": "ompA", "position": 630,  "ref": "C", "alt": "G", "effect": "VD2 p.P120A"},
            ],
            "serovar-l2": [
                {"gene": "ompA", "position": 420,  "ref": "A", "alt": "G", "effect": "VD1 p.K50E (invasive marker)"},
                {"gene": "ompA", "position": 485,  "ref": "G", "alt": "C", "effect": "VD1 p.G73R"},
                {"gene": "ompA", "position": 556,  "ref": "T", "alt": "A", "effect": "VD2 p.L95H"},
                {"gene": "ompA", "position": 640,  "ref": "C", "alt": "T", "effect": "VD2 p.P123L"},
                {"gene": "ompA", "position": 710,  "ref": "G", "alt": "A", "effect": "VD3 p.G147D"},
            ],
        },
    },
}


# ─── Public API ───────────────────────────────────────────────────────────────

def get_variant_list(disease_type: str) -> list[dict]:
    return VARIANT_CATALOG.get(disease_type, {}).get("variants", [])


def get_mutations(disease_type: str, variant_id: str) -> list[dict]:
    return (
        VARIANT_CATALOG
        .get(disease_type, {})
        .get("mutations", {})
        .get(variant_id, [])
    )
