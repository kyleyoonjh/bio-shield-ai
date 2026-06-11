import { useState, useEffect, useCallback } from "react";
import ClinicalValidationDashboard from "./components/ClinicalValidationDashboard";
import DnaSequenceView from "./components/DnaSequenceView";
import PrimerStructure from "./components/PrimerStructure";
import RiskEnginePage from "./components/RiskEnginePage";
import DataCollectionPage from "./components/DataCollectionPage";
import AssayDesignPage from "./components/AssayDesignPage";
import CovidDashboard from "./components/covid/CovidDashboard";
import DemoBanner from "./components/DemoBanner";
import { ToastContainer, makeToast } from "./components/Toast";
import { checkDemoMode } from "./services/covidService";
import type { ToastMessage } from "./components/Toast";
import type { DiseaseType, VariantInfo, Mutation } from "./types";

// Phase 1: Covid 대시보드 · DNA 탐색 · Primer 구조
type Tab = "covid" | "dna" | "primer";
type Phase = "1" | "2" | "3";
// Phase 2에 통계 검증(stat-validation) 추가
type Phase2Page = "risk-engine" | "stat-validation" | "data-collection";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "covid",  label: "Covid Dashboard", icon: "🦠" },
  { id: "dna",    label: "DNA 맵",           icon: "🧬" },
  { id: "primer", label: "Primer 구조",      icon: "🔬" },
];

const PHASE2_PAGES: { id: Phase2Page; label: string; icon: string }[] = [
  { id: "stat-validation", label: "통계 검증",         icon: "📊" },
  { id: "risk-engine",     label: "Risk Engine",     icon: "⚡" },
  { id: "data-collection", label: "Data Collection", icon: "🗄️" },
];

const DISEASES: { id: DiseaseType; label: string }[] = [
  { id: "SARS-CoV-2", label: "SARS-CoV-2 (COVID-19)" },
  { id: "HPV",        label: "HPV Type 16" },
  { id: "STI",        label: "Chlamydia trachomatis" },
];

