import { useState, useEffect, useMemo } from "react";
import type { BioContextResponse, DiseaseType, Mutation, RiskLevel } from "../types";

// ─── In-Silico Alignment Engine ───────────────────────────────────────────────
//
// Model: forward primer bound to antisense (template) strand.
//   Primer row  (5′→3′): primer sequence as-is
//   Target row  (3′→5′): antisense strand — comp(sense base) at each position
//   Mismatch:   mutation reported on the sense strand (ref→alt)
//               → antisense changes from comp(ref) to comp(alt)
//               → primer[i]=ref no longer pairs with comp(alt) when alt≠ref

const WC_COMP: Record<string, string> = {
  A: "T", T: "A", G: "C", C: "G",
  a: "t", t: "a", g: "c", c: "g",
};

// Full IUPAC complement table for display in target row
const IUPAC_COMP: Record<string, string> = {
  ...WC_COMP,
  R: "Y", Y: "R",   // purine↔pyrimidine
  S: "S", W: "W",   // strong/weak are self-complementary
  K: "M", M: "K",
  B: "V", V: "B",
  D: "H", H: "D",
  N: "N",
};

function compBase(b: string): string {
  return IUPAC_COMP[b.toUpperCase()] ?? "N";
}

// Watson-Crick strict match (handles IUPAC degeneracy in primer: treat as match)
function isWatsonCrick(primerBase: string, templateBase: string): boolean {
  const p = primerBase.toUpperCase();
  const t = templateBase.toUpperCase();
  // IUPAC ambiguity in primer = intentional degeneracy → treat as matching
  if (!"ACGT".includes(p)) return true;
  return (
    (p === "A" && t === "T") ||
    (p === "T" && t === "A") ||
    (p === "G" && t === "C") ||
    (p === "C" && t === "G")
  );
}

// ─── Primer genomic position resolution ──────────────────────────────────────
//
// Priority:
//  1. API: primer_structure.abs_start  (added to ncbi_service.py _build_response)
//  2. API: seq_start + annotations[0].start  (relative → absolute)
//  3. Hardcoded per-disease fallback (matches DISEASE_TARGETS in ncbi_service.py)

const PRIMER_ABS_FALLBACK: Record<string, number> = {
  "SARS-CoV-2": 15431,   // RdRp_Fwd abs_start (WHO EUL)
  "HPV":        562,     // E7_Fwd abs_start
  "STI":        410,     // ompA_Fwd abs_start
};

function resolvePrimerAbsStart(bioCtx: BioContextResponse): number {
  // ① Direct from API (most reliable)
  if (bioCtx.primer_structure.abs_start != null) {
    return bioCtx.primer_structure.abs_start;
  }
  // ② seq_start (genomic base of rdrp_sequence[0]) + first annotation's relative offset
  if (bioCtx.seq_start != null && bioCtx.annotations.length > 0) {
    return bioCtx.seq_start + bioCtx.annotations[0].start;
  }
  // ③ Hardcoded per-disease
  return PRIMER_ABS_FALLBACK[bioCtx.disease_type] ?? 1;
}

// ─── AlignmentData ────────────────────────────────────────────────────────────

interface MappedMutation {
  primerIdx: number;      // 0-based offset from primer start
  genomicPos: number;     // absolute genomic position
  ref: string;
  alt: string;
}

interface AlignmentData {
  primerBases: string[];     // primer sequence characters
  targetBases: string[];     // template strand (antisense), variant-adjusted
  matchFlags: boolean[];     // true = Watson-Crick paired
  primerAbsStart: number;    // absolute genomic start
  primerAbsEnd: number;      // absolute genomic end (inclusive)
  totalMutations: number;    // total mutations passed in
  mappedMutations: MappedMutation[];  // only those overlapping primer region
  inPrimerMismatchCount: number;
  threePrimeMismatch: boolean;
}

// Zone boundaries (distance from primer 3' end)
const CRITICAL_DIST = 3;   // distance 0–3 bp → last 4 bases → critical
const WARNING_DIST  = 15;  // distance 4–15 bp → primer body → warning

function primerZone(idxFromStart: number, primerLength: number): "critical" | "warning" | "normal" {
  const distFrom3 = primerLength - 1 - idxFromStart;
  if (distFrom3 <= CRITICAL_DIST) return "critical";
  if (distFrom3 <= WARNING_DIST)  return "warning";
  return "normal";
}

