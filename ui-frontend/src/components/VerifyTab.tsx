import { useRef, useState } from "react";
import { api } from "../api/client";
import type { VerifyFinding, VerifyResult } from "../types";

type TabKey = "overall" | "days" | "restaurants" | "static_sections";

const CHECK_DESCRIPTIONS: Record<string, { label: string; severity: "RED" | "YELLOW" }> = {
  R1:  { label: "AI artifacts in text",              severity: "RED"    },
  R2:  { label: "Unfilled template placeholders",    severity: "RED"    },
  R3:  { label: "Mandatory sections present",        severity: "RED"    },
  R4:  { label: "Day numbers sequential",            severity: "RED"    },
  R5:  { label: "Day heading format correct",        severity: "YELLOW" },
  R6:  { label: "Google Maps links present",         severity: "YELLOW" },
  R7:  { label: "≥3 restaurant options per day",     severity: "RED"    },
  R8:  { label: "Time ranges include AM/PM",         severity: "RED"    },
  R9:  { label: "No encoding artefacts",             severity: "YELLOW" },
  R10: { label: "Day count matches itinerary",       severity: "RED"    },
  A1:  { label: "No dietary violations",             severity: "RED"    },
  A2:  { label: "Real emergency contacts",           severity: "RED"    },
  A3:  { label: "No wrong-destination content",      severity: "RED"    },
  A4:  { label: "Creative destination-specific title", severity: "YELLOW" },
  A5:  { label: "Packing list trip-specific",        severity: "YELLOW" },
  A6:  { label: "Full opening hours on all entries", severity: "YELLOW" },
  A7:  { label: "Meal proximity to attractions/hotel", severity: "YELLOW" },
  A8:  { label: "Must-Try Dishes covers all cities", severity: "YELLOW" },
  A9:  { label: "Getting Around covers all cities",  severity: "YELLOW" },
  A10: { label: "Cultural etiquette destination-specific", severity: "YELLOW" },
  A11: { label: "Thank You page uses client name",   severity: "YELLOW" },
  A12: { label: "No coherence / flow issues",        severity: "YELLOW" },
  A13: { label: "No inverted time ranges",           severity: "RED"    },
  A14: { label: "Dinner venues open past 7 PM",      severity: "RED"    },
  A15: { label: "Sunset / time-of-day times accurate", severity: "RED"  },
  A16: { label: "Travel times plausible",            severity: "RED"    },
  A17: { label: "Transport pass claims accurate",    severity: "RED"    },
  A18: { label: "Important Places includes essentials", severity: "RED" },
  A19: { label: "Meal venue types appropriate",           severity: "YELLOW" },
  A20: { label: "Distance references correctly anchored", severity: "YELLOW" },
  A21: { label: "Attractions open on scheduled day",      severity: "RED"    },
  A22: { label: "Booking requirements flagged",           severity: "RED"    },
  A23: { label: "Arrival/departure day logic sound",      severity: "RED"    },
  A24: { label: "Seasonal experiences accurate",          severity: "RED"    },
  A25: { label: "Day itineraries practically executable", severity: "RED"    },
  A26: { label: "Spelling, grammar & formatting clean",   severity: "YELLOW" },
  A27: { label: "Day flow logical and well-paced",        severity: "RED"    },
};

const NARRATIVE_TABS: { key: TabKey; label: string }[] = [
  { key: "overall",         label: "Overall" },
  { key: "days",            label: "Days" },
  { key: "restaurants",     label: "Restaurants" },
  { key: "static_sections", label: "Other Sections" },
];

// ---------------------------------------------------------------------------
// Finding card
// ---------------------------------------------------------------------------

