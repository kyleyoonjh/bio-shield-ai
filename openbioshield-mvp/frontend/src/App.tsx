import { useState } from "react";
import FileUpload from "./components/FileUpload";
import StatsDashboard from "./components/StatsDashboard";
import DnaSequenceView from "./components/DnaSequenceView";
import PrimerStructure from "./components/PrimerStructure";
import type { SchemaMapping, StatsResult, UploadMetadata } from "./types";

type Step = "upload" | "stats" | "dna" | "primer";

const STEPS: { id: Step; label: string; icon: string }[] = [
  { id: "upload", label: "1. 업로드", icon: "📊" },
  { id: "stats", label: "2. 통계 분석", icon: "📈" },
  { id: "dna", label: "3. DNA 맵", icon: "🧬" },
  { id: "primer", label: "4. Primer 구조", icon: "🔬" },
];

export default function App() {
  const [step, setStep] = useState<Step>("upload");
  const [, setFile] = useState<File | null>(null);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSchemaConfirmed = async (
    uploadedFile: File,
    schema: SchemaMapping,
    _metadata: UploadMetadata
  ) => {
    setFile(uploadedFile);
    setAnalyzing(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", uploadedFile);
    formData.append("schema_mapping", JSON.stringify(schema));

    try {
      const res = await fetch("/api/v1/analyze", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Analysis failed");
      }
      const data: StatsResult = await res.json();
      setStats(data);
      setStep("stats");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const currentStepIndex = STEPS.findIndex((s) => s.id === step);

  return (
    <div className="min-h-screen">
      <header className="bg-bio-700 text-white shadow-lg">
        <div className="max-w-6xl mx-auto px-6 py-5">
          <h1 className="text-2xl font-bold">OpenBioShield</h1>
          <p className="text-bio-100 text-sm mt-1">
            SARS-CoV-2 RdRp Gene Assay Precision Validation · Phase 1 MVP
          </p>
        </div>
      </header>

      <nav className="bg-white border-b shadow-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 flex gap-1 overflow-x-auto">
          {STEPS.map((s, i) => {
            const isActive = s.id === step;
            const isDone = i < currentStepIndex;
            const isDisabled = s.id !== "upload" && !stats && s.id !== "dna" && s.id !== "primer";

            return (
              <button
                key={s.id}
                onClick={() => {
                  if (s.id === "upload" || stats || s.id === "dna" || s.id === "primer") {
                    setStep(s.id);
                  }
                }}
                disabled={isDisabled}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap ${
                  isActive
                    ? "border-bio-600 text-bio-700"
                    : isDone
                      ? "border-transparent text-bio-600 hover:text-bio-700"
                      : "border-transparent text-gray-400"
                } ${isDisabled ? "opacity-40 cursor-not-allowed" : ""}`}
              >
                <span>{s.icon}</span>
                {s.label}
              </button>
            );
          })}
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {analyzing && (
          <div className="text-center py-12">
            <div className="inline-block w-10 h-10 border-4 border-bio-500 border-t-transparent rounded-full animate-spin" />
            <p className="mt-3 text-gray-600">statsmodels ANOVA 분석 수행 중...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        {!analyzing && step === "upload" && <FileUpload onSchemaConfirmed={handleSchemaConfirmed} />}
        {!analyzing && step === "stats" && stats && <StatsDashboard stats={stats} />}
        {!analyzing && step === "dna" && <DnaSequenceView />}
        {!analyzing && step === "primer" && <PrimerStructure />}
      </main>

      <footer className="border-t bg-white mt-12">
        <div className="max-w-6xl mx-auto px-6 py-4 text-center text-xs text-gray-400">
          OpenBioShield MVP · CLSI EP05-A3 · Anti-Hallucination: All stats computed by Python
        </div>
      </footer>
    </div>
  );
}