function computeAlignmentData(
  primerSeq: string,
  mutations: Mutation[],
  bioCtx: BioContextResponse | null,
): AlignmentData {
  const primerAbsStart = bioCtx ? resolvePrimerAbsStart(bioCtx) : (PRIMER_ABS_FALLBACK["SARS-CoV-2"] ?? 1);
  const primerLength   = primerSeq.length;
  const primerAbsEnd   = primerAbsStart + primerLength - 1;

  // Build lookup: genomicPos → {ref, alt}  (only those within primer span)
  const mutLookup = new Map<number, { ref: string; alt: string }>();
  for (const m of mutations) {
    if (m.position >= primerAbsStart && m.position <= primerAbsEnd) {
      mutLookup.set(m.position, { ref: m.ref, alt: m.alt });
    }
  }

  const primerBases: string[] = [];
  const targetBases: string[] = [];
  const matchFlags:  boolean[] = [];
  const mappedMutations: MappedMutation[] = [];

  for (let i = 0; i < primerLength; i++) {
    const primerBase = primerSeq[i].toUpperCase();
    const genomicPos = primerAbsStart + i;
    const mut = mutLookup.get(genomicPos);

    primerBases.push(primerBase);

    let targetBase: string;
    if (mut) {
      // Template (antisense) shows complement of the ALT sense-strand base
      targetBase = compBase(mut.alt);
      mappedMutations.push({ primerIdx: i, genomicPos, ref: mut.ref, alt: mut.alt });
    } else {
      // Perfect complement (no mutation at this position)
      targetBase = compBase(primerBase);
    }

    targetBases.push(targetBase);
    matchFlags.push(isWatsonCrick(primerBase, targetBase));
  }

  const inPrimerMismatchCount = matchFlags.filter(f => !f).length;
  const threePrimeMismatch    = matchFlags.slice(-(CRITICAL_DIST + 1)).some(f => !f);

  return {
    primerBases, targetBases, matchFlags,
    primerAbsStart, primerAbsEnd,
    totalMutations: mutations.length,
    mappedMutations,
    inPrimerMismatchCount,
    threePrimeMismatch,
  };
}

// ─── PFPS result (from /api/v2/pfps) ─────────────────────────────────────────
//
// Layer 1 (deterministic) → risk_level, score, meta_metrics
// Layer 2 (GPT-4o narrator) → reason  (never changes risk_level / score)

interface PfpsResult {
  risk_level: RiskLevel;
  score: number;
  reason: string;         // GPT-4o clinical report
  meta_metrics: {
    is_critical_override: boolean;
    cv_escalated:         boolean;
    trigger_rule_summary: string;
  };
}

const RISK_CFG: Record<RiskLevel, {
  label: string; badge: string; glow: string; border: string; accentText: string; icon: string;
}> = {
  HIGH:   { label: "고위험 (HIGH)",   badge: "bg-red-500",     glow: "shadow-red-500/40",     border: "border-red-500",     accentText: "text-red-400",     icon: "!" },
  MEDIUM: { label: "중위험 (MEDIUM)", badge: "bg-amber-500",   glow: "shadow-amber-500/40",   border: "border-amber-400",   accentText: "text-amber-400",   icon: "~" },
  LOW:    { label: "저위험 (LOW)",    badge: "bg-emerald-500", glow: "shadow-emerald-500/40", border: "border-emerald-500", accentText: "text-emerald-400", icon: "✓" },
};

// ─── SequenceAlignmentView ────────────────────────────────────────────────────

