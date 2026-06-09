import { useState, useRef, useCallback, useEffect } from "react";
import type { AssayStatusResponse } from "../types";

// ─── Types ────────────────────────────────────────────────────────────────────

type PageState = "idle" | "uploading" | "polling" | "done" | "error";

interface JobListEntry {
  id: string;
  project_name: string;
  target_name: string;
  assay_type: string;
  status: string;
  created_at: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 120; // 6 minutes

// ─── Test data generator ──────────────────────────────────────────────────────

const TEST_GENES   = ["ORF1ab", "Spike", "Nucleocapsid", "Envelope", "RdRp", "E6", "E7", "ompA"];
const TEST_ASSAY   = ["qPCR", "Multiplex qPCR", "End-point PCR"] as const;
const TEST_ORGS    = ["SARS-CoV-2", "HPV16", "Chlamydia", "Influenza-A", "RSV"] as const;
const BASES        = ["A", "T", "G", "C"] as const;

function randInt(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randPick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function randSeq(length: number): string {
  // Biased toward AT-rich (60 % AT) to mimic real amplicon regions
  const pool = ["A","A","A","T","T","T","G","C","G","C"];
  return Array.from({ length }, () => pool[Math.floor(Math.random() * pool.length)]).join("");
}

function mutateSeq(seq: string, mutRate = 0.02): string {
  return seq.split("").map(b =>
    Math.random() < mutRate ? randPick(BASES) : b
  ).join("");
}

function generateTestFasta(): File {
  const seqLen  = randInt(350, 500);
  const numSeqs = randInt(4, 8);
  const ref     = randSeq(seqLen);

  const lines: string[] = [];
  for (let i = 0; i < numSeqs; i++) {
    const seq = i === 0 ? ref : mutateSeq(ref, 0.015 + Math.random() * 0.025);
    lines.push(`>seq${i + 1}_strain${randInt(1, 999)}`);
    // wrap at 70 chars
    for (let pos = 0; pos < seq.length; pos += 70) {
      lines.push(seq.slice(pos, pos + 70));
    }
  }

  const content = lines.join("\n") + "\n";
  return new File([content], "test_sequences.fasta", { type: "text/plain" });
}

function generateTestMeta() {
  const org   = randPick(TEST_ORGS);
  const gene  = randPick(TEST_GENES);
  const assay = randPick(TEST_ASSAY);
  const ts    = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  return {
    projectName: `${org}_${gene}_${ts}`,
    targetName:  gene,
    assayType:   assay,
  };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function parseApiError(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (res.status === 404) return "엔드포인트를 찾을 수 없습니다. 백엔드 서버를 재시작해 주세요. (404)";
  if (res.status === 503) return "백엔드 서버가 응답하지 않습니다. (503)";
  if (res.status === 422) {
    try {
      const json = JSON.parse(text);
      const msg = json?.detail?.[0]?.msg ?? json?.detail ?? text;
      return `입력값 오류: ${msg}`;
    } catch { return `입력값 오류 (422)`; }
  }
  try {
    const json = JSON.parse(text);
    return (json?.detail ?? text) || `서버 오류 (${res.status})`;
  } catch {
    return text || `서버 오류 (${res.status})`;
  }
}

function scoreBar(value: number | null, max = 1) {
  if (value === null) return null;
  const pct = Math.round((value / max) * 100);
  const color =
    pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400 w-8 text-right">{pct}%</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    RUNNING:   "bg-blue-500/20 text-blue-300 border-blue-500/30",
    COMPLETED: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
    FAILED:    "bg-red-500/20 text-red-300 border-red-500/30",
  };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${cfg[status] ?? "bg-slate-700 text-slate-300 border-slate-600"}`}>
      {status}
    </span>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function AssayDesignPage() {
  const [pageState, setPageState] = useState<PageState>("idle");
  const [projectName, setProjectName] = useState("");
  const [targetName, setTargetName]   = useState("");
  const [assayType, setAssayType]     = useState("qPCR");
  const [fastaFile, setFastaFile]     = useState<File | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [result, setResult]           = useState<AssayStatusResponse | null>(null);
  const [errorMsg, setErrorMsg]       = useState<string>("");
  const [pollCount, setPollCount]     = useState(0);
  const [recentJobs, setRecentJobs]   = useState<JobListEntry[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load recent jobs on mount ──────────────────────────────────────────────
  useEffect(() => {
    loadRecentJobs();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  const loadRecentJobs = useCallback(async () => {
    setJobsLoading(true);
    try {
      const res = await fetch("/api/v3/assay/jobs?limit=10");
      if (res.ok) {
        const data: JobListEntry[] = await res.json();
        setRecentJobs(data);
      }
    } catch {
      // silently fail — jobs list is informational
    } finally {
      setJobsLoading(false);
    }
  }, []);

  // ── Poll job status ────────────────────────────────────────────────────────
  const pollStatus = useCallback(async (jobId: string, attempt: number) => {
    if (attempt >= POLL_MAX_ATTEMPTS) {
      console.error("[assay] ⏰ 폴링 타임아웃 job=%s attempt=%d", jobId, attempt);
      setPageState("error");
      setErrorMsg("파이프라인 시간 초과 (6분). 서버 로그를 확인해 주세요.");
      return;
    }
    try {
      const res = await fetch(`/api/v3/assay/status/${jobId}`);
      if (!res.ok) {
        const msg = await parseApiError(res);
        throw new Error(msg);
      }
      const data: AssayStatusResponse = await res.json();
      console.log(`[assay] poll #${attempt + 1} job=${jobId} status=${data.status}`);
      setPollCount(attempt + 1);

      if (data.status === "COMPLETED") {
        console.log("[assay] ✅ COMPLETED | primers:", data.primers?.length ?? 0, "report:", data.report_path);
        setResult(data);
        setPageState("done");
        loadRecentJobs();
      } else if (data.status === "FAILED") {
        console.error("[assay] ❌ FAILED | error:", data.error_message);
        setErrorMsg(data.error_message ?? "파이프라인 실패");
        setPageState("error");
        loadRecentJobs();
      } else {
        // still RUNNING — schedule next poll
        pollTimerRef.current = setTimeout(
          () => pollStatus(jobId, attempt + 1),
          POLL_INTERVAL_MS,
        );
      }
    } catch (err) {
      setErrorMsg(`상태 조회 실패: ${err}`);
      setPageState("error");
    }
  }, [loadRecentJobs]);

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = useCallback(async () => {
    if (!fastaFile || !projectName.trim() || !targetName.trim()) return;
    setPageState("uploading");
    setErrorMsg("");
    setResult(null);
    setPollCount(0);

    console.group("[assay] 🚀 파이프라인 시작");
    console.log("project:", projectName.trim());
    console.log("target:", targetName.trim(), "| assay_type:", assayType);
    console.log("fasta_file:", fastaFile.name, "| size:", fastaFile.size, "bytes");
    console.log("POST →", "/api/v3/assay/design");

    try {
      const form = new FormData();
      form.append("project_name", projectName.trim());
      form.append("target_name",  targetName.trim());
      form.append("assay_type",   assayType);
      form.append("fasta_file",   fastaFile);

      const res = await fetch("/api/v3/assay/design", {
        method: "POST",
        body: form,
      });

      console.log("응답 status:", res.status, res.statusText);

      if (!res.ok) {
        const msg = await parseApiError(res);
        console.error("❌ 업로드 실패:", msg);
        console.groupEnd();
        throw new Error(msg);
      }

      const data = await res.json();
      console.log("✅ job 생성:", data.job_id, "| status:", data.status);
      console.groupEnd();
      setCurrentJobId(data.job_id);
      setPageState("polling");
      pollStatus(data.job_id, 0);
    } catch (err) {
      console.error("[assay] submit error:", err);
      console.groupEnd();
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg.startsWith("Failed to fetch")
        ? "백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요."
        : msg);
      setPageState("error");
    }
  }, [fastaFile, projectName, targetName, assayType, pollStatus]);

  const handleFillTest = useCallback(async () => {
    const meta = generateTestMeta();
    setProjectName(meta.projectName);
    setTargetName(meta.targetName);
    setAssayType(meta.assayType);
    if (fileInputRef.current) fileInputRef.current.value = "";

    console.group("[assay] 🎲 테스트 데이터 채움");
    console.log("project:", meta.projectName, "| target:", meta.targetName, "| assay:", meta.assayType);

    try {
      const res = await fetch("/test_sequences.fasta");
      console.log("FASTA fetch →", res.status, res.url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const file = new File([blob], "test_sequences.fasta", { type: "text/plain" });
      setFastaFile(file);
      console.log("✅ static FASTA 로드 완료 | size:", file.size, "bytes");
    } catch (e) {
      console.warn("static FASTA 로드 실패 → 랜덤 생성 fallback", e);
      const file = generateTestFasta();
      setFastaFile(file);
      console.log("✅ 랜덤 FASTA 생성 완료 | size:", file.size, "bytes");
    }
    console.groupEnd();
  }, []);

  const handleReset = () => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    setPageState("idle");
    setCurrentJobId(null);
    setResult(null);
    setErrorMsg("");
    setPollCount(0);
    setFastaFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const isSubmittable =
    pageState === "idle" &&
    !!fastaFile &&
    projectName.trim().length > 0 &&
    targetName.trim().length > 0;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">

      {/* ── Header card ─────────────────────────────────────────────────── */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-lg bg-violet-500/20 border border-violet-500/30 flex items-center justify-center text-lg flex-shrink-0">
            🧪
          </div>
          <div>
            <h2 className="text-white font-semibold text-base">Assay Design Pipeline</h2>
            <p className="text-slate-400 text-sm mt-1">
              다중 서열 FASTA 업로드 → MSA → 보존 구역 탐지 → Primer3 후보 생성 →
              특이성 필터 → Tm/GC 평가 → AI 효율 점수 → 최적 프라이머 랭킹
            </p>
            <div className="flex flex-wrap gap-2 mt-3">
              {[
                "MAFFT MSA",
                "Shannon Entropy",
                "Primer3",
                "Bowtie2",
                "Thermo Scoring",
                "AI Efficiency",
                "Weighted Rank",
              ].map(label => (
                <span
                  key={label}
                  className="text-xs bg-slate-700 text-slate-300 border border-slate-600 rounded-full px-2.5 py-0.5"
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* ── Left: Input form ──────────────────────────────────────────── */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-slate-200 font-medium text-sm">프로젝트 설정</h3>
              <button
                onClick={handleFillTest}
                disabled={pageState !== "idle"}
                title="랜덤 데이터로 자동 채움"
                className="flex items-center gap-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 border border-slate-600 rounded-md px-2.5 py-1 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span>🎲</span>
                테스트 채움
              </button>
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-400 block mb-1.5">프로젝트명 *</label>
              <input
                type="text"
                value={projectName}
                onChange={e => setProjectName(e.target.value)}
                placeholder="예: COVID-19_qPCR_2026"
                disabled={pageState !== "idle"}
                className="w-full bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-50 placeholder:text-slate-500"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-400 block mb-1.5">타깃 유전자 *</label>
              <input
                type="text"
                value={targetName}
                onChange={e => setTargetName(e.target.value)}
                placeholder="예: ORF1ab, E, N"
                disabled={pageState !== "idle"}
                className="w-full bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-50 placeholder:text-slate-500"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-400 block mb-1.5">Assay 종류</label>
              <select
                value={assayType}
                onChange={e => setAssayType(e.target.value)}
                disabled={pageState !== "idle"}
                className="w-full bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-50"
              >
                <option value="qPCR">qPCR</option>
                <option value="Multiplex qPCR">Multiplex qPCR</option>
                <option value="End-point PCR">End-point PCR</option>
              </select>
            </div>

            {/* FASTA upload */}
            <div>
              <label className="text-xs font-semibold text-slate-400 block mb-1.5">FASTA 파일 *</label>
              <div
                onClick={() => pageState === "idle" && fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors cursor-pointer ${
                  pageState !== "idle"
                    ? "border-slate-700 opacity-50 cursor-not-allowed"
                    : fastaFile
                    ? "border-violet-500 bg-violet-500/10"
                    : "border-slate-600 hover:border-slate-500 bg-slate-700/40"
                }`}
              >
                {fastaFile ? (
                  <div>
                    <p className="text-violet-300 text-sm font-medium">{fastaFile.name}</p>
                    <p className="text-slate-500 text-xs mt-1">{(fastaFile.size / 1024).toFixed(1)} KB</p>
                  </div>
                ) : (
                  <div>
                    <p className="text-slate-400 text-sm">클릭하여 FASTA 파일 선택</p>
                    <p className="text-slate-600 text-xs mt-1">.fasta, .fa, .txt</p>
                  </div>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".fasta,.fa,.txt"
                className="hidden"
                onChange={e => setFastaFile(e.target.files?.[0] ?? null)}
              />
            </div>

            {/* Submit / Reset */}
            {pageState === "idle" || pageState === "error" ? (
              <button
                onClick={pageState === "error" ? handleReset : handleSubmit}
                disabled={pageState === "idle" && !isSubmittable}
                className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-all ${
                  pageState === "error"
                    ? "bg-slate-600 hover:bg-slate-500 text-white"
                    : isSubmittable
                    ? "bg-violet-600 hover:bg-violet-500 text-white"
                    : "bg-slate-700 text-slate-500 cursor-not-allowed"
                }`}
              >
                {pageState === "error" ? "다시 시도" : "파이프라인 시작"}
              </button>
            ) : (
              <button
                onClick={handleReset}
                className="w-full py-2.5 rounded-lg text-sm font-semibold bg-slate-700 hover:bg-slate-600 text-slate-300 transition-all"
              >
                초기화
              </button>
            )}
          </div>

          {/* Recent jobs */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-slate-200 font-medium text-sm">최근 작업</h3>
              <button
                onClick={loadRecentJobs}
                className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                새로고침
              </button>
            </div>

            {jobsLoading ? (
              <div className="flex justify-center py-4">
                <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : recentJobs.length === 0 ? (
              <p className="text-slate-600 text-xs text-center py-4">작업 없음</p>
            ) : (
              <div className="space-y-2">
                {recentJobs.map(job => (
                  <div
                    key={job.id}
                    className="bg-slate-700/50 rounded-lg p-3 border border-slate-700"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-slate-200 text-xs font-medium truncate">{job.project_name}</p>
                        <p className="text-slate-500 text-xs truncate">{job.target_name} · {job.assay_type}</p>
                      </div>
                      <StatusBadge status={job.status} />
                    </div>
                    <p className="text-slate-600 text-xs mt-1.5">
                      {new Date(job.created_at).toLocaleString("ko-KR")}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Right: Status + Results ──────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-4">

          {/* Idle placeholder */}
          {pageState === "idle" && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-10 flex flex-col items-center justify-center text-center gap-3">
              <div className="text-4xl">🧬</div>
              <p className="text-slate-300 font-medium">파이프라인 대기 중</p>
              <p className="text-slate-500 text-sm max-w-sm">
                왼쪽에서 프로젝트 정보와 FASTA 파일을 설정한 후 "파이프라인 시작"을 클릭하세요.
              </p>
            </div>
          )}

          {/* Uploading */}
          {pageState === "uploading" && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-10 flex flex-col items-center gap-4">
              <div className="w-10 h-10 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
              <p className="text-slate-300 font-medium">FASTA 파일 업로드 중...</p>
            </div>
          )}

          {/* Polling / Running */}
          {pageState === "polling" && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-8 space-y-6">
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                <div>
                  <p className="text-white font-semibold">파이프라인 실행 중</p>
                  <p className="text-slate-400 text-xs mt-0.5">Job ID: {currentJobId}</p>
                </div>
              </div>

              {/* Pipeline steps visual */}
              <div className="space-y-2">
                {[
                  { step: 1, label: "MAFFT 다중 서열 정렬" },
                  { step: 2, label: "Shannon Entropy 보존 구역 탐지" },
                  { step: 3, label: "Primer3 후보 생성" },
                  { step: 4, label: "Bowtie2 특이성 필터" },
                  { step: 5, label: "변이 커버리지 계산" },
                  { step: 6, label: "열역학 점수 (Tm/GC/Dimer)" },
                  { step: 7, label: "AI 효율 예측" },
                  { step: 8, label: "가중치 랭킹" },
                  { step: 9, label: "보고서 생성" },
                ].map(({ step, label }) => {
                  const estimatedStep = Math.min(
                    Math.floor((pollCount / POLL_MAX_ATTEMPTS) * 9) + 1,
                    9,
                  );
                  const isDone    = step < estimatedStep;
                  const isCurrent = step === estimatedStep;
                  return (
                    <div key={step} className="flex items-center gap-3">
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                        isDone    ? "bg-emerald-500 text-white"
                        : isCurrent ? "bg-blue-500 text-white animate-pulse"
                        : "bg-slate-700 text-slate-500"
                      }`}>
                        {isDone ? "✓" : step}
                      </div>
                      <span className={`text-sm ${
                        isDone    ? "text-slate-400 line-through"
                        : isCurrent ? "text-white font-medium"
                        : "text-slate-600"
                      }`}>
                        {label}
                      </span>
                    </div>
                  );
                })}
              </div>

              <p className="text-slate-600 text-xs text-center">
                폴링 {pollCount}/{POLL_MAX_ATTEMPTS} · {POLL_INTERVAL_MS / 1000}초마다 갱신
              </p>
            </div>
          )}

          {/* Error */}
          {pageState === "error" && (
            <div className="bg-red-900/30 border border-red-500/40 rounded-xl p-6 space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-red-400 text-lg">⚠</span>
                <h3 className="text-red-300 font-semibold">파이프라인 오류</h3>
              </div>
              <p className="text-red-200 text-sm whitespace-pre-wrap">{errorMsg}</p>
            </div>
          )}

          {/* Done / Results */}
          {pageState === "done" && result && (
            <div className="space-y-4">

              {/* Summary banner */}
              <div className="bg-emerald-900/30 border border-emerald-500/40 rounded-xl p-5 flex items-center gap-4">
                <div className="w-10 h-10 bg-emerald-500/20 rounded-full flex items-center justify-center text-xl flex-shrink-0">
                  ✓
                </div>
                <div>
                  <p className="text-emerald-300 font-semibold">파이프라인 완료</p>
                  <p className="text-slate-400 text-sm">
                    {result.primers?.length ?? 0}개 최적 프라이머 선별 완료
                    {result.report_path && (
                      <span className="text-slate-500"> · 보고서: {result.report_path.split("/").pop()}</span>
                    )}
                  </p>
                </div>
              </div>

              {/* Ranked primer table */}
              {result.primers && result.primers.length > 0 && (
                <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
                  <div className="px-5 py-3 border-b border-slate-700">
                    <h3 className="text-slate-200 font-medium text-sm">최적 프라이머 랭킹</h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-slate-700 text-slate-400">
                          <th className="px-3 py-2.5 text-left font-medium w-8">#</th>
                          <th className="px-3 py-2.5 text-left font-medium">Forward (5'→3')</th>
                          <th className="px-3 py-2.5 text-left font-medium">Reverse (5'→3')</th>
                          <th className="px-3 py-2.5 text-right font-medium w-16">Tm (°C)</th>
                          <th className="px-3 py-2.5 text-right font-medium w-12">크기</th>
                          <th className="px-3 py-2.5 text-left font-medium w-28">Coverage</th>
                          <th className="px-3 py-2.5 text-left font-medium w-28">Thermo</th>
                          <th className="px-3 py-2.5 text-left font-medium w-28">AI 효율</th>
                          <th className="px-3 py-2.5 text-right font-medium w-20">최종 점수</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.primers.map(p => (
                          <tr
                            key={p.id}
                            className={`border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors ${
                              p.final_rank === 1 ? "bg-violet-900/20" : ""
                            }`}
                          >
                            <td className="px-3 py-3 text-center">
                              {p.final_rank === 1 ? (
                                <span className="text-yellow-400 font-bold">1</span>
                              ) : (
                                <span className="text-slate-500">{p.final_rank}</span>
                              )}
                            </td>
                            <td className="px-3 py-3">
                              <code className="text-violet-300 font-mono text-xs tracking-wide">
                                {p.forward_primer}
                              </code>
                            </td>
                            <td className="px-3 py-3">
                              <code className="text-cyan-300 font-mono text-xs tracking-wide">
                                {p.reverse_primer}
                              </code>
                            </td>
                            <td className="px-3 py-3 text-right text-slate-300">
                              {p.tm !== null ? p.tm.toFixed(1) : "—"}
                            </td>
                            <td className="px-3 py-3 text-right text-slate-400">
                              {p.product_size ?? "—"}<span className="text-slate-600">bp</span>
                            </td>
                            <td className="px-3 py-3">
                              {scoreBar(p.coverage_score)}
                            </td>
                            <td className="px-3 py-3">
                              {scoreBar(p.thermo_score, 100)}
                            </td>
                            <td className="px-3 py-3">
                              {scoreBar(p.ai_score, 100)}
                            </td>
                            <td className="px-3 py-3 text-right">
                              <span className={`font-bold ${
                                (p.final_score ?? 0) >= 0.7
                                  ? "text-emerald-400"
                                  : (p.final_score ?? 0) >= 0.4
                                  ? "text-amber-400"
                                  : "text-red-400"
                              }`}>
                                {p.final_score !== null ? p.final_score.toFixed(3) : "—"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Score legend */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
                <p className="text-slate-500 text-xs font-semibold mb-2">점수 공식</p>
                <p className="text-slate-400 text-xs font-mono">
                  Final Score = 0.6 × Coverage + 0.2 × Thermo + 0.2 × AI
                </p>
                <p className="text-slate-600 text-xs mt-1">
                  Coverage: 다변이 커버리지 (0–1) · Thermo: 열역학 점수/100 · AI: 효율 예측/100
                </p>
              </div>

              {/* New design button */}
              <button
                onClick={handleReset}
                className="w-full py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm font-medium rounded-lg transition-all"
              >
                새 디자인 시작
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
