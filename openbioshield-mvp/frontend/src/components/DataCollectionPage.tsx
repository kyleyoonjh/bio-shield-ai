import { useEffect, useState, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from "recharts";
import type { DatasetStats, RiskLevel } from "../types";

interface DatasetStatsExtended extends DatasetStats {
  _status?: string;
  _error?: string;
}

const FINE_TUNING_THRESHOLD = 5000;

const RISK_COLORS: Record<RiskLevel, string> = {
  HIGH:   "#ef4444",
  MEDIUM: "#f59e0b",
  LOW:    "#10b981",
};

const DISEASE_COLORS: Record<string, string> = {
  "SARS-CoV-2": "#3b82f6",
  "HPV":        "#8b5cf6",
  "STI":        "#ec4899",
};

type SetupState = "idle" | "running" | "done" | "error";

export default function DataCollectionPage() {
  const [stats, setStats]     = useState<DatasetStatsExtended | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  const [setupState, setSetupState] = useState<SetupState>("idle");
  const [setupError, setSetupError] = useState<string | null>(null);

  const fetchStats = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch("/api/v2/dataset/stats")
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: DatasetStatsExtended) => setStats(data))
      .catch(e => setError(e instanceof Error ? e.message : "Failed to load stats"))
      .finally(() => setLoading(false));
  }, []);

  const handleSetupTables = async () => {
    setSetupState("running");
    setSetupError(null);
    try {
      const res = await fetch("/api/v2/setup-tables", { method: "POST" });
      const body = await res.json().catch(() => ({ detail: "Unknown error" }));
      if (!res.ok) {
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      setSetupState("done");
      // Re-fetch stats after a short delay so new empty tables are reflected
      setTimeout(fetchStats, 1200);
    } catch (e) {
      setSetupState("error");
      setSetupError(e instanceof Error ? e.message : "테이블 생성 실패");
    }
  };

  useEffect(() => { fetchStats(); }, [fetchStats]);

  if (loading) return (
    <div className="flex items-center justify-center gap-3 py-24 text-slate-500">
      <span className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin inline-block" />
      <span className="text-sm">데이터셋 통계 로딩 중...</span>
    </div>
  );

  if (error) return (
    <div className="bg-red-50 border border-red-200 text-red-700 px-5 py-4 rounded-xl text-sm flex items-center justify-between">
      <span>{error}</span>
      <button onClick={fetchStats} className="text-xs font-semibold bg-red-100 hover:bg-red-200 border border-red-300 rounded-lg px-3 py-1.5 transition">
        다시 시도
      </button>
    </div>
  );

  if (!stats) return null;

  const readinessPct = Math.min(stats.readiness_percent, 100);
  const highRiskPct  = stats.total_records > 0
    ? Math.round((stats.by_risk.HIGH ?? 0) / stats.total_records * 100)
    : 0;

  const diseaseChartData = Object.entries(stats.by_disease).map(([name, count]) => ({
    name, count,
  }));
  const riskChartData = (["HIGH", "MEDIUM", "LOW"] as RiskLevel[]).map(level => ({
    name: level,
    count: stats.by_risk[level] ?? 0,
  }));

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="bg-blue-900 rounded-xl p-5 text-white">
        <p className="text-xs font-semibold text-blue-300 uppercase tracking-widest mb-1">
          Phase 2 · Data Collection
        </p>
        <p className="font-bold text-white text-lg">Genomic AI 훈련 데이터셋</p>
        <p className="text-sm text-blue-200 mt-1">
          연구자 분석 워크플로우에서 자동 수집된 데이터. {FINE_TUNING_THRESHOLD.toLocaleString()}개 도달 시
          DNABERT-2 / HyenaDNA fine-tuning이 가능합니다.
        </p>
      </div>

      {/* Supabase setup card */}
      {stats._status === "supabase_unavailable" && setupState !== "done" && (
        <div className="bg-slate-900 border border-amber-600/40 rounded-xl overflow-hidden">
          {/* Title bar */}
          <div className="bg-amber-950/60 border-b border-amber-700/30 px-5 py-3 flex items-center gap-2">
            <span className="text-amber-400 text-base">⚠</span>
            <p className="text-sm font-semibold text-amber-300">Supabase 테이블 미생성</p>
            <span className="ml-auto text-[10px] text-amber-600 font-mono">primer_experiments, feedback_records</span>
          </div>

          <div className="p-5 space-y-4">
            {/* Step instructions */}
            <ol className="space-y-2 text-xs text-slate-400">
              <li className="flex gap-2.5">
                <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-[10px] flex items-center justify-center shrink-0 font-bold">1</span>
                <span>
                  <a
                    href="https://supabase.com/dashboard/account/tokens"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:text-blue-300 underline underline-offset-2"
                  >
                    supabase.com/dashboard/account/tokens
                  </a>
                  에서 <strong className="text-slate-200">Personal Access Token</strong> 발급
                </span>
              </li>
              <li className="flex gap-2.5">
                <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-[10px] flex items-center justify-center shrink-0 font-bold">2</span>
                <span>
                  <code className="bg-slate-800 rounded px-1.5 py-0.5 text-emerald-400 text-[11px]">backend/.env</code>에 추가:
                </span>
              </li>
            </ol>
            <div className="bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 font-mono text-xs text-emerald-400 select-all">
              SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxxxxxxxxxxxxxx
            </div>
            <p className="text-[11px] text-slate-500">
              토큰 추가 후 백엔드를 재시작하면 아래 버튼이 활성화됩니다.
            </p>

            {/* Action row */}
            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={handleSetupTables}
                disabled={setupState === "running"}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                  setupState === "running"
                    ? "bg-slate-700 text-slate-400 cursor-wait"
                    : "bg-blue-600 hover:bg-blue-700 active:scale-[0.97] text-white shadow-md"
                }`}
              >
                {setupState === "running" ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                    테이블 생성 중…
                  </>
                ) : (
                  <>
                    <span>🗄</span>
                    테이블 자동 생성 (CREATE TABLE)
                  </>
                )}
              </button>

              {setupState === "error" && setupError && (
                <div className="flex-1 flex items-start gap-1.5 bg-red-950/40 border border-red-700/40 rounded-lg px-3 py-2">
                  <span className="text-red-400 text-xs shrink-0 mt-0.5">✕</span>
                  <p className="text-xs text-red-300 leading-relaxed">{setupError}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Success notice after setup */}
      {setupState === "done" && (
        <div className="bg-emerald-900/40 border border-emerald-600/40 rounded-xl px-5 py-3 flex items-center gap-3">
          <span className="text-emerald-400 text-lg">✓</span>
          <div>
            <p className="text-sm font-semibold text-emerald-300">테이블 생성 완료</p>
            <p className="text-xs text-emerald-500 mt-0.5">
              primer_experiments, feedback_records 테이블이 생성되었습니다. 이제 분석을 실행하면 자동으로 데이터가 수집됩니다.
            </p>
          </div>
        </div>
      )}

      {/* Fine-tuning readiness */}
      {stats.is_ready ? (
        <div className="bg-emerald-50 border-2 border-emerald-400 rounded-xl p-5 flex items-center gap-4">
          <span className="text-4xl">🎉</span>
          <div>
            <p className="font-bold text-emerald-800 text-lg">Dataset ready for genomic model fine-tuning!</p>
            <p className="text-sm text-emerald-700 mt-0.5">
              {stats.total_records.toLocaleString()}개 레코드 수집 완료 — DNABERT-2 또는 HyenaDNA fine-tuning을 시작할 수 있습니다.
            </p>
          </div>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-semibold text-slate-700">Fine-Tuning Readiness</p>
            <p className="text-xs text-slate-500 font-mono">
              {stats.total_records.toLocaleString()} / {FINE_TUNING_THRESHOLD.toLocaleString()}
            </p>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-3 overflow-hidden">
            <div
              className="h-3 rounded-full transition-all bg-gradient-to-r from-blue-500 to-blue-600"
              style={{ width: `${readinessPct}%` }}
            />
          </div>
          <p className="text-xs text-slate-400 mt-1.5">{readinessPct.toFixed(1)}% 완료</p>
        </div>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KpiCard label="총 레코드" value={stats.total_records.toLocaleString()} accent="blue" />
        <KpiCard label="최근 30일" value={stats.recent_30d.toLocaleString()} accent="green" />
        <KpiCard label="High Risk 비율" value={`${highRiskPct}%`} accent="red" />
        <KpiCard
          label="EP09 수집"
          value={(stats.by_guideline["EP09"] ?? 0).toLocaleString()}
          accent="default"
        />
      </div>

      {/* Charts row */}
      <div className="grid sm:grid-cols-2 gap-4">

        {/* Disease distribution */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-4">
            Disease 분포
          </p>
          {stats.total_records === 0 ? (
            <EmptyChart />
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={diseaseChartData} layout="vertical" margin={{ left: 8, right: 20, top: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#94a3b8" }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "#64748b" }} width={90} />
                <Tooltip
                  formatter={(v: number) => [v.toLocaleString(), "레코드"]}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {diseaseChartData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={DISEASE_COLORS[entry.name] ?? "#94a3b8"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Risk distribution */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-4">
            Risk Level 분포
          </p>
          {stats.total_records === 0 ? (
            <EmptyChart />
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={riskChartData} margin={{ left: 0, right: 8, top: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} />
                <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} />
                <Tooltip
                  formatter={(v: number) => [v.toLocaleString(), "레코드"]}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {riskChartData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={RISK_COLORS[entry.name as RiskLevel] ?? "#94a3b8"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Guideline breakdown */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-4">
          가이드라인별 수집 현황
        </p>
        <div className="grid grid-cols-2 gap-4">
          {(["EP05", "EP09"] as const).map(g => {
            const count = stats.by_guideline[g] ?? 0;
            const pct = stats.total_records > 0 ? Math.round(count / stats.total_records * 100) : 0;
            return (
              <div key={g} className="bg-slate-50 rounded-lg p-4">
                <p className="text-xs font-bold text-slate-600 uppercase tracking-wide">{g}</p>
                <p className="text-2xl font-bold text-slate-800 mt-1">{count.toLocaleString()}</p>
                <p className="text-xs text-slate-400 mt-0.5">{pct}% of total</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Refresh */}
      <div className="flex justify-end">
        <button
          onClick={fetchStats}
          className="text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1.5 transition"
        >
          <span>↻</span> 새로고침
        </button>
      </div>

    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function KpiCard({ label, value, accent }: {
  label: string; value: string;
  accent: "blue" | "green" | "red" | "default";
}) {
  const borders = { blue: "border-l-blue-500", green: "border-l-emerald-500", red: "border-l-red-400", default: "border-l-slate-300" };
  const values  = { blue: "text-blue-700",     green: "text-emerald-700",     red: "text-red-600",    default: "text-slate-800"    };
  return (
    <div className={`bg-white border border-slate-200 border-l-4 ${borders[accent]} rounded-lg p-4 shadow-sm`}>
      <p className="text-xs text-slate-500 font-medium uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${values[accent]}`}>{value}</p>
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="flex items-center justify-center h-[180px] text-slate-300">
      <div className="text-center">
        <p className="text-4xl mb-2">📭</p>
        <p className="text-sm">데이터 없음 — 분석을 실행하면 자동 수집됩니다</p>
      </div>
    </div>
  );
}