export default function App() {
  const [activeTab, setActiveTab]   = useState<Tab>("covid");
  const [phase, setPhase]           = useState<Phase>("1");
  const [phase2Page, setPhase2Page] = useState<Phase2Page>("stat-validation");
  const [demoMode, setDemoMode]     = useState(false);

  const [disease, setDisease]                     = useState<DiseaseType>("SARS-CoV-2");
  const [variant, setVariant]                     = useState<string>("wild-type");
  const [variantList, setVariantList]             = useState<VariantInfo[]>([]);
  const [mutations, setMutations]                 = useState<Mutation[]>([]);
  const [variantsLoading, setVariantsLoading]     = useState(false);
  const [mutationsLoading, setMutationsLoading]   = useState(false);
  const [toasts, setToasts]                       = useState<ToastMessage[]>([]);

  // Check demo mode once on startup before any other data fetching
  useEffect(() => {
    checkDemoMode().then(on => setDemoMode(on));
  }, []);

  const addToast = useCallback((message: string, type: ToastMessage["type"] = "info") => {
    setToasts(prev => [...prev, makeToast(message, type)]);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // ── Disease 변경 ───────────────────────────────────────────────────────────
  useEffect(() => {
    setVariant("wild-type");
    setMutations([]);
    setVariantList([]);
    setVariantsLoading(true);
    fetch(`/api/v1/variants?disease_type=${encodeURIComponent(disease)}`)
      .then(r => r.json())
      .then(data => setVariantList(data.variants ?? []))
      .catch(() => addToast("변이 목록을 불러오지 못했습니다.", "warning"))
      .finally(() => setVariantsLoading(false));
  }, [disease, addToast]);

  // ── Variant 변경 ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (variant === "wild-type") { setMutations([]); return; }
    setMutationsLoading(true);
    fetch(`/api/v1/mutations?disease_type=${encodeURIComponent(disease)}&variant=${encodeURIComponent(variant)}`)
      .then(r => r.json())
      .then(data => setMutations(data.mutations ?? []))
      .catch(() => addToast("변이 데이터를 불러오지 못했습니다.", "warning"))
      .finally(() => setMutationsLoading(false));
  }, [disease, variant, addToast]);

  const navToTab = useCallback((tab: Tab, reason: string) => {
    console.log(`[tab-nav] → ${tab}  reason: ${reason}  time: ${new Date().toTimeString().slice(0, 8)}`);
    setActiveTab(tab);
  }, []);

  const handleDiseaseChange = (newDisease: DiseaseType) => {
    console.log(`[disease-change] ${disease} → ${newDisease}  currentTab: ${activeTab}`);
    setDisease(newDisease);
  };

  const handleVariantChange = (newVariant: string) => {
    console.log(`[variant-change] ${variant} → ${newVariant}  currentTab: ${activeTab}`);
    if (newVariant !== "wild-type") {
      addToast(
        `변이 변경: 업로드된 분석 파일이 현재 변이(${
          variantList.find(v => v.id === newVariant)?.label ?? newVariant
        })와 일치하지 않을 수 있습니다. 파일을 다시 확인해주세요.`,
        "warning",
      );
    }
    setVariant(newVariant);
  };

  const currentVariantLabel = variantList.find(v => v.id === variant)?.label ?? variant;

  // ── 병원균/변이주 셀렉터 (Phase 1 · Phase 2 nav 공유) ─────────────────────
  const renderDiseaseVariantSelectors = () => (
    <div className="ml-auto flex items-center gap-4 py-1">
      <div className="flex items-center gap-1.5">
        <label className="text-xs font-semibold text-slate-400 whitespace-nowrap">병원균</label>
        <select
          value={disease}
          onChange={e => handleDiseaseChange(e.target.value as DiseaseType)}
          className="text-xs bg-white border border-slate-200 text-slate-700 rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-400 cursor-pointer"
        >
          {DISEASES.map(d => (
            <option key={d.id} value={d.id}>{d.label}</option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-1.5">
        <label className="text-xs font-semibold text-slate-400 whitespace-nowrap">변이주</label>
        <select
          value={variant}
          onChange={e => handleVariantChange(e.target.value)}
          disabled={variantsLoading || variantList.length === 0}
          className="text-xs bg-white border border-slate-200 text-slate-700 rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-400 cursor-pointer disabled:opacity-50"
        >
          {variantsLoading ? (
            <option>로딩 중...</option>
          ) : (
            variantList.map(v => (
              <option key={v.id} value={v.id}>
                {v.label}
                {v.who_label && v.who_label !== "Reference" ? ` · ${v.who_label}` : ""}
              </option>
            ))
          )}
        </select>
        {mutationsLoading && (
          <span className="w-3.5 h-3.5 border-2 border-red-400 border-t-transparent rounded-full animate-spin inline-block flex-shrink-0" />
        )}
        {!mutationsLoading && mutations.length > 0 && (
          <span className="text-xs bg-red-500 text-white rounded-full px-2 py-0.5 font-bold leading-none flex-shrink-0">
            {mutations.length} 변이
          </span>
        )}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">

      {/* ── Header — Phase 전환 + 타이틀만 ────────────────────────────────── */}
      <header className="bg-gradient-to-r from-blue-800 to-blue-700 shadow-md">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-5">

          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-bold tracking-wide text-white">OpenBioShield</h1>
            <p className="text-xs text-blue-200 mt-0.5">
              {phase === "1"
                ? "DNA 탐색 및 Primer 설계 · Phase 1"
                : phase === "2"
                ? "통계 검증 · Risk Engine · Phase 2"
                : "Assay Design Pipeline · Phase 3"}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-0.5 bg-blue-900/50 rounded-lg p-0.5 border border-blue-600/50">
              {(["1", "2", "3"] as Phase[]).map(p => (
                <button
                  key={p}
                  onClick={() => setPhase(p)}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${
                    phase === p
                      ? "bg-blue-500 text-white shadow-sm"
                      : "text-blue-300 hover:text-white"
                  }`}
                >
                  Phase {p}
                </button>
              ))}
            </div>
            <span className="flex items-center gap-1.5 text-xs text-blue-200">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              Ready
            </span>
          </div>
        </div>
      </header>

      {/* ── Phase 1 Tab Nav (DNA 맵 · Primer 구조 + 병원균/변이주 셀렉터) ─── */}
      {phase === "1" && (
        <nav className="bg-white border-b border-slate-200 shadow-sm sticky top-0 z-10">
          <div className="max-w-7xl mx-auto px-6 flex items-center gap-1">
            {TABS.map(t => {
              const isActive = t.id === activeTab;
              return (
                <button key={t.id} onClick={() => navToTab(t.id, "tab button clicked")}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                    isActive
                      ? "border-blue-600 text-blue-700"
                      : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
                  }`}
                >
                  <span>{t.icon}</span>
                  {t.label}
                </button>
              );
            })}

            {activeTab !== "covid" && variant !== "wild-type" && (
              <span className="text-xs bg-red-50 border border-red-200 text-red-700 rounded-full px-3 py-1 font-semibold whitespace-nowrap">
                {currentVariantLabel}
              </span>
            )}

            {/* Covid 탭에서는 병원균 고정(SARS-CoV-2) → 셀렉터 숨김 */}
            {activeTab !== "covid" && renderDiseaseVariantSelectors()}
          </div>
        </nav>
      )}

      {/* ── Phase 2 Tab Nav (Risk Engine · 통계 검증 · Data Collection) ──── */}
      {phase === "2" && (
        <nav className="bg-white border-b border-slate-200 shadow-sm sticky top-0 z-10">
          <div className="max-w-7xl mx-auto px-6 flex items-center gap-1">
            {PHASE2_PAGES.map(p => {
              const isActive = p.id === phase2Page;
              return (
                <button key={p.id} onClick={() => setPhase2Page(p.id)}
                  className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                    isActive
                      ? "border-blue-600 text-blue-700"
                      : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
                  }`}
                >
                  <span>{p.icon}</span>
                  {p.label}
                </button>
              );
            })}

            {variant !== "wild-type" && phase2Page !== "data-collection" && (
              <span className="text-xs bg-red-50 border border-red-200 text-red-700 rounded-full px-3 py-1 font-semibold whitespace-nowrap">
                {currentVariantLabel}
              </span>
            )}

            {/* 병원균/변이주는 data-collection 페이지에선 불필요 */}
            {phase2Page !== "data-collection" && renderDiseaseVariantSelectors()}
          </div>
        </nav>
      )}

      {/* ── Main ───────────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">

        {/* Phase 1 — Covid 대시보드 (병원균 SARS-CoV-2 고정) */}
        {phase === "1" && activeTab === "covid" && (
          <CovidDashboard />
        )}

        {/* Phase 1 — DNA 탐색 / Primer 구조 */}
        {phase === "1" && activeTab === "dna" && (
          <DnaSequenceView
            disease={disease}
            mutations={mutations}
            mutationsLoading={mutationsLoading}
            variantLabel={variant === "wild-type" ? undefined : currentVariantLabel}
          />
        )}
        {phase === "1" && activeTab === "primer" && (
          <PrimerStructure
            disease={disease}
            mutations={mutations}
            variantLabel={variant === "wild-type" ? undefined : currentVariantLabel}
          />
        )}

        {/* Phase 2 — Risk Engine */}
        {phase === "2" && phase2Page === "risk-engine" && (
          <RiskEnginePage
            disease={disease}
            variant={variant}
            mutations={mutations}
          />
        )}

        {/* Phase 2 — 통계 검증 (EP05 · EP09) */}
        {phase === "2" && phase2Page === "stat-validation" && (
          <ClinicalValidationDashboard
            disease={disease}
            variant={variant}
            variantLabel={currentVariantLabel}
            mutations={mutations}
            onVariantMismatchWarning={() =>
              addToast("업로드된 파일이 현재 변이 컨텍스트와 다를 수 있습니다.", "warning")
            }
          />
        )}

        {/* Phase 2 — Data Collection */}
        {phase === "2" && phase2Page === "data-collection" && (
          <DataCollectionPage />
        )}

        {/* Phase 3 — Assay Design */}
        {phase === "3" && (
          <AssayDesignPage />
        )}
      </main>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between text-xs text-slate-400">
          <span>OpenBioShield MVP · 통계 계산은 Python 엔진 전담 (Anti-Hallucination)</span>
          <span className="font-mono">FastAPI · statsmodels · OpenAI · Supabase · Primer3</span>
        </div>
      </footer>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      {demoMode && <DemoBanner />}
    </div>
  );
}