function FindingCard({ finding }: { finding: VerifyFinding }) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const isRed = finding.severity === "RED";

  return (
    <div className={`rounded-lg border p-4 ${isRed ? "border-red-200 bg-red-50" : "border-yellow-200 bg-yellow-50"}`}>
      <div className="flex items-start gap-3">
        <span className={`shrink-0 text-xs font-bold px-2 py-0.5 rounded ${isRed ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700"}`}>
          {finding.check_id}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-500 mb-0.5">{finding.section}</p>
          <p className="text-sm text-slate-800">{finding.description}</p>
          {finding.evidence && (
            <button
              onClick={() => setEvidenceOpen((o) => !o)}
              className="mt-2 text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1"
            >
              <span>{evidenceOpen ? "▲" : "▼"}</span>
              <span>Evidence</span>
            </button>
          )}
          {evidenceOpen && finding.evidence && (
            <pre className="mt-2 text-xs bg-white border border-slate-200 rounded p-2 whitespace-pre-wrap break-words text-slate-600 font-mono">
              {finding.evidence}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results view
// ---------------------------------------------------------------------------

function Results({ result, onReset }: { result: VerifyResult; onReset: () => void }) {
  const [narrativeTab, setNarrativeTab] = useState<TabKey>("overall");
  const [passedOpen, setPassedOpen] = useState(false);

  const redFindings    = result.findings.filter((f) => f.severity === "RED");
  const yellowFindings = result.findings.filter((f) => f.severity === "YELLOW");

  const ALL_CHECK_IDS = [
    "R1","R2","R3","R4","R5","R6","R7","R8","R9","R10",
    "A1","A2","A3","A4","A5","A6","A7","A8","A9","A10",
    "A11","A12","A13","A14","A15","A16","A17","A18","A19","A20",
    "A21","A22","A23","A24","A25","A26","A27",
  ];

  // When R3 flags a section as missing, AI checks for that section had no
  // content to evaluate — exclude them from "passed" to avoid false reassurance.
  const SECTION_TO_AI_CHECKS: Record<string, string[]> = {
    "Safety & Emergency":    ["A2"],
    "Important Places":      ["A18"],
    "Must-Try Local Dishes": ["A8"],
    "Getting Around":        ["A9"],
    "Cultural Etiquette":    ["A10"],
    "Tailored Packing List": ["A5"],
    "Thank You":             ["A11"],
  };
  const notApplicableIds = new Set<string>();
  result.findings
    .filter((f) => f.check_id === "R3")
    .forEach((f) => {
      Object.entries(SECTION_TO_AI_CHECKS).forEach(([keyword, checks]) => {
        if (f.description.toLowerCase().includes(keyword.toLowerCase())) {
          checks.forEach((c) => notApplicableIds.add(c));
        }
      });
    });

  const failedIds = new Set(result.findings.map((f) => f.check_id));
  const passedIds = ALL_CHECK_IDS.filter(
    (id) => !failedIds.has(id) && !notApplicableIds.has(id)
  );

  return (
    <div className="max-w-3xl mx-auto space-y-5">

      {/* Summary bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-red-600">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" />
            {result.meta.red_count} RED
          </span>
          <span className="flex items-center gap-1.5 text-sm font-semibold text-yellow-600">
            <span className="w-2.5 h-2.5 rounded-full bg-yellow-400 inline-block" />
            {result.meta.yellow_count} YELLOW
          </span>
          <span className="flex items-center gap-1.5 text-sm font-semibold text-green-600">
            <span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" />
            {result.meta.passed_count} passed
          </span>
          <span className="text-xs text-slate-400">{result.meta.model}</span>
        </div>
        <button
          onClick={onReset}
          className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 font-medium"
        >
          Verify Another File
        </button>
      </div>

      {/* AI narratives */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="flex border-b border-slate-100">
          {NARRATIVE_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setNarrativeTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium flex-1 ${narrativeTab === t.key ? "bg-blue-50 text-blue-600 border-b-2 border-blue-500" : "text-slate-500 hover:bg-slate-50"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="p-4 text-sm text-slate-700 leading-relaxed min-h-[60px]">
          {result.narratives[narrativeTab] || <span className="text-slate-400 italic">No narrative available.</span>}
        </div>
      </div>

      {/* RED findings */}
      {redFindings.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-red-600 mb-2 flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" />
            RED ISSUES ({redFindings.length})
          </h2>
          <div className="space-y-2">
            {redFindings.map((f, i) => <FindingCard key={i} finding={f} />)}
          </div>
        </section>
      )}

      {/* YELLOW findings */}
      {yellowFindings.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-yellow-600 mb-2 flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-yellow-400 inline-block" />
            YELLOW ISSUES ({yellowFindings.length})
          </h2>
          <div className="space-y-2">
            {yellowFindings.map((f, i) => <FindingCard key={i} finding={f} />)}
          </div>
        </section>
      )}

      {/* Passed checks (collapsed by default) */}
      {passedIds.length > 0 && (
        <section>
          <button
            onClick={() => setPassedOpen((o) => !o)}
            className="text-sm font-semibold text-green-600 flex items-center gap-1.5 mb-2"
          >
            <span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" />
            PASSED ({passedIds.length})
            <span className="text-slate-400 font-normal ml-1">{passedOpen ? "▲" : "▼"}</span>
          </button>
          {passedOpen && (
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-1 pr-3 font-medium w-10">ID</th>
                  <th className="py-1 font-medium">Check</th>
                </tr>
              </thead>
              <tbody>
                {passedIds.map((id) => {
                  const meta = CHECK_DESCRIPTIONS[id];
                  return (
                    <tr key={id} className="border-b border-slate-100 last:border-0">
                      <td className="py-1 pr-3 font-mono text-green-700 font-semibold">{id}</td>
                      <td className="py-1 text-slate-700">{meta?.label ?? id}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      )}

      {result.meta.red_count === 0 && result.meta.yellow_count === 0 && (
        <div className="text-center py-8 text-green-600 font-medium">
          All checks passed — guide looks good to send!
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload view
// ---------------------------------------------------------------------------

function Upload({ onResult }: { onResult: (r: VerifyResult) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(f: File | undefined | null) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".docx")) {
      setError("Only .docx files are accepted");
      return;
    }
    setError(null);
    setFile(f);
  }

  async function runVerification() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.verifyAig(file);
      onResult(result);
    } catch (e: any) {
      setError(e?.message || "Verification failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto mt-12 space-y-4">
      <div className="text-center mb-6">
        <h1 className="text-xl font-bold text-slate-900">AIG Verification</h1>
        <p className="text-sm text-slate-500 mt-1">Upload a generated guide to run quality checks</p>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => !loading && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
          dragging ? "border-blue-400 bg-blue-50" :
          file ? "border-green-400 bg-green-50" :
          "border-slate-300 hover:border-slate-400 bg-white"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".docx"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
        {file ? (
          <>
            <div className="text-3xl mb-2">📄</div>
            <p className="text-sm font-medium text-slate-800">{file.name}</p>
            <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(0)} KB — click to change</p>
          </>
        ) : (
          <>
            <div className="text-3xl mb-2">📂</div>
            <p className="text-sm font-medium text-slate-700">Drop your AIG (.docx) here</p>
            <p className="text-xs text-slate-400 mt-1">or click to browse</p>
          </>
        )}
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <button
        disabled={!file || loading}
        onClick={runVerification}
        className={`w-full py-3 rounded-xl text-sm font-semibold transition-colors ${
          !file || loading
            ? "bg-slate-100 text-slate-400 cursor-not-allowed"
            : "bg-blue-600 text-white hover:bg-blue-700"
        }`}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
            Verifying… this usually takes 15–30 seconds
          </span>
        ) : (
          "Run Verification"
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export function VerifyTab() {
  const [result, setResult] = useState<VerifyResult | null>(null);
  return result
    ? <Results result={result} onReset={() => setResult(null)} />
    : <Upload onResult={setResult} />;
}
