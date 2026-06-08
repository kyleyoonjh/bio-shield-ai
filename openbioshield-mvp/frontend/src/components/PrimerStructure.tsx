import { useEffect, useState } from "react";
import type { BioContext } from "../types";

export default function PrimerStructure() {
  const [bioContext, setBioContext] = useState<BioContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/bio-context")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load bio context");
        return res.json();
      })
      .then(setBioContext)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-gray-500 text-center py-8">프라이머 구조 데이터 로딩 중...</p>;
  if (error) return <p className="text-red-600 text-center py-8">{error}</p>;
  if (!bioContext) return null;

  const ps = bioContext.primer_structure;

  return (
    <div className="space-y-6">
      <div className="grid md:grid-cols-3 gap-4">
        <MetricCard label="Melting Temperature (Tm)" value={`${ps.melting_temp_c}°C`} icon="🌡️" />
        <MetricCard label="ΔG (Self-dimer)" value={`${ps.delta_g_kcal} kcal/mol`} icon="⚡" />
        <MetricCard label="GC Content" value={`${ps.gc_percent}%`} icon="🧬" />
      </div>

      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h3 className="font-semibold mb-4">Forward Primer 서열</h3>
        <p className="font-mono text-sm bg-gray-50 p-4 rounded-lg break-all">{ps.sequence}</p>
        <p className="text-xs text-gray-400 mt-2">Length: {ps.length} nt</p>
      </div>

      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h3 className="font-semibold mb-4">2차 구조 (Dot-Bracket Notation)</h3>
        <p className="font-mono text-sm bg-gray-50 p-4 rounded-lg break-all mb-4">{ps.dot_bracket}</p>

        <h4 className="text-sm font-medium text-gray-600 mb-3">구조 시각화</h4>
        <div className="grid grid-cols-11 gap-1 max-w-lg">
          {ps.sequence.split("").map((base, i) => {
            const bracket = ps.dot_bracket[i] ?? ".";
            const isPaired = bracket === "(" || bracket === ")";
            return (
              <div
                key={i}
                className={`aspect-square flex flex-col items-center justify-center rounded text-xs font-mono ${
                  isPaired ? "bg-bio-100 border-bio-300 border" : "bg-gray-50 border border-gray-200"
                }`}
                title={`${base} [${bracket}]`}
              >
                <span className="font-bold">{base}</span>
                <span className="text-gray-400 text-[10px]">{bracket}</span>
              </div>
            );
          })}
        </div>
        <div className="flex gap-4 mt-4 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 bg-bio-100 border border-bio-300 rounded" /> Paired
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 bg-gray-50 border border-gray-200 rounded" /> Unpaired
          </span>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, icon }: { label: string; value: string; icon: string }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border p-5">
      <div className="text-2xl mb-2">{icon}</div>
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-xl font-bold text-gray-800 mt-1">{value}</p>
    </div>
  );
}