function SequenceAlignmentView({
  alignment, loading,
}: {
  alignment: AlignmentData | null;
  loading: boolean;
}) {
  const MAX_SHOW = 30;

  if (loading) {
    return (
      <div className="bg-slate-950 rounded-xl p-5 flex items-center justify-center gap-3 h-44 border border-slate-800">
        <span className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-slate-500 font-mono">Fetching genomic sequence…</span>
      </div>
    );
  }

  if (!alignment || alignment.primerBases.length === 0) {
    return (
      <div className="bg-slate-950 rounded-xl p-5 flex items-center justify-center h-44 text-slate-600 font-mono text-xs border border-slate-800">
        Primer sequence unavailable
      </div>
    );
  }

  const { primerBases, targetBases, matchFlags, primerAbsStart, primerAbsEnd,
          mappedMutations, inPrimerMismatchCount, threePrimeMismatch, totalMutations } = alignment;
  const primerLength = primerBases.length;

  // Show at most MAX_SHOW bases, biased toward the 3' end
  const displayStart = primerLength > MAX_SHOW ? primerLength - MAX_SHOW : 0;
  const truncated    = displayStart > 0;

  return (
    <div className="bg-slate-950 rounded-xl border border-slate-800 overflow-hidden">

      {/* Toolbar */}
      <div className="bg-slate-900/80 px-4 py-2.5 border-b border-slate-800">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-semibold text-slate-400 font-mono">
            In Silico Alignment · {primerLength} nt
            <span className="text-slate-600 ml-1.5 font-normal">
              pos {primerAbsStart.toLocaleString()}–{primerAbsEnd.toLocaleString()}
            </span>
          </span>
          <div className="flex items-center gap-3 text-[10px] text-slate-500">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-red-900/70 ring-1 ring-red-700/50 rounded-sm inline-block" />
              Critical (0–3bp)
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-amber-900/60 rounded-sm inline-block" />
              Warning (4–15bp)
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-red-700/80 rounded-sm inline-block" />
              Mismatch
            </span>
          </div>
        </div>
        {/* Mapping summary */}
        <p className="text-[10px] text-slate-500 mt-1 font-mono">
          전체 변이 {totalMutations}개 중{" "}
          <span className={mappedMutations.length > 0 ? "text-red-400 font-semibold" : "text-emerald-500"}>
            {mappedMutations.length}개
          </span>
          {" "}가 프라이머 구간 내 매핑됨
          {mappedMutations.length > 0 && (
            <span className="ml-1 text-slate-600">
              ({mappedMutations.map(m => `pos ${m.genomicPos.toLocaleString()} ${m.ref}→${m.alt}`).join(", ")})
            </span>
          )}
        </p>
      </div>

      <div className="p-4 overflow-x-auto select-none">

        {/* 5' strand label */}
        <div className="flex items-center gap-1.5 mb-2">
          <span className="text-blue-500 font-mono text-[11px] font-bold">5′</span>
          {truncated && <span className="text-slate-700 font-mono text-[11px]">···</span>}
          <span className="text-slate-600 font-mono text-[11px]">─── Primer ───</span>
          <span className="text-blue-500 font-mono text-[11px] font-bold">3′</span>
        </div>

        {/* Primer bases row */}
        <div className="flex gap-0.5 mb-1">
          {primerBases.slice(displayStart).map((base, i) => {
            const gIdx       = displayStart + i;
            const isMismatch = !matchFlags[gIdx];
            const zone       = primerZone(gIdx, primerLength);
            return (
              <div
                key={i}
                className={`w-[26px] h-7 flex items-center justify-center rounded text-[11px] font-bold font-mono ${
                  isMismatch
                    ? "bg-red-800/70 text-red-200 ring-1 ring-red-500/60"
                    : zone === "critical"
                    ? "bg-red-900/50 text-orange-100 ring-1 ring-red-800/50"
                    : zone === "warning"
                    ? "bg-amber-900/40 text-amber-200"
                    : "bg-slate-700/80 text-slate-200"
                }`}
              >
                {base}
              </div>
            );
          })}
        </div>

        {/* Watson-Crick bond indicators */}
        <div className="flex gap-0.5 mb-1">
          {matchFlags.slice(displayStart).map((isMatch, i) => (
            <div key={i} className="w-[26px] h-4 flex items-center justify-center">
              {isMatch
                ? <span className="text-slate-600 text-[11px] leading-none">│</span>
                : <span className="text-red-400 text-[11px] font-black leading-none">✕</span>
              }
            </div>
          ))}
        </div>

        {/* Target (variant antisense) row */}
        <div className="flex gap-0.5 mb-2">
          {targetBases.slice(displayStart).map((base, i) => {
            const gIdx       = displayStart + i;
            const isMismatch = !matchFlags[gIdx];
            const zone       = primerZone(gIdx, primerLength);
            return (
              <div
                key={i}
                className={`w-[26px] h-7 flex items-center justify-center rounded text-[11px] font-bold font-mono ${
                  isMismatch
                    ? "bg-red-900/60 text-red-400 ring-1 ring-red-600/40"
                    : zone === "critical"
                    ? "bg-red-950/50 text-red-300/70"
                    : zone === "warning"
                    ? "bg-amber-950/30 text-amber-500"
                    : "bg-slate-800/60 text-slate-500"
                }`}
              >
                {base}
              </div>
            );
          })}
        </div>

        {/* Genomic position scale */}
        <div className="flex justify-between text-[9px] text-slate-700 font-mono mb-3">
          <span>pos {(primerAbsStart + displayStart).toLocaleString()}</span>
          <span className="text-slate-800">─── Target (Variant antisense) ───</span>
          <span>pos {primerAbsEnd.toLocaleString()}</span>
        </div>

        {/* 3' strand label */}
        <div className="flex items-center gap-1.5 mb-3">
          <span className="text-slate-500 font-mono text-[11px] font-bold">3′</span>
          {truncated && <span className="text-slate-700 font-mono text-[11px]">···</span>}
          <span className="text-slate-600 font-mono text-[11px]">─── Antisense (Template) ───</span>
          <span className="text-slate-500 font-mono text-[11px] font-bold">5′</span>
        </div>

        {/* Status annotation */}
        {threePrimeMismatch ? (
          <div className="flex items-start gap-2 bg-red-950/50 border border-red-700/40 rounded-lg px-3 py-2">
            <span className="text-red-400 text-sm mt-0.5 shrink-0">⚠</span>
            <div>
              <p className="text-[11px] font-bold text-red-300">3′ Critical Zone 미스매치 감지 (pos {(primerAbsEnd - CRITICAL_DIST).toLocaleString()}–{primerAbsEnd.toLocaleString()})</p>
              <p className="text-[11px] text-red-400/70 mt-0.5 leading-relaxed">
                DNA polymerase extension이 차단될 수 있습니다. 프라이머 재설계 권장.
              </p>
            </div>
          </div>
        ) : inPrimerMismatchCount > 0 ? (
          <div className="flex items-center gap-2 bg-amber-950/30 border border-amber-700/30 rounded-lg px-3 py-2">
            <span className="text-amber-400 text-xs shrink-0">⚡</span>
            <p className="text-[11px] text-amber-300">
              {inPrimerMismatchCount}개 미스매치가 Primer body에 분포 · 3′ 말단 정상 매칭 (Extension 유지)
            </p>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-1 py-1">
            <span className="text-emerald-400 text-xs shrink-0">✓</span>
            <p className="text-[11px] text-emerald-500/80">
              완전 매칭 — 프라이머 구간 {primerLength}nt 내 변이 없음
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── RiskGaugeBar ─────────────────────────────────────────────────────────────

function RiskGaugeBar({
  label, subtitle, value, unit, max, warnAt, criticalAt,
}: {
  label: string; subtitle: string; value: number | null;
  unit: string; max: number; warnAt: number; criticalAt: number;
}) {
  const safeVal = value ?? 0;
  const fillPct = Math.min((safeVal / max) * 100, 100);
  const warnPct = (warnAt / max) * 100;
  const critPct = (criticalAt / max) * 100;

  const fillCls =
    value === null        ? "bg-slate-600"
    : safeVal >= criticalAt ? "bg-gradient-to-r from-red-600 to-red-400"
    : safeVal >= warnAt     ? "bg-gradient-to-r from-amber-500 to-amber-300"
    : "bg-gradient-to-r from-emerald-600 to-emerald-400";

  const badge =
    value === null          ? { text: "미입력", cls: "text-slate-500 bg-slate-700"       }
    : safeVal >= criticalAt ? { text: "위험",   cls: "text-red-300   bg-red-900/60"      }
    : safeVal >= warnAt     ? { text: "경계",   cls: "text-amber-300 bg-amber-900/60"    }
    : { text: "정상",   cls: "text-emerald-300 bg-emerald-900/60" };

  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[12px] font-semibold text-slate-200">{label}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-base font-bold font-mono text-white tabular-nums">
            {value !== null ? `${value}${unit}` : "—"}
          </span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}>
            {badge.text}
          </span>
        </div>
      </div>
      <div className="relative h-3 bg-slate-700 rounded-full overflow-visible">
        <div className="absolute top-1/2 -translate-y-1/2 w-px h-5 bg-amber-400/60 z-10" style={{ left: `${warnPct}%` }}>
          <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[9px] text-amber-500 whitespace-nowrap font-mono">
            {warnAt}{unit}
          </span>
        </div>
        <div className="absolute top-1/2 -translate-y-1/2 w-px h-5 bg-red-400/60 z-10" style={{ left: `${critPct}%` }}>
          <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[9px] text-red-400 whitespace-nowrap font-mono">
            {criticalAt}{unit}
          </span>
        </div>
        <div className={`h-full rounded-full transition-all duration-700 ${fillCls}`} style={{ width: `${fillPct}%` }} />
      </div>
      <div className="flex justify-between text-[9px] text-slate-600 font-mono">
        <span>0{unit}</span>
        <span>{max}{unit}+</span>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface Props {
  disease: DiseaseType;
  variant: string;
  mutations: Mutation[];
}

export default function RiskEnginePage({ disease, variant, mutations }: Props) {
  const [bioCtx, setBioCtx]         = useState<BioContextResponse | null>(null);
  const [bioLoading, setBioLoading]  = useState(false);

  // mismatchCount and threePrimeMismatch are auto-filled from in-silico alignment;
  // the user can still override them manually before running the assessment.
  const [mismatchCount, setMismatchCount]           = useState(0);
  const [threePrimeMismatch, setThreePrimeMismatch]  = useState(false);
  const [reproducibilityCV, setReproducibilityCV]    = useState("");

  const [result, setResult]           = useState<PfpsResult | null>(null);
  const [assessing, setAssessing]     = useState(false);
  const [assessError, setAssessError] = useState<string | null>(null);
  const [saving, setSaving]           = useState(false);
  const [saved, setSaved]         = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Fetch primer sequence and genomic context
  useEffect(() => {
    setBioCtx(null);
    setBioLoading(true);
    fetch(`/api/v1/bio-context?disease_type=${encodeURIComponent(disease)}`)
      .then(r => (r.ok ? (r.json() as Promise<BioContextResponse>) : null))
      .then(data => setBioCtx(data))
      .catch(() => {})
      .finally(() => setBioLoading(false));
  }, [disease]);

  // Reset when variant changes
  useEffect(() => {
    setMismatchCount(0);
    setThreePrimeMismatch(false);
    setReproducibilityCV("");
    setResult(null);
    setSaved(false);
    setSaveError(null);
  }, [variant]);

  // ── In-silico alignment computation ──────────────────────────────────────────
  const primerSeq = bioCtx?.primer_structure?.sequence ?? "";

  const alignment = useMemo<AlignmentData | null>(() => {
    if (!primerSeq || bioLoading) return null;
    return computeAlignmentData(primerSeq, mutations, bioCtx);
  }, [primerSeq, mutations, bioCtx, bioLoading]);

  // Auto-fill mismatch params from alignment result
  useEffect(() => {
    if (alignment) {
      setMismatchCount(alignment.inPrimerMismatchCount);
      setThreePrimeMismatch(alignment.threePrimeMismatch);
    }
  }, [alignment]);

  const cvValue = reproducibilityCV !== "" ? parseFloat(reproducibilityCV) : null;
  const cfg     = result ? RISK_CFG[result.risk_level] : null;

  const handleAssess = async () => {
    const primerStart = alignment?.primerAbsStart ?? (PRIMER_ABS_FALLBACK[disease] ?? 1);
    const primerEnd   = alignment?.primerAbsEnd   ?? (primerStart + (primerSeq.length || 22) - 1);
    setAssessing(true);
    setAssessError(null);
    setResult(null);
    setSaved(false);
    setSaveError(null);
    try {
      // /api/v2/pfps — Layer 1 (deterministic) + Layer 2 (GPT-4o explanation)
      const res = await fetch("/api/v2/pfps", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mutations: mutations.map(m => ({
            position: m.position,
            gene:     m.gene ?? "Unknown",
            ref:      m.ref,
            alt:      m.alt,
            effect:   m.effect ?? "",
          })),
          primer_position: {
            primer_start_pos: primerStart,
            primer_end_pos:   primerEnd,
          },
          reproducibility_cv: cvValue ?? 0.0,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      const data: PfpsResult = await res.json();
      setResult(data);
    } catch (e) {
      setAssessError(e instanceof Error ? e.message : "평가 API 호출 실패");
    } finally {
      setAssessing(false);
    }
  };

  // Packages current context as CollectPayload JSON and POSTs to /api/v2/collect.
  // Endpoint is aliased as /api/v2/save-dataset in routers/v2.py.
  const handleSaveDataset = async () => {
    if (!result) return;
    setSaving(true);
    setSaveError(null);
    const payload = {
      disease_type:         disease,
      variant_name:         variant === "wild-type" ? "wild-type" : variant,
      mismatch_count:       mismatchCount,
      three_prime_mismatch: threePrimeMismatch,
      reproducibility_cv:   cvValue ?? undefined,
      guideline:            "risk-engine",
      source_filename:      null as null,
    };
    try {
      const res = await fetch("/api/v2/collect", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      setSaved(true);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setSaving(false);
    }
  };

  // Is the mismatch count consistent with the alignment result?
  const alignmentSynced =
    alignment !== null &&
    mismatchCount === alignment.inPrimerMismatchCount &&
    threePrimeMismatch === alignment.threePrimeMismatch;

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="bg-gradient-to-r from-blue-950 via-slate-900 to-slate-900 border border-blue-900/40 rounded-xl p-5 text-white">
        <p className="text-[11px] font-semibold text-blue-400 uppercase tracking-widest mb-1">
          Phase 2 · In Silico Variant Risk Engine
        </p>
        <p className="font-bold text-lg">프라이머-변이 정밀 위험도 평가</p>
        <p className="text-sm text-slate-400 mt-1 leading-relaxed">
          유전체 절대 좌표 기반으로 프라이머 결합 구간 내 실제 매핑되는 변이만 추출합니다.
          Watson-Crick 상보적 결합 규칙을 적용하여 미스매치 여부를 판정합니다.
        </p>
      </div>

      {/* ── Context bar ── */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl px-5 py-3 flex flex-wrap gap-5 text-sm">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Disease</p>
          <p className="font-semibold text-white mt-0.5">{disease}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Variant</p>
          <p className="font-semibold text-white mt-0.5">{variant}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Total Mutations</p>
          <p className="font-semibold text-white mt-0.5">{mutations.length}개</p>
        </div>
        {alignment && (
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Primer Region</p>
            <p className="font-semibold text-white mt-0.5 font-mono text-xs">
              pos {alignment.primerAbsStart.toLocaleString()}–{alignment.primerAbsEnd.toLocaleString()}
              <span className="text-slate-500 ml-1">({primerSeq.length} nt)</span>
            </p>
          </div>
        )}
        {alignment && (
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">In-Primer Mismatches</p>
            <p className={`font-semibold mt-0.5 font-mono text-xs ${
              alignment.inPrimerMismatchCount === 0 ? "text-emerald-400"
              : alignment.inPrimerMismatchCount >= 2 ? "text-red-400"
              : "text-amber-400"
            }`}>
              {alignment.inPrimerMismatchCount}개
              {alignment.threePrimeMismatch && <span className="ml-1 text-red-400">(3′ 포함)</span>}
            </p>
          </div>
        )}
      </div>

      {/* ── Two-column body ── */}
      <div className="grid lg:grid-cols-2 gap-5 items-start">

        {/* Left: Alignment + Mutation table */}
        <div className="space-y-4">

          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
              In Silico 서열 정렬 (Watson-Crick Complementarity)
            </p>
            <SequenceAlignmentView alignment={alignment} loading={bioLoading} />
          </div>

          {/* Mutation table — highlights in-primer rows */}
          {mutations.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-800 flex items-center justify-between">
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  Mutation Delta ({mutations.length})
                </p>
                {alignment && alignment.mappedMutations.length > 0 && (
                  <span className="text-[10px] font-semibold text-red-400 bg-red-900/40 border border-red-700/40 rounded px-2 py-0.5">
                    {alignment.mappedMutations.length}개 프라이머 구간 내
                  </span>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {["Gene", "Position", "Ref→Alt", "Effect", "Primer"].map(h => (
                        <th key={h} className="text-left text-[10px] text-slate-500 font-semibold uppercase tracking-wider px-3 py-2">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {mutations.map((m, i) => {
                      const inPrimer = alignment
                        ? m.position >= alignment.primerAbsStart && m.position <= alignment.primerAbsEnd
                        : false;
                      const primerOffset = inPrimer && alignment
                        ? m.position - alignment.primerAbsStart
                        : null;
                      return (
                        <tr
                          key={i}
                          className={`border-b border-slate-800/40 transition-colors ${
                            inPrimer ? "bg-red-950/30 hover:bg-red-950/50" : "hover:bg-slate-800/30"
                          }`}
                        >
                          <td className="px-3 py-2 font-semibold text-blue-400 font-mono">{m.gene}</td>
                          <td className="px-3 py-2 text-slate-300 font-mono">
                            {m.position.toLocaleString()}
                            {primerOffset !== null && (
                              <span className="ml-1.5 text-[10px] text-orange-400">+{primerOffset}</span>
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            <span className="text-slate-400">{m.ref}</span>
                            <span className="text-slate-600 mx-0.5">→</span>
                            <span className="text-orange-400 font-bold">{m.alt}</span>
                          </td>
                          <td className="px-3 py-2 text-slate-400">{m.effect}</td>
                          <td className="px-3 py-2">
                            {inPrimer ? (
                              <span className="text-[10px] font-semibold text-red-300 bg-red-900/50 border border-red-700/40 rounded px-1.5 py-0.5 whitespace-nowrap">
                                프라이머 내
                              </span>
                            ) : (
                              <span className="text-[10px] text-slate-700">구간 외</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Right: Parameters + Result */}
        <div className="space-y-4">

          {/* Parameter inputs */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              평가 파라미터
            </p>

            {/* Mismatch count — auto-filled from in-silico result */}
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                Mismatch Count
                {alignmentSynced ? (
                  <span className="ml-1.5 text-emerald-600 font-normal text-[10px]">
                    ✓ In Silico 계산값 (프라이머 구간 내 실제 매핑)
                  </span>
                ) : alignment ? (
                  <span className="ml-1.5 text-amber-600 font-normal text-[10px]">
                    수동 재정의 중 (계산값: {alignment.inPrimerMismatchCount})
                  </span>
                ) : (
                  <span className="ml-1.5 text-slate-400 font-normal">genome 로딩 중…</span>
                )}
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={20}
                  value={mismatchCount}
                  onChange={e => setMismatchCount(Math.max(0, parseInt(e.target.value) || 0))}
                  className="w-24 border border-slate-200 rounded-lg px-3 py-1.5 text-sm font-mono text-center focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
                {alignment && mismatchCount !== alignment.inPrimerMismatchCount && (
                  <button
                    onClick={() => {
                      setMismatchCount(alignment.inPrimerMismatchCount);
                      setThreePrimeMismatch(alignment.threePrimeMismatch);
                    }}
                    className="text-xs text-blue-500 hover:text-blue-700 transition"
                  >
                    ← In Silico 복원
                  </button>
                )}
              </div>
            </div>

            {/* 3' mismatch — auto-filled from alignment */}
            <div>
              <p className="text-xs font-semibold text-slate-600 mb-1.5">
                3′ 말단 미스매치
                {alignment && (
                  <span className={`ml-1.5 text-[10px] font-normal ${
                    alignment.threePrimeMismatch ? "text-red-500" : "text-emerald-600"
                  }`}>
                    ← In Silico {alignment.threePrimeMismatch ? "감지됨" : "정상"}
                  </span>
                )}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setThreePrimeMismatch(true)}
                  className={`flex-1 py-2 rounded-lg text-xs font-semibold border transition-all ${
                    threePrimeMismatch
                      ? "bg-red-600 border-red-500 text-white shadow-md"
                      : "bg-slate-50 border-slate-200 text-slate-500 hover:border-red-300 hover:text-red-600"
                  }`}
                >
                  활성 (감지됨)
                </button>
                <button
                  onClick={() => setThreePrimeMismatch(false)}
                  className={`flex-1 py-2 rounded-lg text-xs font-semibold border transition-all ${
                    !threePrimeMismatch
                      ? "bg-emerald-600 border-emerald-500 text-white shadow-md"
                      : "bg-slate-50 border-slate-200 text-slate-500 hover:border-emerald-300 hover:text-emerald-600"
                  }`}
                >
                  비활성 (정상)
                </button>
              </div>
            </div>

            {/* CV input */}
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                Reproducibility CV (%)
                <span className="ml-1.5 text-slate-400 font-normal">EP05 검증값 · 임계치 10%</span>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  placeholder="예: 8.5"
                  value={reproducibilityCV}
                  onChange={e => setReproducibilityCV(e.target.value)}
                  className="w-32 border border-slate-200 rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
                <span className="text-xs text-slate-400">%</span>
              </div>
            </div>

            <button
              onClick={handleAssess}
              disabled={assessing}
              className={`w-full py-2.5 font-semibold text-sm rounded-lg transition-all shadow-sm flex items-center justify-center gap-2 ${
                assessing
                  ? "bg-slate-300 text-slate-500 cursor-wait"
                  : "bg-blue-600 hover:bg-blue-700 active:scale-[0.98] text-white"
              }`}
            >
              {assessing ? (
                <>
                  <span className="w-4 h-4 border-2 border-slate-400 border-t-slate-600 rounded-full animate-spin" />
                  좌표 기반 위험도 계산 중…
                </>
              ) : "위험도 평가 실행 (PFPS + AI 보고서)"}
            </button>
            {assessError && (
              <p className="text-xs text-red-500 mt-1 text-center">{assessError}</p>
            )}
          </div>

          {/* ── Result Panel ── */}
          {result && cfg && (
            <div className={`border-2 rounded-xl overflow-hidden bg-slate-900 ${cfg.border}`}>

              {/* Risk badge */}
              <div className="px-5 pt-5 pb-4 flex items-center justify-between">
                <div>
                  <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5">
                    Risk Assessment Result
                  </p>
                  <div className="flex items-center gap-3">
                    <span className={`w-3 h-3 rounded-full ${cfg.badge} shadow-lg ${cfg.glow} animate-pulse inline-block`} />
                    <span className={`text-2xl font-black ${cfg.accentText}`}>{cfg.label}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <span className="text-[10px] font-mono text-slate-500">
                      PFPS Score:
                      <span className="text-white font-semibold ml-1">
                        {result.meta_metrics.is_critical_override ? "Critical Override" : `${result.score}pt`}
                      </span>
                    </span>
                    {result.meta_metrics.is_critical_override && (
                      <span className="text-[9px] bg-red-900/60 text-red-300 border border-red-700/40 rounded-full px-2 py-0.5 font-semibold">
                        Critical Override
                      </span>
                    )}
                    {result.meta_metrics.cv_escalated && (
                      <span className="text-[9px] bg-amber-900/60 text-amber-300 border border-amber-700/40 rounded-full px-2 py-0.5 font-semibold">
                        CV Escalated
                      </span>
                    )}
                  </div>
                </div>
                <div className={`w-14 h-14 rounded-full ${cfg.badge} flex items-center justify-center shadow-xl`}>
                  <span className="text-white text-2xl font-black">{cfg.icon}</span>
                </div>
              </div>

              {/* Explainable Rule Indicator */}
              <div className="bg-slate-900/80 border-t border-slate-800/50 px-5 py-5">
                <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-6">
                  Explainable Rule Indicator
                </p>
                <div className="space-y-7">
                  <RiskGaugeBar
                    label="통계 리스크 — Reproducibility CV"
                    subtitle="CLSI EP05 · CV > 10% → MEDIUM 이상"
                    value={cvValue}
                    unit="%"
                    max={25}
                    warnAt={5}
                    criticalAt={10}
                  />
                  <RiskGaugeBar
                    label="서열 리스크 — In-Silico Mismatch Count"
                    subtitle="프라이머 구간 내 실제 매핑 변이 · ≥ 2개 → HIGH"
                    value={mismatchCount}
                    unit=""
                    max={5}
                    warnAt={1}
                    criticalAt={2}
                  />
                  <RiskGaugeBar
                    label="위치 기반 리스크 — PFPS Score"
                    subtitle={
                      result.meta_metrics.is_critical_override
                        ? "Critical Override 활성 — 3′ 말단 직격 변이 존재"
                        : "3′ 거리 가중 점수 · ≥5pt→HIGH · 3–4pt→MEDIUM"
                    }
                    value={
                      result.meta_metrics.is_critical_override
                        ? 10
                        : Math.min(result.score, 10)
                    }
                    unit="pt"
                    max={10}
                    warnAt={3}
                    criticalAt={5}
                  />
                </div>
              </div>

              {/* Deterministic trigger summary */}
              <div className="px-5 pt-4 pb-2 border-t border-slate-800">
                <div className="flex items-start gap-2">
                  <span className="text-[11px] shrink-0 mt-0.5">
                    {result.risk_level === "HIGH" ? "🔴" : result.risk_level === "MEDIUM" ? "🟡" : "🟢"}
                  </span>
                  <p className="text-[11px] text-slate-300 leading-relaxed">
                    {result.meta_metrics.trigger_rule_summary}
                  </p>
                </div>
              </div>

              {/* AI Clinical Report — GPT-4o narrator */}
              <div className="px-5 pb-5">
                <div className="flex items-center gap-2 mb-2.5">
                  <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
                    AI 임상 보고서
                  </p>
                  <span className="text-[9px] bg-blue-900/40 text-blue-400 border border-blue-700/30 rounded px-1.5 py-0.5 font-mono">
                    GPT-4o · 해설 전용
                  </span>
                </div>
                <div className="bg-slate-950 border border-slate-700/60 rounded-xl p-4">
                  <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
                    {result.reason}
                  </p>
                </div>
              </div>

              {/* Save dataset button */}
              <div className="px-5 pb-5 flex items-center justify-between gap-3">
                {saved ? (
                  <div className="flex items-center gap-2 bg-emerald-900/40 border border-emerald-700/40 rounded-lg px-3 py-2 flex-1">
                    <span className="text-emerald-400 text-sm">✓</span>
                    <p className="text-xs text-emerald-300 font-semibold">데이터셋에 저장되었습니다</p>
                  </div>
                ) : saveError ? (
                  <div className="flex items-start gap-2 bg-red-950/40 border border-red-700/40 rounded-lg px-3 py-2 flex-1">
                    <span className="text-red-400 text-sm shrink-0">✕</span>
                    <p className="text-xs text-red-300 leading-relaxed">{saveError}</p>
                  </div>
                ) : (
                  <div className="flex-1" />
                )}
                <button
                  onClick={handleSaveDataset}
                  disabled={saving || saved}
                  className={`shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
                    saved
                      ? "bg-slate-700 text-slate-400 cursor-default"
                      : saving
                      ? "bg-slate-700 text-slate-400 cursor-wait"
                      : "bg-blue-600 hover:bg-blue-700 active:scale-[0.97] text-white shadow-md"
                  }`}
                >
                  {saving ? (
                    <>
                      <span className="w-3 h-3 border border-white/50 border-t-transparent rounded-full animate-spin" />
                      저장 중…
                    </>
                  ) : saved ? "저장 완료" : (
                    <><span>⬆</span>데이터셋에 저장</>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
