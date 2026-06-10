import type { AssayPrimer } from "../types";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export interface ScoreBreakdown {
  coverageContribution: number;
  thermoContribution: number;
  aiContribution: number;
  bonus: number;
  penalty: number;
  finalScore: number;
}

export interface RiskSummary {
  variantRisk: RiskLevel;
  thermoRisk: RiskLevel;
  coverageRisk: RiskLevel;
  overall: RiskLevel;
  message: string;
}

export interface RadarData {
  coverage: number;
  thermodynamics: number;
  gcQuality: number;
  ampliconQuality: number;
  riskProfile: number;
  aiEfficiency: number;
}

export interface Explainability {
  scoreBreakdown: ScoreBreakdown;
  strengths: string[];
  weaknesses: string[];
  riskSummary: RiskSummary;
  recommendation: string;
  recommendationLevel: "high" | "recommended" | "consider" | "low";
  whyRanked: string[];
  comparisonSummary: { lines: string[]; scoreDiff: number; vsRank: number } | null;
  radar: RadarData;
}

const clamp = (v: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v));

const worstRisk = (risks: RiskLevel[]): RiskLevel =>
  risks.includes("HIGH") ? "HIGH" : risks.includes("MEDIUM") ? "MEDIUM" : "LOW";

const riskMsg: Record<RiskLevel, string> = {
  LOW:    "Low overall assay risk",
  MEDIUM: "Moderate overall assay risk — review before use",
  HIGH:   "High overall assay risk — validate carefully",
};

function coverageRisk(cov: number): RiskLevel {
  return cov < 85 ? "HIGH" : cov < 95 ? "MEDIUM" : "LOW";
}
function thermoRisk(t: number): RiskLevel {
  return t < 60 ? "HIGH" : t < 80 ? "MEDIUM" : "LOW";
}

