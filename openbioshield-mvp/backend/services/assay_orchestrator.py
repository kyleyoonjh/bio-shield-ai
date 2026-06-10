"""
9-step Assay Design pipeline orchestrator.

Step 1  AlignmentService      — MAFFT MSA
Step 2  ConservationService   — Shannon Entropy conserved regions
Step 3  CandidateAnalysis     — Primer3 candidate generation
Step 4  OffTargetFilter       — Bowtie2/BLAST+ hard filter (specificity)
Step 5  CoverageService       — Variant coverage per candidate
Step 6  ThermoScoringService  — Tm, GC, dimer, hairpin scoring
Step 7  AIScoringService      — Feature-based / XGBoost efficiency prediction
Step 8  RankingService        — Weighted final score + rank
Step 9  ReportService         — JSON summary report

All Supabase writes use supabase_service (REST API, verify=False) —
no direct PostgreSQL connections (company firewall blocks 5432/6543).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from services.alignment_service      import AlignmentService
from services.conservation_service   import ConservationService
from services.candidate_analysis_service import CandidateAnalysisService
from services.coverage_service       import CoverageService
from services.off_target_filter_service  import OffTargetFilterService
from services.thermo_scoring_service import ThermoScoringService
from services.ai_scoring_service     import AIScoringService
from services.ranking_service        import RankingService
from services.report_service         import ReportService

logger = logging.getLogger(__name__)


class AssayOrchestrator:
    def __init__(self):
        self.alignment   = AlignmentService()
        self.conservation = ConservationService()
        self.candidate   = CandidateAnalysisService()
        self.coverage    = CoverageService()
        self.off_target  = OffTargetFilterService()
        self.thermo      = ThermoScoringService()
        self.ai_scoring  = AIScoringService()
        self.ranking     = RankingService()
        self.report      = ReportService()

    async def run_pipeline(
        self,
        assay_id:        int | str,
        fasta_path:      str,
        assay_type:      str,
        advanced_options: dict[str, Any] | None = None,
        progress_cb=None,   # optional async callback(step: int, total: int, msg: str)
    ) -> dict[str, Any]:
        """
        Execute the full 9-step pipeline.
        Returns {report_path, ranked_primers, stats}.
        Updates Supabase assay status via supabase_service.
        """
        total_steps = 9

        async def _progress(step: int, msg: str):
            logger.info("[pipeline] assay=%s step=%d/%d — %s", assay_id, step, total_steps, msg)
            if progress_cb:
                await progress_cb(step, total_steps, msg)

        try:
            await self._update_status(assay_id, "RUNNING")

            # ── All CPU-bound steps run in a thread so the event loop stays free ──

            # Step 1 — MSA
            await _progress(1, "Running MAFFT alignment")
            aligned = await asyncio.to_thread(self.alignment.run_mafft, fasta_path)

            # Step 2 — Conserved regions
            await _progress(2, "Detecting conserved regions (Shannon entropy)")
            regions = await asyncio.to_thread(self.conservation.find_regions, aligned)
            if not regions:
                raise ValueError("No conserved regions found — check input diversity")

            # Step 3 — Primer3 candidates
            await _progress(3, "Generating primer candidates (Primer3)")
            raw_candidates = await asyncio.to_thread(
                self.candidate.generate_primers, regions, advanced_options, assay_type
            )
            if not raw_candidates:
                raise ValueError("Primer3 produced no candidates — try relaxing parameters")

            # Step 4 — Specificity filter
            await _progress(4, f"Running off-target specificity filter ({len(raw_candidates)} candidates)")

            def _run_specificity(candidates):
                out = []
                for cand in candidates:
                    spec = self.off_target.validate_specificity(
                        cand["forward"], cand["reverse"], cand.get("probe")
                    )
                    if not spec["is_valid"]:
                        continue
                    cand["specificity_valid"] = True
                    cand["specificity_score"] = spec["specificity_score"]
                    out.append(cand)
                return out

            validated_spec: list[dict] = await asyncio.to_thread(_run_specificity, raw_candidates)
            if not validated_spec:
                raise ValueError("All candidates failed specificity filter")
            logger.info("[pipeline] step 4 → %d/%d passed specificity", len(validated_spec), len(raw_candidates))

            # Step 5 — Coverage scoring
            await _progress(5, f"Calculating variant coverage ({len(validated_spec)} candidates)")

            def _run_coverage(candidates, fp):
                for cand in candidates:
                    cov = self.coverage.calculate_coverage(cand["forward"], cand["reverse"], fp)
                    cand["coverage_score"] = cov["coverage_score"]
                return candidates

            validated_spec = await asyncio.to_thread(_run_coverage, validated_spec, fasta_path)

            # Step 6 — Thermodynamic scoring
            await _progress(6, "Thermodynamic scoring (Tm, GC, dimer, hairpin, cross-dimer)")

            def _run_thermo(candidates):
                for cand in candidates:
                    probe = cand.get("probe")
                    if probe:
                        thermo = self.thermo.evaluate_kinetics_with_probe(
                            cand["forward"], cand["reverse"], probe
                        )
                    else:
                        thermo = self.thermo.evaluate_kinetics(cand["forward"], cand["reverse"])
                    cand.update(thermo)
                return candidates

            validated_spec = await asyncio.to_thread(_run_thermo, validated_spec)

            # Step 7 — AI efficiency scoring
            await _progress(7, "AI efficiency scoring")

            def _run_ai(candidates):
                for cand in candidates:
                    ai = self.ai_scoring.predict_efficiency(cand)
                    cand["ai_score"] = ai["ai_score"]
                return candidates

            validated = await asyncio.to_thread(_run_ai, validated_spec)

            # Step 8 — Ranking
            await _progress(8, "Computing weighted final rankings")
            ranked = await asyncio.to_thread(self.ranking.calculate_final_rankings, validated)

            # Step 9 — Report
            await _progress(9, "Generating HTML + PDF report")
            report_html = await asyncio.to_thread(self.report.generate_summary, assay_id, ranked)
            report_path = f"/api/v3/assay/report/{assay_id}"

            # Persist top primers BEFORE marking COMPLETED to avoid race condition
            logger.info("[pipeline] _save_primers 호출 | ranked count=%d", len(ranked))
            if ranked:
                logger.info("[pipeline] ranked[0] keys: %s", list(ranked[0].keys()))
                logger.info("[pipeline] ranked[0] sample: forward=%s gc_fwd=%s gc_rev=%s tm_fwd=%s",
                    ranked[0].get("forward","?")[:12],
                    ranked[0].get("gc_fwd","MISSING"),
                    ranked[0].get("gc_rev","MISSING"),
                    ranked[0].get("tm_fwd","MISSING"))
            await self._save_primers(assay_id, ranked[:10])

            await self._update_status(
                assay_id, "COMPLETED",
                report_path=report_path,
                report_html=report_html,
            )

            return {
                "report_path":   report_path,
                "ranked_primers": ranked,
                "stats": {
                    "total_generated":  len(raw_candidates),
                    "passed_filter":    len(validated),
                    "conserved_regions": len(regions),
                },
            }

        except Exception as exc:
            logger.exception("[pipeline] assay=%s FAILED: %s", assay_id, exc)
            await self._update_status(assay_id, "FAILED", error=str(exc))
            raise

    # ── Supabase persistence (REST API only — no direct DB) ────────────────

    @staticmethod
    async def _update_status(
        assay_id,
        status: str,
        report_path: str | None = None,
        report_html: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            from services.supabase_service import _get_client
            client = _get_client()
            payload: dict[str, Any] = {"status": status, "updated_at": datetime.utcnow().isoformat()}
            if report_path:
                payload["report_path"] = report_path
            if report_html:
                payload["report_html"] = report_html
            if error:
                payload["error_message"] = error[:500]
            client.table("assay_jobs").update(payload).eq("id", str(assay_id)).execute()
        except Exception as exc:
            logger.warning("[pipeline] Supabase status update failed: %s", exc)

    @staticmethod
    async def _save_primers(assay_id, ranked: list[dict]) -> None:
        _PROBE_COLS = {"probe_sequence", "tm_fwd", "tm_rev", "tm_probe", "probe_center_score"}
        try:
            from services.supabase_service import _get_client
            client = _get_client()
            rows = [
                {
                    "assay_id":           str(assay_id),
                    "forward_primer":     c["forward"],
                    "reverse_primer":     c["reverse"],
                    "probe_sequence":     c.get("probe"),
                    "tm":                 round((c.get("tm_fwd", 0) + c.get("tm_rev", 0)) / 2, 2),
                    "tm_fwd":             round(c["tm_fwd"], 2) if c.get("tm_fwd") is not None else None,
                    "tm_rev":             round(c["tm_rev"], 2) if c.get("tm_rev") is not None else None,
                    "tm_probe":           round(c["tm_probe"], 2) if c.get("tm_probe") is not None else None,
                    "probe_center_score": min(round(c.get("probe_center_score") or 0, 2), 99.99) if c.get("probe_center_score") is not None else None,
                    "gc":                 min(round((c.get("gc_fwd", 0) + c.get("gc_rev", 0)) / 2, 2), 99.99),
                    "coverage_score":     min(round(c.get("coverage_score", 0), 2), 99.99),
                    "specificity_score":  min(round(c.get("specificity_score", 0), 2), 99.99),
                    "thermo_score":       min(round(c.get("thermo_score", 0), 2), 99.99),
                    "ai_score":           min(round(c.get("ai_score", 0), 2), 99.99),
                    "final_score":        min(round(c.get("final_score", 0), 2), 99.99),
                    "final_rank":         c.get("final_rank", 0),
                    "product_size":       c.get("product_size", 0),
                }
                for c in ranked
            ]
            if not rows:
                logger.warning("[pipeline] _save_primers: rows is empty — nothing to insert!")
                return
            logger.info("[pipeline] _save_primers: inserting %d rows", len(rows))
            try:
                res = client.table("assay_primers").insert(rows).execute()
                logger.info("[pipeline] _save_primers INSERT OK: %d rows saved", len(res.data or []))
            except Exception as probe_exc:
                logger.warning(
                    "[pipeline] full primer INSERT failed (%s) — retrying without probe columns", probe_exc
                )
                base_rows = [
                    {k: v for k, v in row.items() if k not in _PROBE_COLS}
                    for row in rows
                ]
                try:
                    res2 = client.table("assay_primers").insert(base_rows).execute()
                    logger.info("[pipeline] _save_primers base INSERT OK: %d rows saved", len(res2.data or []))
                except Exception as base_exc:
                    logger.error("[pipeline] _save_primers base INSERT also failed: %s", base_exc)
        except Exception as exc:
            logger.error("[pipeline] Supabase primer save OUTER failed: %s", exc)
