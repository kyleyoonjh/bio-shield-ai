import { useEffect, useState, useMemo } from "react";
import { SeqViz } from "seqviz";
import type { BioContextResponse, DiseaseType, Mutation } from "../types";

const NCBI_BASE = "https://www.ncbi.nlm.nih.gov/nuccore/";

// Converts absolute genome position → relative position within the fetched window
function toRelative(absPos: number, seqStart: number): number {
  return absPos - seqStart;
}

// SeqViz annotation color for mutations
const MUTATION_COLOR = "#ef4444"; // red-500

interface Props {
  disease: DiseaseType;
  mutations: Mutation[];
  mutationsLoading?: boolean;
  variantLabel?: string; // undefined = Wild-Type
}

export default function DnaSequenceView({ disease, mutations, mutationsLoading, variantLabel }: Props) {
  const [ctx, setCtx]         = useState<BioContextResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    setCtx(null);
    setError(null);
    setLoading(true);
    fetch(`/api/v1/bio-context?disease_type=${encodeURIComponent(disease)}`)
      .then(r => {
        if (!r.ok) throw new Error(`NCBI fetch failed (HTTP ${r.status})`);
        return r.json();
      })
      .then((data: BioContextResponse) => setCtx(data))
      .catch(e => setError(e instanceof Error ? e.message : "Unknown error"))
      .finally(() => setLoading(false));
  }, [disease]);

  // SeqViz annotation window start (matches DISEASE_TARGETS seq_start)
  // Infer from annotation positions + sequence
  const seqWindowStart = useMemo(() => {
    if (!ctx || ctx.annotations.length === 0) return 0;
    // Back-calculate: for primer annotations we know abs_start from disease config.
    // We store it indirectly — just use accession to pick the right offset.
    const offsets: Record<string, number> = {
      "NC_045512.2": 15400,
      "NC_001526.4": 540,
      "AE001273.1":  400,
    };
    return offsets[ctx.accession] ?? 0;
  }, [ctx]);

  // Mutation annotations that fall within the displayed window
  const mutationAnnotations = useMemo(() => {
    if (!ctx) return [];
    const windowEnd = seqWindowStart + ctx.rdrp_sequence.length;
    return mutations
      .filter(m => m.position >= seqWindowStart && m.position < windowEnd)
      .map(m => ({
        name:      m.effect,
        start:     toRelative(m.position, seqWindowStart),
        end:       toRelative(m.position, seqWindowStart) + Math.max(m.ref.length, 1),
        direction: 1 as 1 | -1,
        color:     MUTATION_COLOR,
      }));
  }, [mutations, ctx, seqWindowStart]);

  const allAnnotations = useMemo(() => {
    if (!ctx) return [];
    return [
      ...ctx.annotations.map(a => ({
        name:      a.name,
        start:     a.start,
        end:       a.end,
        direction: a.strand as 1 | -1,
        color:     a.color,
      })),
      ...mutationAnnotations,
    ];
  }, [ctx, mutationAnnotations]);

  return (
    <div className="space-y-5">

      {/* Source badge */}
      {ctx && ctx.source !== "ncbi" && (
        <div className={`px-4 py-2 rounded-lg text-xs flex items-center gap-2 ${
          ctx.source === "cache"
            ? "bg-blue-50 border border-blue-200 text-blue-800"
            : "bg-amber-50 border border-amber-300 text-amber-800"
        }`}>
          <span className="font-bold">{ctx.source === "cache" ? "ℹ" : "⚠"}</span>
          {ctx.source === "cache"
            ? "NCBI 연결 실패 — 이전에 저장된 캐시 데이터를 표시합니다."
            : "NCBI 연결 실패 · 캐시 없음 — 내장 대표 서열을 표시합니다. 실제 서열과 다를 수 있습니다."}
        </div>
      )}

      {/* Variant mutation banner — 항상 표시 (로딩 중에도) */}
      {variantLabel && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-center gap-3">
          <span className="text-red-500 text-base leading-none">●</span>
          <span className="font-semibold text-red-800 text-sm">{variantLabel}</span>

          {mutationsLoading ? (
            <div className="flex items-center gap-2 text-xs text-red-600">
              <span className="w-3.5 h-3.5 border-2 border-red-400 border-t-transparent rounded-full animate-spin inline-block" />
              변이 데이터 로딩 중...
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-red-700">— {mutations.length}개 변이</span>
              {mutationAnnotations.length > 0 && (
                <span className="text-xs bg-red-100 border border-red-200 text-red-700 rounded px-2 py-0.5">
                  현재 창 내 {mutationAnnotations.length}개 하이라이트
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center gap-3 py-16 text-slate-500">
          <span className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin inline-block" />
          <span className="text-sm">NCBI GenBank에서 실제 서열을 가져오는 중...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      {/* Results */}
      {ctx && !loading && (
        <>
          {/* SeqViz */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-widest">
                Linear Sequence Map · NCBI E-utilities 실시간
              </h3>
              <span className="text-xs font-mono text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">
                {ctx.accession}
              </span>
            </div>
            <div className="p-5">
              <div className="border rounded-lg overflow-hidden bg-gray-50">
                <SeqViz
                  name={`${ctx.assay_info.organism} — ${ctx.assay_info.target_gene}`}
                  seq={ctx.rdrp_sequence}
                  annotations={allAnnotations}
                  viewer="linear"
                  showComplement={false}
                  style={{ height: "220px", width: "100%" }}
                />
              </div>

              {/* Legend */}
              <div className="flex flex-wrap gap-4 mt-4">
                {ctx.annotations.map(a => (
                  <div key={a.name} className="flex items-center gap-2 text-xs text-slate-600">
                    <span className="w-3 h-3 rounded shrink-0" style={{ backgroundColor: a.color }} />
                    <span>{a.name}: {a.start + 1}–{a.end} bp</span>
                  </div>
                ))}
                {mutationAnnotations.length > 0 && (
                  <div className="flex items-center gap-2 text-xs text-red-700">
                    <span className="w-3 h-3 rounded shrink-0 bg-red-500" />
                    <span>변이 위치 ({mutationAnnotations.length})</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Assay info + Primer stats */}
          <div className="grid sm:grid-cols-2 gap-5">
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50">
                <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-widest">Assay 정보</h3>
              </div>
              <div className="p-5 space-y-2 text-sm">
                {[
                  ["대상 유전자", ctx.assay_info.target_gene],
                  ["대상 병원체", ctx.assay_info.organism],
                  ["Assay 유형", ctx.assay_info.assay_type],
                  ["적용 표준",  ctx.assay_info.standard],
                  ["서열 길이",  `${ctx.rdrp_sequence.length} bp`],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4">
                    <span className="text-slate-500 shrink-0">{k}</span>
                    <span className="font-semibold text-slate-700 text-right">{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50">
                <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-widest">
                  Forward Primer (primer3-py)
                </h3>
              </div>
              <div className="p-5 space-y-3">
                <div className="grid grid-cols-3 gap-3 text-center">
                  {[
                    ["Tm",     ctx.primer_structure.tm_celsius != null ? `${ctx.primer_structure.tm_celsius}°C` : "N/A"],
                    ["GC%",   `${ctx.primer_structure.gc_percent}%`],
                    ["Length",`${ctx.primer_structure.length} nt`],
                  ].map(([k, v]) => (
                    <div key={k} className="bg-slate-50 rounded-lg p-3">
                      <p className="text-xs text-slate-500 mb-1">{k}</p>
                      <p className="font-bold text-slate-800 text-sm">{v}</p>
                    </div>
                  ))}
                </div>
                <p className="text-xs font-mono text-slate-500 bg-slate-50 px-3 py-2 rounded-lg break-all">
                  {ctx.primer_structure.sequence}
                </p>
                {ctx.primer_structure.dot_bracket == null ? (
                  <div className="bg-slate-100 border border-slate-200 rounded-lg px-4 py-2 text-xs text-slate-500 text-center">
                    2차 구조 — Primer 탭에서 확인
                  </div>
                ) : (
                  <p className="font-mono text-xs text-slate-600 break-all">{ctx.primer_structure.dot_bracket}</p>
                )}
              </div>
            </div>
          </div>

          {/* Mutation table */}
          {mutations.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 bg-red-50 flex items-center gap-2">
                <h3 className="text-xs font-semibold text-red-700 uppercase tracking-widest">
                  변이 목록 — {variantLabel}
                </h3>
                <span className="text-xs bg-red-100 border border-red-200 text-red-700 rounded-full px-2 py-0.5 font-bold">
                  {mutations.length}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-slate-500 uppercase tracking-widest">
                    <tr>
                      {["Gene", "Position (abs)", "Ref", "Alt", "Effect", "In View"].map(h => (
                        <th key={h} className="px-4 py-2 text-left font-semibold">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {mutations.map((m, i) => {
                      const inWindow =
                        m.position >= seqWindowStart &&
                        m.position < seqWindowStart + ctx.rdrp_sequence.length;
                      return (
                        <tr key={i} className={inWindow ? "bg-red-50" : ""}>
                          <td className="px-4 py-2 font-mono font-semibold text-slate-700">{m.gene}</td>
                          <td className="px-4 py-2 font-mono text-slate-600">{m.position.toLocaleString()}</td>
                          <td className="px-4 py-2 font-mono text-emerald-700">{m.ref || "—"}</td>
                          <td className="px-4 py-2 font-mono text-red-600">{m.alt === "-" ? "del" : m.alt}</td>
                          <td className="px-4 py-2 text-slate-700">{m.effect}</td>
                          <td className="px-4 py-2">
                            {inWindow
                              ? <span className="text-red-600 font-bold">●</span>
                              : <span className="text-slate-300">—</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Source citation */}
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">데이터 출처 (Data Sources)</p>
            <div className="space-y-2 text-xs text-slate-600">
              <div className="flex items-start gap-2">
                <span className="shrink-0 font-semibold text-slate-700 w-28">유전체 서열</span>
                <span>
                  NCBI GenBank&nbsp;
                  <a href={`${NCBI_BASE}${ctx.accession}`} target="_blank" rel="noopener noreferrer"
                    className="text-blue-600 hover:underline font-mono">
                    {ctx.accession}
                  </a>
                  &nbsp;— {ctx.assay_info.organism}, {ctx.assay_info.target_gene} region
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="shrink-0 font-semibold text-slate-700 w-28">Primer 수치</span>
                <span>SantaLucia (1998) nearest-neighbor via primer3-py · GC% 직접 계산</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="shrink-0 font-semibold text-slate-700 w-28">변이 데이터</span>
                <span>NCBI Virus, WHO VOC 보고서, 공개 문헌 기반 (published mutation coordinates)</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="shrink-0 font-semibold text-slate-700 w-28">서열 취득</span>
                <span>
                  {ctx.source === "ncbi"
                    ? "NCBI E-utilities efetch API · 실시간"
                    : ctx.source === "cache"
                    ? "디스크 캐시 (이전 NCBI 성공 결과)"
                    : "내장 대표 서열 (캐시 없음)"}
                </span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
