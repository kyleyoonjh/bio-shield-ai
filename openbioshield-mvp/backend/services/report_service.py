"""
Assay design report generator.
Produces JSON + HTML + PDF reports for each completed pipeline run.

Dependencies:
  - jinja2     (HTML template rendering)
  - reportlab  (PDF generation — Platypus layout engine)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

# ── HTML template (inline Jinja2) ────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Assay Design Report — {{ assay_id }}</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:#1e293b;background:#f8fafc;padding:32px}
    header{background:#0f172a;color:#f1f5f9;padding:24px 32px;border-radius:12px;margin-bottom:28px}
    header h1{font-size:22px;font-weight:700;letter-spacing:.5px}
    header .meta{margin-top:8px;opacity:.7;font-size:12px}
    .section{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:20px 24px;margin-bottom:20px}
    .section h2{font-size:14px;font-weight:700;color:#334155;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid #f1f5f9}
    table{width:100%;border-collapse:collapse;font-size:12px}
    th{background:#f1f5f9;color:#475569;font-weight:600;padding:8px 10px;text-align:left;white-space:nowrap}
    td{padding:7px 10px;border-bottom:1px solid #f8fafc;vertical-align:top}
    tr:last-child td{border-bottom:none}
    tr:hover td{background:#f8fafc}
    .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600}
    .badge-green{background:#dcfce7;color:#166534}
    .badge-yellow{background:#fef9c3;color:#854d0e}
    .badge-red{background:#fee2e2;color:#991b1b}
    .score-bar{display:flex;align-items:center;gap:6px}
    .bar{height:8px;border-radius:4px;background:#3b82f6;min-width:2px}
    .num{color:#64748b;width:36px;text-align:right;font-size:11px}
    .seq{font-family:'Courier New',monospace;font-size:11px;color:#0f172a;word-break:break-all}
    .kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
    .kpi{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;text-align:center}
    .kpi .val{font-size:24px;font-weight:700;color:#0f172a;margin-bottom:2px}
    .kpi .lbl{font-size:11px;color:#64748b}
    footer{text-align:center;font-size:11px;color:#94a3b8;margin-top:24px}
  </style>
</head>
<body>
<header>
  <h1>OpenBioShield — Assay Design Report</h1>
  <div class="meta">
    Assay ID: <strong>{{ assay_id }}</strong> &nbsp;|&nbsp;
    Generated: {{ generated_at }} &nbsp;|&nbsp;
    Candidates evaluated: {{ total_candidates }}
  </div>
</header>

<div class="section">
  <h2>Summary</h2>
  <div class="kpi-grid">
    <div class="kpi"><div class="val">{{ total_candidates }}</div><div class="lbl">Total Candidates</div></div>
    <div class="kpi"><div class="val">{{ top_candidates | length }}</div><div class="lbl">Top Ranked</div></div>
    <div class="kpi"><div class="val">{{ "%.1f" | format(top_candidates[0].final_score) if top_candidates else "—" }}</div><div class="lbl">Best Score (0–100)</div></div>
    <div class="kpi"><div class="val">{{ "%.1f" | format(top_candidates[0].tm_fwd) if top_candidates else "—" }}°C</div><div class="lbl">Best Primer Tm</div></div>
  </div>
</div>

<div class="section">
  <h2>Top Primer Candidates</h2>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Forward Primer (5'→3')</th>
        <th>Reverse Primer (5'→3')</th>
        <th>Tm Fwd</th>
        <th>Tm Rev</th>
        <th>GC Fwd</th>
        <th>GC Rev</th>
        <th>Product</th>
        <th>Coverage</th>
        <th>Thermo</th>
        <th>AI</th>
        <th>Final Score</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
    {% for c in top_candidates %}
      <tr>
        <td><strong>{{ c.rank }}</strong></td>
        <td><span class="seq">{{ c.forward }}</span></td>
        <td><span class="seq">{{ c.reverse }}</span></td>
        <td>{{ "%.1f" | format(c.tm_fwd) }}°C</td>
        <td>{{ "%.1f" | format(c.tm_rev) }}°C</td>
        <td>{{ "%.1f" | format(c.gc_fwd) }}%</td>
        <td>{{ "%.1f" | format(c.gc_rev) }}%</td>
        <td>{{ c.product_size }} bp</td>
        <td>
          <div class="score-bar">
            <div class="bar" style="width:{{ [[c.coverage_score, 100] | min * 0.6, 0.1] | max | float | round(1) }}px"></div>
            <span class="num">{{ "%.0f" | format(c.coverage_score) }}%</span>
          </div>
        </td>
        <td>
          <div class="score-bar">
            <div class="bar" style="width:{{ [[c.thermo_score, 100] | min * 0.6, 0.1] | max | float | round(1) }}px"></div>
            <span class="num">{{ "%.0f" | format(c.thermo_score) }}</span>
          </div>
        </td>
        <td>
          <div class="score-bar">
            <div class="bar" style="width:{{ [[c.ai_score, 100] | min * 0.6, 0.1] | max | float | round(1) }}px"></div>
            <span class="num">{{ "%.0f" | format(c.ai_score) }}</span>
          </div>
        </td>
        <td><strong>{{ "%.1f" | format(c.final_score) }}</strong></td>
        <td>
          {% if c.penalty_reason == "Pass" or not c.penalty_reason %}
            <span class="badge badge-green">Pass</span>
          {% else %}
            <span class="badge badge-yellow" title="{{ c.penalty_reason }}">Warn</span>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div class="section">
  <h2>Score Weights</h2>
  <table style="max-width:320px">
    <tr><th>Component</th><th>Weight</th></tr>
    <tr><td>Coverage Score</td><td>{{ (score_weights.coverage * 100) | int }}%</td></tr>
    <tr><td>Thermodynamic Score</td><td>{{ (score_weights.thermo * 100) | int }}%</td></tr>
    <tr><td>AI Efficiency Score</td><td>{{ (score_weights.ai * 100) | int }}%</td></tr>
  </table>
</div>

<footer>OpenBioShield MVP &mdash; Generated {{ generated_at }}</footer>
</body>
</html>
"""


