import { useMemo } from "react";
import type { AssayPrimer } from "../../types";
import { computeExplainability, type RiskLevel } from "../../utils/xprEngine";

// ── Radar Chart ───────────────────────────────────────────────────────────────

import type { RadarData } from "../../utils/xprEngine";

interface RadarChartProps {
  values: RadarData; // 0–100
}

function RadarChart({ values }: RadarChartProps) {
  const labels = Object.keys(values);
  const data   = Object.values(values);
  const N      = labels.length;
  const cx = 130; const cy = 130; const r = 100;

  const angleOf = (i: number) => (Math.PI * 2 * i) / N - Math.PI / 2;

  const point = (i: number, pct: number): [number, number] => [
    cx + r * pct * Math.cos(angleOf(i)),
    cy + r * pct * Math.sin(angleOf(i)),
  ];

  const gridCircles = [0.25, 0.5, 0.75, 1.0];

  const polygon = data
    .map((v, i) => point(i, v / 100).join(","))
    .join(" ");

  const labelPos = (i: number): [number, number] => {
    const [x, y] = point(i, 1.22);
    return [x, y];
  };

  const shorten: Record<string, string> = {
    coverage:       "Coverage",
    thermodynamics: "Thermo",
    gcQuality:      "GC",
    ampliconQuality:"Amplicon",
    riskProfile:    "Risk",
    aiEfficiency:   "AI",
  };

  return (
    <svg viewBox="0 0 260 260" className="w-full max-w-xs mx-auto">
      {/* Grid circles */}
      {gridCircles.map((pct, gi) => (
        <polygon
          key={gi}
          points={Array.from({ length: N }, (_, i) => point(i, pct).join(",")).join(" ")}
          fill="none"
          stroke="#334155"
          strokeWidth={gi === gridCircles.length - 1 ? 1 : 0.5}
        />
      ))}

      {/* Axes */}
      {labels.map((_, i) => {
        const [x, y] = point(i, 1);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#334155" strokeWidth={0.8} />;
      })}

      {/* Data polygon */}
      <polygon
        points={polygon}
        fill="rgba(139,92,246,0.25)"
        stroke="#8b5cf6"
        strokeWidth={2}
        strokeLinejoin="round"
      />

      {/* Data points */}
      {data.map((v, i) => {
        const [x, y] = point(i, v / 100);
        return <circle key={i} cx={x} cy={y} r={3.5} fill="#8b5cf6" />;
      })}

      {/* Labels */}
      {labels.map((key, i) => {
        const [x, y] = labelPos(i);
        return (
          <text
            key={i}
            x={x} y={y}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={9}
            fill="#94a3b8"
            fontWeight="600"
          >
            {shorten[key] ?? key}
          </text>
        );
      })}

      {/* Center value labels */}
      {data.map((v, i) => {
        const [x, y] = point(i, (v / 100) * 0.62);
        if (v < 8) return null;
        return (
          <text key={i} x={x} y={y} textAnchor="middle" dominantBaseline="central"
            fontSize={7} fill="#c4b5fd">
            {Math.round(v)}
          </text>
        );
      })}
    </svg>
  );
}

// ── Risk badge ────────────────────────────────────────────────────────────────

