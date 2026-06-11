import { useEffect, useState, useMemo } from "react";
import type { BioContextResponse, DiseaseType, Mutation } from "../types";

// ─── Arc Diagram ──────────────────────────────────────────────────────────────

function parsePairs(dotBracket: string): [number, number][] {
  const pairs: [number, number][] = [];
  const stack: number[] = [];
  for (let i = 0; i < dotBracket.length; i++) {
    if (dotBracket[i] === "(") stack.push(i);
    else if (dotBracket[i] === ")") {
      const j = stack.pop();
      if (j !== undefined) pairs.push([j, i]);
    }
  }
  return pairs;
}

const BASE_COLORS: Record<string, string> = {
  A: "#4CAF50", T: "#2196F3", G: "#FF9800", C: "#E91E63",
};

function ArcDiagram({ sequence, dotBracket }: { sequence: string; dotBracket: string }) {
  const pairs = useMemo(() => parsePairs(dotBracket), [dotBracket]);
  const n = sequence.length;

  const BASE_R = 10;
  const SPACING = 24;
  const svgWidth = n * SPACING + 20;
  const maxArcH = Math.max(...pairs.map(([i, j]) => ((j - i) * SPACING) / 2), 0);
  const svgHeight = maxArcH + BASE_R * 2 + 36;

  const cx = (i: number) => 10 + i * SPACING + BASE_R;
  const baselineY = svgHeight - BASE_R - 4;

  const pairedSet = useMemo(() => new Set(pairs.flatMap(([i, j]) => [i, j])), [pairs]);

  return (
    <div className="overflow-x-auto">
      <svg
        width={svgWidth}
        height={svgHeight}
        className="font-mono"
        style={{ minWidth: svgWidth }}
      >
        {/* Arcs */}
        {pairs.map(([i, j]) => {
          const x1 = cx(i);
          const x2 = cx(j);
          const midX = (x1 + x2) / 2;
          const arcH = ((j - i) * SPACING) / 2;
          const ctrlY = baselineY - arcH;
          return (
            <path
              key={`${i}-${j}`}
              d={`M ${x1} ${baselineY} Q ${midX} ${ctrlY} ${x2} ${baselineY}`}
              fill="none"
              stroke="#94a3b8"
              strokeWidth={1.5}
              opacity={0.7}
            />
          );
        })}

        {/* Base circles */}
        {sequence.split("").map((base, i) => {
          const x = cx(i);
          const isPaired = pairedSet.has(i);
          const color = BASE_COLORS[base.toUpperCase()] ?? "#9ca3af";
          return (
            <g key={i}>
              <circle
                cx={x} cy={baselineY}
                r={BASE_R}
                fill={isPaired ? color : "#f1f5f9"}
                stroke={isPaired ? color : "#cbd5e1"}
                strokeWidth={1.5}
              />
              <text
                x={x} y={baselineY + 1}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={9}
                fontWeight="bold"
                fill={isPaired ? "#fff" : "#64748b"}
              >
                {base.toUpperCase()}
              </text>
              {/* dot-bracket char below */}
              <text
                x={x} y={baselineY + BASE_R + 10}
                textAnchor="middle"
                fontSize={8}
                fill="#94a3b8"
              >
                {dotBracket[i]}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface Props {
  disease: DiseaseType;
  mutations?: Mutation[];
  variantLabel?: string;
}

export default function PrimerStructure({ disease, mutations = [], variantLabel }: Props) {
  const [ctx, setCtx]         = useState<BioContextResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    setCtx(null);
    setError(null);
    setLoading(true);
    fetch(`/api/v1/bio-context?disease_type=${encodeURIComponent(disease)}`)
      .then(r => {
        if (!r.ok) throw new Error(`API error (HTTP ${r.status})`);
        return r.json();
      })
      .then((data: BioContextResponse) => setCtx(data))
      .catch(e => setError(e instanceof Error ? e.message : "Unknown error"))
      .finally(() => setLoading(false));
  }, [disease]);

  if (loading) return (
    <div className="flex items-center justify-center gap-3 py-20 text-slate-500">
      <span className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin inline-block" />
      <span className="text-sm">프라이머 구조 분석 중 (ViennaRNA)...</span>
    </div>
  );

  if (error) return (
    <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
  );

  if (!ctx) return null;

  const ps = ctx.primer_structure;
  const hasFolding = ps.dot_bracket != null;

  return (
    <div className="space-y-6">

      {/* Variant context banner */}
      {variantLabel && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-center gap-3">
          <span className="text-red-500">●</span>
          <span className="font-semibold text-red-800 text-sm">{variantLabel}</span>
          {mutations.length > 0 ? (
            <span className="text-sm text-red-700">
              — {mutations.length}개 변이 존재.
              프라이머 결합 특이성에 영향을 줄 수 있습니다.
            </span>
          ) : (
            <span className="text-sm text-red-600">— 이 변이주의 변이 데이터 없음</span>
          )}
        </div>
      )}

      {/* Source notice — demo mode 는 DemoBanner 가 커버하므로 숨김 */}
      {ctx.source !== "ncbi" && ctx.source !== "demo" && (
        <div className={`px-4 py-2 rounded-lg text-xs flex items-center gap-2 ${
          ctx.source === "cache"
            ? "bg-blue-50 border border-blue-200 text-blue-800"
            : "bg-amber-50 border border-amber-300 text-amber-800"
        }`}>
          <span className="font-bold">{ctx.source === "cache" ? "ℹ" : "⚠"}</span>
          {ctx.source === "cache"
            ? "NCBI 연결 실패 — 이전에 저장된 캐시 데이터를 표시합니다."
            : "NCBI 연결 실패 · 캐시 없음 — 내장 대표 서열을 표시합니다."}
        </div>
      )}

      {/* Assay info banner */}
      <div className="bg-blue-900 rounded-xl p-4 text-white">
        <p className="text-xs font-semibold text-blue-300 uppercase tracking-widest mb-1">Assay 정보</p>
        <p className="font-bold text-white">{ctx.assay_info.organism} — {ctx.assay_info.target_gene}</p>
        <p className="text-xs text-blue-300 mt-0.5 font-mono">{ctx.accession} · {ctx.assay_info.assay_type}</p>
      </div>

      {/* Metrics */}
      <div className="grid sm:grid-cols-4 gap-4">
        <MetricCard label="Melting Temp (Tm)"
          value={ps.tm_celsius != null ? `${ps.tm_celsius}°C` : "N/A"} />
        <MetricCard label="GC Content" value={`${ps.gc_percent}%`} />
        <MetricCard label="Length" value={`${ps.length} nt`} />
        <MetricCard
          label="ΔG (MFE)"
          value={ps.mfe != null ? `${ps.mfe} kcal/mol` : "N/A"}
          highlight={ps.mfe != null && ps.mfe < -2}
        />
      </div>

      {/* Sequence */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Forward Primer 서열</h3>
        <p className="font-mono text-sm bg-slate-50 p-4 rounded-lg break-all text-slate-700">{ps.sequence}</p>
        <p className="text-xs text-slate-400 mt-2">Length: {ps.length} nt · IUPAC 표기 포함</p>
      </div>

      {/* Secondary structure */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest">
            2차 구조 (ViennaRNA · RNAfold)
          </h3>
          {hasFolding && ps.mfe != null && (
            <span className={`text-xs font-mono px-2.5 py-1 rounded-full border font-semibold ${
              ps.mfe < -3
                ? "bg-red-50 border-red-200 text-red-700"
                : ps.mfe < -1
                ? "bg-amber-50 border-amber-200 text-amber-700"
                : "bg-emerald-50 border-emerald-200 text-emerald-700"
            }`}>
              ΔG = {ps.mfe} kcal/mol
            </span>
          )}
        </div>

        {!hasFolding ? (
          <div className="bg-slate-50 border border-slate-200 rounded-lg px-5 py-6 text-center">
            <p className="text-sm text-slate-500">ViennaRNA를 설치하면 구조 예측이 가능합니다.</p>
            <code className="text-xs text-slate-400 mt-1 block">pip install ViennaRNA</code>
          </div>
        ) : (
          <>
            {/* Dot-bracket */}
            <div className="mb-5 space-y-1">
              <p className="text-xs text-slate-400 uppercase tracking-widest font-semibold">Dot-Bracket Notation</p>
              <p className="font-mono text-sm bg-slate-50 p-3 rounded-lg break-all text-slate-600">
                {ps.dot_bracket}
              </p>
            </div>

            {/* Arc diagram */}
            <div className="mb-4">
              <p className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-3">Arc Diagram</p>
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
                <ArcDiagram sequence={ps.sequence} dotBracket={ps.dot_bracket!} />
              </div>
            </div>

            {/* Legend */}
            <div className="flex flex-wrap gap-4 text-xs text-slate-500 mt-3">
              {["A", "T", "G", "C"].map(b => (
                <span key={b} className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full inline-block"
                    style={{ backgroundColor: BASE_COLORS[b] }} />
                  {b} {b === "A" ? "(adenine)" : b === "T" ? "(thymine)" : b === "G" ? "(guanine)" : "(cytosine)"}
                </span>
              ))}
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-full bg-slate-100 border border-slate-300 inline-block" />
                unpaired
              </span>
            </div>

            {/* Interpretation */}
            {ps.mfe != null && (
              <div className={`mt-5 rounded-lg px-4 py-3 text-xs ${
                ps.mfe < -3
                  ? "bg-red-50 border border-red-200 text-red-700"
                  : ps.mfe < -1
                  ? "bg-amber-50 border border-amber-200 text-amber-700"
                  : "bg-emerald-50 border border-emerald-200 text-emerald-700"
              }`}>
                <span className="font-semibold">구조 안정성: </span>
                {ps.mfe < -3
                  ? `ΔG ${ps.mfe} kcal/mol — 강한 hairpin 형성 가능. 프라이머 효율 저하 주의.`
                  : ps.mfe < -1
                  ? `ΔG ${ps.mfe} kcal/mol — 약한 hairpin. 일반적으로 허용 범위 (> -2 kcal/mol 권장).`
                  : `ΔG ${ps.mfe} kcal/mol — 안정적인 선형 구조. Hairpin 위험 낮음.`}
              </div>
            )}
          </>
        )}
      </div>

      {/* Source */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">데이터 출처</p>
        <div className="space-y-1 text-xs text-slate-500">
          <p><span className="font-semibold text-slate-600">2차 구조: </span>
            ViennaRNA RNAfold · Zuker-Stiegler MFE algorithm (2007)</p>
          <p><span className="font-semibold text-slate-600">Tm: </span>
            SantaLucia (1998) nearest-neighbor via primer3-py</p>
          <p><span className="font-semibold text-slate-600">서열: </span>
            NCBI GenBank&nbsp;
            <a href={`https://www.ncbi.nlm.nih.gov/nuccore/${ctx.accession}`}
              target="_blank" rel="noopener noreferrer"
              className="text-blue-600 hover:underline font-mono">
              {ctx.accession}
            </a>
            {ctx.source !== "ncbi" && ` (${ctx.source === "cache" ? "캐시" : "내장 서열"})`}
          </p>
          <p><span className="font-semibold text-slate-600">표준: </span>{ctx.assay_info.standard}</p>
        </div>
      </div>

    </div>
  );
}

function MetricCard({ label, value, highlight = false }: {
  label: string; value: string; highlight?: boolean;
}) {
  return (
    <div className={`rounded-xl shadow-sm border p-5 ${
      highlight ? "bg-red-50 border-red-200" : "bg-white border-slate-200"
    }`}>
      <p className={`text-xs font-medium uppercase tracking-wider ${
        highlight ? "text-red-500" : "text-slate-500"
      }`}>{label}</p>
      <p className={`text-xl font-bold mt-2 ${highlight ? "text-red-700" : "text-slate-800"}`}>{value}</p>
    </div>
  );
}