class ReportService:
    def __init__(self, report_dir: str = _REPORT_DIR):
        self.report_dir = report_dir
        os.makedirs(report_dir, exist_ok=True)

    def generate_summary(
        self,
        assay_id: int | str,
        ranked_primers: list[dict],
        assay_info: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate JSON + HTML + PDF reports.
        Returns the path to the HTML report (primary artifact).
        """
        top10 = ranked_primers[:10]
        now_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        iso_str = datetime.utcnow().isoformat() + "Z"
        base = f"assay_{assay_id}_{now_str}"

        summary = self._build_summary(assay_id, iso_str, ranked_primers, top10)

        json_path = os.path.join(self.report_dir, f"{base}.json")
        html_path = os.path.join(self.report_dir, f"{base}.html")
        pdf_path  = os.path.join(self.report_dir, f"{base}.pdf")

        # ── JSON ──────────────────────────────────────────────────────────────
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info("[report] JSON → %s", json_path)

        # ── HTML ──────────────────────────────────────────────────────────────
        try:
            html_content = self._render_html(summary)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info("[report] HTML → %s", html_path)
        except Exception as exc:
            logger.warning("[report] HTML generation failed: %s", exc)
            html_path = json_path  # fallback

        # ── PDF ───────────────────────────────────────────────────────────────
        try:
            self._render_pdf(summary, pdf_path)
            logger.info("[report] PDF  → %s", pdf_path)
        except Exception as exc:
            logger.warning("[report] PDF generation failed: %s", exc)

        # Return URL path (served via FastAPI StaticFiles at /reports/)
        return f"/reports/{os.path.basename(html_path)}"

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        assay_id: Any,
        iso_str: str,
        ranked_primers: list[dict],
        top10: list[dict],
    ) -> dict:
        return {
            "assay_id":           str(assay_id),
            "generated_at":       iso_str,
            "total_candidates":   len(ranked_primers),
            "top_candidates": [
                {
                    "rank":           c.get("final_rank"),
                    "forward":        c.get("forward", ""),
                    "reverse":        c.get("reverse", ""),
                    "final_score":    round(c.get("final_score", 0.0), 4),
                    "coverage_score": round(c.get("coverage_score", 0.0), 2),
                    "thermo_score":   round(c.get("thermo_score", 0.0), 2),
                    "ai_score":       round(c.get("ai_score", 0.0), 2),
                    "tm_fwd":         round(c.get("tm_fwd", 0.0), 2),
                    "tm_rev":         round(c.get("tm_rev", 0.0), 2),
                    "gc_fwd":         round(c.get("gc_fwd", 0.0), 2),
                    "gc_rev":         round(c.get("gc_rev", 0.0), 2),
                    "product_size":   c.get("product_size", 0),
                    "specificity":    round(c.get("specificity_score", 0.0), 4),
                    "penalty_reason": c.get("penalty_reason", ""),
                }
                for c in top10
            ],
            "score_weights": {"coverage": 0.6, "thermo": 0.2, "ai": 0.2},
        }

    @staticmethod
    def _render_html(summary: dict) -> str:
        from jinja2 import Environment, Undefined  # type: ignore

        env = Environment(undefined=Undefined)
        tmpl = env.from_string(_HTML_TEMPLATE)
        return tmpl.render(**summary)

    @staticmethod
    def _render_pdf(summary: dict, pdf_path: str) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        )

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )

        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
        h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceAfter=4)
        body = styles["Normal"]
        mono = ParagraphStyle("Mono", parent=body, fontName="Courier", fontSize=8)
        small = ParagraphStyle("Small", parent=body, fontSize=8, textColor=colors.HexColor("#64748b"))

        story = []

        # ── Header ───────────────────────────────────────────────────────────
        story.append(Paragraph("OpenBioShield — Assay Design Report", h1))
        story.append(Paragraph(
            f"Assay ID: <b>{summary['assay_id']}</b> &nbsp;|&nbsp; "
            f"Generated: {summary['generated_at']} &nbsp;|&nbsp; "
            f"Candidates: {summary['total_candidates']}",
            small,
        ))
        story.append(Spacer(1, 6 * mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
        story.append(Spacer(1, 4 * mm))

        # ── Top candidates table ──────────────────────────────────────────────
        story.append(Paragraph("Top Primer Candidates", h2))

        header_row = [
            "#", "Forward (5'→3')", "Reverse (5'→3')",
            "Tm F\n(°C)", "Tm R\n(°C)", "GC F\n(%)", "GC R\n(%)",
            "Prod\n(bp)", "Cov", "Thermo", "AI", "Score",
        ]
        rows = [header_row]
        for c in summary["top_candidates"]:
            rows.append([
                str(c["rank"]),
                Paragraph(c["forward"] or "—", mono),
                Paragraph(c["reverse"] or "—", mono),
                f"{c['tm_fwd']:.1f}",
                f"{c['tm_rev']:.1f}",
                f"{c['gc_fwd']:.1f}",
                f"{c['gc_rev']:.1f}",
                str(c["product_size"]),
                f"{c['coverage_score']:.1f}",
                f"{c['thermo_score']:.1f}",
                f"{c['ai_score']:.1f}",
                f"{c['final_score']:.3f}",
            ])

        col_widths = [8*mm, 42*mm, 42*mm, 13*mm, 13*mm, 13*mm, 13*mm, 13*mm, 12*mm, 14*mm, 10*mm, 14*mm]
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 7),
            ("FONTSIZE",      (0, 1), (-1, -1), 8),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("ALIGN",         (1, 1), (2, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 6 * mm))

        # ── Score weights ─────────────────────────────────────────────────────
        story.append(Paragraph("Score Weights", h2))
        w = summary["score_weights"]
        wrows = [
            ["Component",        "Weight"],
            ["Coverage Score",   f"{w['coverage']*100:.0f}%"],
            ["Thermodynamic",    f"{w['thermo']*100:.0f}%"],
            ["AI Efficiency",    f"{w['ai']*100:.0f}%"],
        ]
        wtbl = Table(wrows, colWidths=[60*mm, 30*mm])
        wtbl.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("GRID",        (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
            ("TOPPADDING",  (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ]))
        story.append(wtbl)

        doc.build(story)