function RiskBadge({ level }: { level: RiskLevel }) {
  const cfg: Record<RiskLevel, string> = {
    LOW:    "bg-emerald-900/40 text-emerald-300 border-emerald-600/40",
    MEDIUM: "bg-amber-900/40 text-amber-300 border-amber-600/40",
    HIGH:   "bg-red-900/40 text-red-300 border-red-600/40",
  };
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${cfg[level]}`}>
      {level}
    </span>
  );
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-800/60 border-b border-slate-700">
        <p className="text-xs font-semibold text-slate-300 uppercase tracking-wider">{title}</p>
      </div>
      <div className="px-4 py-3">{children}</div>
    </div>
  );
}

// ── Main Drawer ───────────────────────────────────────────────────────────────

interface Props {
  primer: AssayPrimer | null;
  allPrimers: AssayPrimer[];
  onClose: () => void;
}

export default function CandidateDetailDrawer({ primer, allPrimers, onClose }: Props) {
  console.log('[Drawer] render | primer=', primer?.id ?? null, 'allPrimers=', allPrimers.length);

  const xpr = useMemo(
    () => {
      if (!primer) { console.log('[Drawer] primer is null — returning null'); return null; }
      try {
        const result = computeExplainability(primer, allPrimers);
        console.log('[Drawer] xpr computed OK | finalScore=', result.scoreBreakdown.finalScore);
        return result;
      } catch (e) {
        console.error('[Drawer] computeExplainability threw:', e);
        return null;
      }
    },
    [primer, allPrimers],
  );

  console.log('[Drawer] xpr=', xpr ? 'OK' : 'null', '→ will render:', !!(primer && xpr));
  if (!primer || !xpr) return null;

  const rank = primer.final_rank ?? "—";
  const tmFwd  = primer.tm_fwd  ?? primer.tm;
  const tmRev  = primer.tm_rev  ?? primer.tm;
  const recColor: Record<string, string> = {
    high:        "text-emerald-300",
    recommended: "text-blue-300",
    consider:    "text-amber-300",
    low:         "text-red-400",
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <div className="fixed top-0 right-0 z-40 h-full w-full max-w-[480px] bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700 flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-xl font-bold text-yellow-400">#{rank}</span>
            <div>
              <p className="text-sm font-semibold text-slate-200">Candidate Detail</p>
              <p className="text-xs text-slate-500 mt-0.5">Explainable Ranking Analysis</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">

          {/* ── Overview ── */}
          <Section title="Overview">
            <div className="space-y-2">
              <div>
                <p className="text-xs text-slate-500 mb-0.5">Forward (5'→3')</p>
                <code className="text-violet-300 font-mono text-xs break-all">{primer.forward_primer}</code>
              </div>
              {primer.probe_sequence && (
                <div>
                  <p className="text-xs text-slate-500 mb-0.5">Probe (5'→3')</p>
                  <code className="text-amber-300 font-mono text-xs break-all">{primer.probe_sequence}</code>
                </div>
              )}
              <div>
                <p className="text-xs text-slate-500 mb-0.5">Reverse (5'→3')</p>
                <code className="text-cyan-300 font-mono text-xs break-all">{primer.reverse_primer}</code>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
                {tmFwd != null && (
                  <span className="text-xs text-slate-400">
                    Tm F: <span className="text-violet-300">{tmFwd.toFixed(1)}°C</span>
                  </span>
                )}
                {primer.tm_probe != null && (
                  <span className="text-xs text-slate-400">
                    Tm P: <span className="text-amber-300">{primer.tm_probe.toFixed(1)}°C</span>
                  </span>
                )}
                {tmRev != null && (
                  <span className="text-xs text-slate-400">
                    Tm R: <span className="text-cyan-300">{tmRev.toFixed(1)}°C</span>
                  </span>
                )}
                {primer.product_size != null && (
                  <span className="text-xs text-slate-400">
                    Size: <span className="text-slate-300">{primer.product_size} bp</span>
                  </span>
                )}
                {primer.gc != null && (
                  <span className="text-xs text-slate-400">
                    GC: <span className="text-slate-300">{primer.gc.toFixed(0)}%</span>
                  </span>
                )}
              </div>
            </div>
          </Section>

          {/* ── Score Breakdown ── */}
          <Section title="Score Breakdown">
            <div className="space-y-2">
              {[
                { label: "Coverage",      value: xpr.scoreBreakdown.coverageContribution,  max: 60,   color: "bg-blue-500"    },
                { label: "Thermodynamic", value: xpr.scoreBreakdown.thermoContribution,    max: 20,   color: "bg-violet-500"  },
                { label: "AI Efficiency", value: xpr.scoreBreakdown.aiContribution,        max: 20,   color: "bg-cyan-500"    },
              ].map(row => (
                <div key={row.label} className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 w-28 flex-shrink-0">{row.label}</span>
                  <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${row.color}`}
                      style={{ width: `${(row.value / row.max) * 100}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-300 w-10 text-right font-mono">
                    +{row.value.toFixed(1)}
                  </span>
                </div>
              ))}
              {xpr.scoreBreakdown.bonus !== 0 && (
                <div className="flex items-center gap-3">
                  <span className="text-xs text-emerald-400 w-28">Bonus</span>
                  <div className="flex-1" />
                  <span className="text-xs text-emerald-400 w-10 text-right font-mono">+{xpr.scoreBreakdown.bonus}</span>
                </div>
              )}
              {xpr.scoreBreakdown.penalty !== 0 && (
                <div className="flex items-center gap-3">
                  <span className="text-xs text-red-400 w-28">Penalty</span>
                  <div className="flex-1" />
                  <span className="text-xs text-red-400 w-10 text-right font-mono">{xpr.scoreBreakdown.penalty}</span>
                </div>
              )}
              <div className="border-t border-slate-700 pt-2 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300">Final Score</span>
                <span className={`text-sm font-bold ${
                  xpr.scoreBreakdown.finalScore >= 85 ? "text-emerald-400"
                  : xpr.scoreBreakdown.finalScore >= 70 ? "text-amber-400"
                  : "text-red-400"
                }`}>
                  {xpr.scoreBreakdown.finalScore.toFixed(1)}
                </span>
              </div>
            </div>
          </Section>

          {/* ── Strengths ── */}
          {xpr.strengths.length > 0 && (
            <Section title="Strengths">
              <ul className="space-y-1.5">
                {xpr.strengths.map(s => (
                  <li key={s} className="flex items-center gap-2 text-xs text-emerald-300">
                    <span className="text-emerald-400 flex-shrink-0">✓</span>
                    {s}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* ── Weaknesses ── */}
          {xpr.weaknesses.length > 0 && (
            <Section title="Weaknesses">
              <ul className="space-y-1.5">
                {xpr.weaknesses.map(w => (
                  <li key={w} className="flex items-center gap-2 text-xs text-amber-300">
                    <span className="text-amber-400 flex-shrink-0">⚠</span>
                    {w}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* ── Risk Summary ── */}
          <Section title="Risk Summary">
            <div className="space-y-2">
              {[
                { label: "Variant Risk",  level: xpr.riskSummary.variantRisk  },
                { label: "Thermo Risk",   level: xpr.riskSummary.thermoRisk   },
                { label: "Coverage Risk", level: xpr.riskSummary.coverageRisk },
              ].map(row => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">{row.label}</span>
                  <RiskBadge level={row.level} />
                </div>
              ))}
              <div className="border-t border-slate-700 pt-2 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300">Overall Risk</span>
                <RiskBadge level={xpr.riskSummary.overall} />
              </div>
              <p className="text-xs text-slate-500 mt-1">{xpr.riskSummary.message}</p>
            </div>
          </Section>

          {/* ── Recommendation ── */}
          <Section title="Recommendation">
            <p className={`text-sm font-semibold ${recColor[xpr.recommendationLevel]}`}>
              {xpr.recommendationLevel === "high" && "⭐ "}
              {xpr.recommendationLevel === "recommended" && "✓ "}
              {xpr.recommendationLevel === "consider" && "△ "}
              {xpr.recommendationLevel === "low" && "↓ "}
              {xpr.recommendation}
            </p>
          </Section>

          {/* ── Why Ranked ── */}
          <Section title={`Why Ranked #${rank}`}>
            {rank === 1 ? (
              <>
                <p className="text-xs text-slate-400 mb-2">This candidate ranked first because:</p>
                <ul className="space-y-1.5">
                  {xpr.whyRanked.map(r => (
                    <li key={r} className="flex items-center gap-2 text-xs text-slate-300">
                      <span className="text-violet-400 flex-shrink-0">•</span>
                      {r}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-xs text-slate-400">
                This candidate ranked #{rank}. See Comparison for details vs #1.
              </p>
            )}
          </Section>

          {/* ── Comparison ── */}
          {xpr.comparisonSummary && (
            <Section title={`Comparison vs #${xpr.comparisonSummary.vsRank}`}>
              <p className="text-xs text-slate-400 mb-2">
                {rank === 1 ? "Candidate #1 ranked higher because:" : "Candidate #1 ranked higher because:"}
              </p>
              <ul className="space-y-1.5 mb-2">
                {xpr.comparisonSummary.lines.map(l => (
                  <li key={l} className="flex items-center gap-2 text-xs text-blue-300">
                    <span className="text-blue-400 flex-shrink-0">+</span>
                    {l}
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between border-t border-slate-700 pt-2">
                <span className="text-xs text-slate-500">Score difference</span>
                <span className="text-xs font-mono text-emerald-400">
                  +{xpr.comparisonSummary.scoreDiff.toFixed(1)}
                </span>
              </div>
            </Section>
          )}

          {/* ── Radar Chart ── */}
          <Section title="Radar Chart">
            <RadarChart values={xpr.radar} />
            <div className="grid grid-cols-3 gap-x-4 gap-y-1 mt-2 px-2">
              {Object.entries(xpr.radar).map(([key, val]) => {
                const labels: Record<string, string> = {
                  coverage: "Coverage", thermodynamics: "Thermo", gcQuality: "GC Quality",
                  ampliconQuality: "Amplicon", riskProfile: "Risk Profile", aiEfficiency: "AI",
                };
                return (
                  <div key={key} className="text-center">
                    <p className="text-xs text-slate-500">{labels[key]}</p>
                    <p className="text-xs font-mono text-slate-300">{Math.round(val)}</p>
                  </div>
                );
              })}
            </div>
          </Section>

        </div>
      </div>
    </>
  );
}