export function computeExplainability(
  primer: AssayPrimer,
  allPrimers: AssayPrimer[],
): Explainability {
  const coverage = clamp(primer.coverage_score ?? 0);
  const thermo   = clamp(primer.thermo_score   ?? 0);
  const ai       = clamp(primer.ai_score       ?? 0);
  const gc       = primer.gc ?? 50;
  const product  = primer.product_size ?? 150;

  const tmFwd  = primer.tm_fwd ?? primer.tm ?? 60;
  const tmRev  = primer.tm_rev ?? primer.tm ?? 60;
  const tmDiff = Math.abs(tmFwd - tmRev);

  // ── Score Breakdown ──────────────────────────────────────────────────────────
  const covContrib   = parseFloat((coverage * 0.6).toFixed(1));
  const thermoContrib = parseFloat((thermo  * 0.2).toFixed(1));
  const aiContrib    = parseFloat((ai       * 0.2).toFixed(1));
  const finalScore   = parseFloat((covContrib + thermoContrib + aiContrib).toFixed(1));

  // ── Strengths ────────────────────────────────────────────────────────────────
  const strengths: string[] = [];
  if (coverage >= 95)              strengths.push("Excellent Coverage");
  if (tmDiff   <= 1)               strengths.push("Excellent Tm Balance");
  if (gc >= 40 && gc <= 60)        strengths.push("Optimal GC Content");
  if (product >= 70 && product <= 200) strengths.push("Optimal Amplicon Size");
  if (thermo   >= 80)              strengths.push("Strong Thermodynamic Stability");
  if (ai       >= 80)              strengths.push("High AI Efficiency");

  // ── Weaknesses ───────────────────────────────────────────────────────────────
  const weaknesses: string[] = [];
  if (coverage < 90)   weaknesses.push("Coverage Limitation");
  if (tmDiff   > 3)    weaknesses.push("Tm Imbalance");
  if (gc       > 65)   weaknesses.push("High GC Content");
  if (gc       < 35)   weaknesses.push("Low GC Content");
  if (product  > 250)  weaknesses.push("Large Amplicon");
  if (thermo   < 50)   weaknesses.push("Poor Thermodynamic Stability");

  // ── Risk ─────────────────────────────────────────────────────────────────────
  const vRisk  = coverageRisk(coverage);
  const tRisk  = thermoRisk(thermo);
  const cRisk  = coverageRisk(coverage);
  const overall = worstRisk([vRisk, tRisk, cRisk]);
  const riskSummary: RiskSummary = {
    variantRisk: vRisk, thermoRisk: tRisk, coverageRisk: cRisk,
    overall, message: riskMsg[overall],
  };

  // ── Recommendation ───────────────────────────────────────────────────────────
  let recommendation: string;
  let recommendationLevel: Explainability["recommendationLevel"];
  if      (finalScore >= 90) { recommendation = "Highly Recommended for wet-lab validation"; recommendationLevel = "high"; }
  else if (finalScore >= 85) { recommendation = "Recommended for wet-lab validation";        recommendationLevel = "recommended"; }
  else if (finalScore >= 80) { recommendation = "Consider Validation";                       recommendationLevel = "consider"; }
  else                       { recommendation = "Low Priority Candidate";                    recommendationLevel = "low"; }

  // ── Why Ranked ───────────────────────────────────────────────────────────────
  const whyRanked: string[] = [];
  whyRanked.push(`${coverage.toFixed(0)}% sequence coverage`);
  if (tmDiff      <= 1)               whyRanked.push("Excellent Tm balance");
  if (gc >= 40 && gc <= 60)           whyRanked.push("Optimal GC content");
  if (thermo      >= 80)              whyRanked.push("Strong thermodynamic stability");
  if (overall     === "LOW")          whyRanked.push("Low assay risk");
  if (ai          >= 80)              whyRanked.push("High AI efficiency prediction");
  if (product >= 70 && product <= 200) whyRanked.push("Optimal amplicon size");

  // ── Comparison ───────────────────────────────────────────────────────────────
  let comparisonSummary: Explainability["comparisonSummary"] = null;

  const myRank   = primer.final_rank ?? 99;
  const myScore  = primer.final_score ?? 0;
  const otherRank = myRank === 1 ? 2 : 1;
  const other = allPrimers.find(p => p.final_rank === otherRank);

  if (other) {
    const oCov    = other.coverage_score ?? 0;
    const oThermo = other.thermo_score   ?? 0;
    const oAi     = other.ai_score       ?? 0;
    const oTmDiff = Math.abs((other.tm_fwd ?? other.tm ?? 60) - (other.tm_rev ?? other.tm ?? 60));
    const oScore  = other.final_score    ?? 0;

    const lines: string[] = [];
    // Compare this candidate vs other (from perspective of rank1 being better)
    const a = myRank === 1 ? primer : other;
    const b = myRank === 1 ? other  : primer;
    const aCov    = a.coverage_score ?? 0;
    const aThermo = a.thermo_score   ?? 0;
    const aAi     = a.ai_score       ?? 0;
    const aTmDiff = Math.abs((a.tm_fwd ?? a.tm ?? 60) - (a.tm_rev ?? a.tm ?? 60));
    const bCov    = b.coverage_score ?? 0;
    const bThermo = b.thermo_score   ?? 0;
    const bAi     = b.ai_score       ?? 0;
    const bTmDiff = Math.abs((b.tm_fwd ?? b.tm ?? 60) - (b.tm_rev ?? b.tm ?? 60));

    if (aCov    > bCov    + 2)    lines.push("Better coverage");
    if (aThermo > bThermo + 3)    lines.push("Better thermodynamic score");
    if (aAi     > bAi     + 3)    lines.push("Higher AI efficiency");
    if (aTmDiff < bTmDiff - 0.5)  lines.push("More balanced Tm");
    if (lines.length === 0)        lines.push("Marginally higher overall score");

    const scoreDiff = parseFloat(((a.final_score ?? 0) - (b.final_score ?? 0)).toFixed(1));
    comparisonSummary = { lines, scoreDiff, vsRank: otherRank };
    void [oCov, oThermo, oAi, oTmDiff, oScore, myScore]; // silence unused
  }

  // ── Radar ────────────────────────────────────────────────────────────────────
  const gcQuality = clamp(100 - Math.abs(gc - 50) * 2);
  const ampliconQuality = clamp(
    product >= 70 && product <= 200 ? 85 + Math.min(15, 15 - Math.abs(product - 135) / 10)
    : product >= 50 && product <= 300 ? 55
    : 20
  );
  const riskProfile: Record<RiskLevel, number> = { LOW: 100, MEDIUM: 55, HIGH: 15 };

  return {
    scoreBreakdown: {
      coverageContribution: covContrib,
      thermoContribution: thermoContrib,
      aiContribution: aiContrib,
      bonus: 0, penalty: 0, finalScore,
    },
    strengths,
    weaknesses,
    riskSummary,
    recommendation,
    recommendationLevel,
    whyRanked,
    comparisonSummary,
    radar: {
      coverage,
      thermodynamics: thermo,
      gcQuality,
      ampliconQuality,
      riskProfile: riskProfile[overall],
      aiEfficiency: ai,
    },
  };
}
