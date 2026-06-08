import { useEffect, useState } from "react";
import { SeqViz } from "seqviz";
import type { BioContext } from "../types";

export default function DnaSequenceView() {
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

  if (loading) return <p className="text-gray-500 text-center py-8">서열 데이터 로딩 중...</p>;
  if (error) return <p className="text-red-600 text-center py-8">{error}</p>;
  if (!bioContext) return null;

  const annotations = bioContext.annotations.map((ann) => ({
    name: ann.name,
    start: ann.start,
    end: ann.end,
    direction: ann.strand as 1 | -1,
    color: ann.color,
  }));

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h3 className="font-semibold text-gray-800 mb-2">
          SARS-CoV-2 RdRp 타겟 서열 — {bioContext.assay_info.organism}
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          {bioContext.assay_info.assay_type} · {bioContext.assay_info.standard} ·{" "}
          {bioContext.rdrp_sequence.length} bp
        </p>

        <div className="border rounded-lg p-4 bg-gray-50 overflow-x-auto">
          <SeqViz
            name="SARS-CoV-2 RdRp"
            seq={bioContext.rdrp_sequence}
            annotations={annotations}
            viewer="linear"
            showComplement={false}
            style={{ height: "200px", width: "100%" }}
          />
        </div>

        <div className="flex flex-wrap gap-4 mt-4">
          {bioContext.annotations.map((ann) => (
            <div key={ann.name} className="flex items-center gap-2 text-sm">
              <span className="w-4 h-4 rounded" style={{ backgroundColor: ann.color }} />
              <span>
                {ann.name}: {ann.start + 1}–{ann.end + 1} bp
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
