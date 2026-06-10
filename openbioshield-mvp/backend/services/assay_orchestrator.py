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
import time
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
        t_pipeline  = time.perf_counter()

        async def _progress(step: int, msg: str):
            elapsed = time.perf_counter() - t_pipeline
            logger.info("[pipeline] step=%d/%d elapsed=%.1fs | %s | assay=%s",
                        step, total_steps, elapsed, msg, assay_id)
            if progress_cb:
                await progress_cb(step, total_steps, msg)

        try:
            await self._update_status(assay_id, "RUNNING")

            # Step 1 — MSA
            await _progress(1, "MAFFT alignment")
            t = time.perf_counter()
            aligned = await asyncio.to_thread(self.alignment.run_mafft, fasta_path)
            logger.info("[pipeline] step=1 DONE | sequences=%d elapsed=%.2fs",
                        len(aligned) if aligned else 0, time.perf_counter() - t)

            # Step 2 — Conserved regions
            await _progress(2, "Shannon entropy conserved regions")
            t = time.perf_counter()
            regions = await asyncio.to_thread(self.conservation.find_regions, aligned)
            logger.info("[pipeline] step=2 DONE | regions=%d elapsed=%.2fs",
                        len(regions), time.perf_counter() - t)
            if not regions:
                raise ValueError("No conserved regions found — check input diversity")

            # Step 3 — Primer3 candidates
            await _progress(3, "Primer3 candidate generation")
            t = time.perf_counter()
            raw_candidates = await asyncio.to_thread(
                self.candidate.generate_primers, regions, advanced_options, assay_type
            )
            logger.info("[pipeline] step=3 DONE | candidates=%d elapsed=%.2fs",
                        len(raw_candidates), time.perf_counter() - t)
            if not raw_candidates:
                raise ValueError("Primer3 produced no candidates — try relaxing parameters")

            # Step 4 — Specificity filter
            await _progress(4, f"Off-target specificity filter ({len(raw_candidates)} candidates)")
            t = time.perf_counter()

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
            logger.info("[pipeline] step=4 DONE | passed=%d/%d elapsed=%.2fs",
                        len(validated_spec), len(raw_candidates), time.perf_counter() - t)
            if not validated_spec:
                raise ValueError("All candidates failed specificity filter")

            # Step 5 — Coverage scoring
            await _progress(5, f"Variant coverage ({len(validated_spec)} candidates)")
            t = time.perf_counter()

            def _run_coverage(candidates, fp):
                for cand in candidates:
                    cov = self.coverage.calculate_coverage(cand["forward"], cand["reverse"], fp)
                    cand["coverage_score"] = cov["coverage_score"]
                return candidates

            validated_spec = await asyncio.to_thread(_run_coverage, validated_spec, fasta_path)
            logger.info("[pipeline] step=5 DONE | elapsed=%.2fs", time.perf_counter() - t)

            # Step 6 — Thermodynamic scoring
            await _progress(6, "Thermodynamic scoring (Tm, GC, dimer, hairpin)")
            t = time.perf_counter()

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
            logger.info("[pipeline] step=6 DONE | elapsed=%.2fs", time.perf_counter() - t)

            # Step 7 — AI efficiency scoring
            await _progress(7, "AI efficiency scoring")
            t = time.perf_counter()

            def _run_ai(candidates):
                for cand in candidates:
                    ai = self.ai_scoring.predict_efficiency(cand)
                    cand["ai_score"] = ai["ai_score"]
                return candidates

            validated = await asyncio.to_thread(_run_ai, validated_spec)
            logger.info("[pipeline] step=7 DONE | elapsed=%.2fs", time.perf_counter() - t)

            # Step 8 — Ranking
            await _progress(8, "Weighted final ranking")
            t = time.perf_counter()
            ranked = await asyncio.to_thread(self.ranking.calculate_final_rankings, validated)
            logger.info("[pipeline] step=8 DONE | ranked=%d elapsed=%.2fs",
                        len(ranked), time.perf_counter() - t)

            # Step 9 — Report
            await _progress(9, "HTML + PDF report generation")
            t = time.perf_counter()
            report_html = await asyncio.to_thread(self.report.generate_summary, assay_id, ranked)
            report_path = f"/api/v3/assay/report/{assay_id}"
            html_kb = len(report_html) // 1024 if report_html else 0
            logger.info("[pipeline] step=9 DONE | html_kb=%d elapsed=%.2fs",
                        html_kb, time.perf_counter() - t)

            # Save top primers → mark COMPLETED
            await self._save_primers(assay_id, ranked[:10])
            await self._update_status(
                assay_id, "COMPLETED",
                report_path=report_path,
                report_html=report_html,
            )

            total_elapsed = time.perf_counter() - t_pipeline
            logger.info(
                "[pipeline] ✅ COMPLETED | assay=%s total=%.1fs "
                "candidates=%d passed=%d ranked=%d",
                assay_id, total_elapsed, len(raw_candidates), len(validated), len(ranked),
            )

            return {
                "report_path":   report_path,
                "ranked_primers": ranked,
                "stats": {
                    "total_generated":   len(raw_candidates),
                    "passed_filter":     len(validated),
                    "conserved_regions": len(regions),
                    "elapsed_seconds":   round(total_elapsed, 1),
                },
            }

        except Exception as exc:
            elapsed = time.perf_counter() - t_pipeline
            logger.exception("[pipeline] ❌ FAILED | assay=%s elapsed=%.1fs error=%s",
                             assay_id, elapsed, exc)
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
        t0 = time.perf_counter()
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
            _id = str(assay_id)
            html_kb = len(report_html) // 1024 if report_html else 0
            await asyncio.to_thread(
                lambda: client.table("assay_jobs").update(payload).eq("id", _id).execute()
            )
            logger.info("[update_status] %s | assay=%s html_kb=%d elapsed=%.0fms",
                        status, assay_id, html_kb, (time.perf_counter() - t0) * 1000)
        except Exception as exc:
            logger.warning("[update_status] FAILED | assay=%s status=%s error=%s elapsed=%.0fms",
                           assay_id, status, exc, (time.perf_counter() - t0) * 1000)

    @staticmethod
    async def _save_primers(assay_id, ranked: list[dict]) -> None:
        _PROBE_COLS = {"probe_sequence", "tm_fwd", "tm_rev", "tm_probe", "probe_center_score"}
        t0 = time.perf_counter()
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
                logger.warning("[save_primers] SKIP — no rows to insert | assay=%s", assay_id)
                return

            has_probe = any(r.get("probe_sequence") for r in rows)
            logger.info("[save_primers] INSERT %d rows | assay=%s has_probe=%s",
                        len(rows), assay_id, has_probe)
            try:
                res = await asyncio.to_thread(
                    lambda: client.table("assay_primers").insert(rows).execute()
                )
                logger.info("[save_primers] INSERT OK | assay=%s saved=%d elapsed=%.0fms",
                            assay_id, len(res.data or []), (time.perf_counter() - t0) * 1000)
            except Exception as probe_exc:
                logger.warning(
                    "[save_primers] full INSERT failed — retrying without probe cols | "
                    "assay=%s error=%s elapsed=%.0fms",
                    assay_id, probe_exc, (time.perf_counter() - t0) * 1000,
                )
                base_rows = [
                    {k: v for k, v in row.items() if k not in _PROBE_COLS}
                    for row in rows
                ]
                try:
                    res2 = await asyncio.to_thread(
                        lambda: client.table("assay_primers").insert(base_rows).execute()
                    )
                    logger.info("[save_primers] base INSERT OK | assay=%s saved=%d elapsed=%.0fms",
                                assay_id, len(res2.data or []), (time.perf_counter() - t0) * 1000)
                except Exception as base_exc:
                    logger.error("[save_primers] base INSERT FAILED | assay=%s error=%s elapsed=%.0fms",
                                 assay_id, base_exc, (time.perf_counter() - t0) * 1000)
        except Exception as exc:
            logger.error("[save_primers] OUTER FAILED | assay=%s error=%s elapsed=%.0fms",
                         assay_id, exc, (time.perf_counter() - t0) * 1000)
