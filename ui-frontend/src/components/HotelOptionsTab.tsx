import { useRef, useState } from "react";
import { api } from "../api/client";
import type {
  HotelOptionsParseResult,
  HotelOptionsUnknownCode,
  HotelOptionsNotFound,
} from "../types";

type TabState = "upload" | "preview" | "generating" | "done" | "error";

export function HotelOptionsTab() {
  const [state, setState] = useState<TabState>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [parseResult, setParseResult] = useState<HotelOptionsParseResult | null>(null);
  const [resolvedCodes, setResolvedCodes] = useState<Record<string, string>>({});
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [docBlob, setDocBlob] = useState<Blob | null>(null);
  const [aiCostUsd, setAiCostUsd] = useState<number | null>(null);
  const [mapsApiCallsGenerate, setMapsApiCallsGenerate] = useState<number>(0);
  const [error, setError] = useState<string>("");
  const [parsing, setParsing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const allResolved =
    parseResult !== null &&
    parseResult.unknown_codes.every((u) => resolvedCodes[u.code]?.trim()) &&
    parseResult.not_found.every((nf) => overrides[nf.sheet_name]?.trim());

  function reset() {
    setState("upload");
    setFile(null);
    setParseResult(null);
    setResolvedCodes({});
    setOverrides({});
    setDocBlob(null);
    setAiCostUsd(null);
    setMapsApiCallsGenerate(0);
    setError("");
  }

  async function handleParse(f: File) {
    setParsing(true);
    setError("");
    try {
      const result = await api.parseHotelOptions(f);
      setParseResult(result);
      setState("preview");
    } catch (e: any) {
      setError(e.message || "Parse failed");
      setState("error");
    } finally {
      setParsing(false);
    }
  }

  async function handleGenerate() {
    if (!file || !parseResult) return;
    setState("generating");
    try {
      const { blob, aiCostUsd: cost, mapsApiCalls } = await api.generateHotelOptions(file, resolvedCodes, overrides);
      setDocBlob(blob);
      setAiCostUsd(cost);
      setMapsApiCallsGenerate(mapsApiCalls);
      setState("done");
    } catch (e: any) {
      setError(e.message || "Generation failed");
      setState("error");
    }
  }

  function handleCodeBlur(code: string, meaning: string) {
    if (!meaning.trim()) return;
    api.saveHotelCode(code, meaning).catch(() => {});
  }

  function downloadDoc() {
    if (!docBlob || !parseResult) return;
    const url = URL.createObjectURL(docBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Hotel Options - ${parseResult.destination || "document"}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (state === "upload" || (state === "error" && !parseResult)) {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-4">
        <h2 className="text-lg font-semibold text-slate-800">Hotel Options Generator</h2>
        <div
          className="border-2 border-dashed border-slate-300 rounded-xl p-12 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) { setFile(f); handleParse(f); }
          }}
        >
          <p className="text-slate-500 text-sm">
            {parsing
              ? "Parsing…"
              : "Drop your hotel comparison .xlsx here, or click to browse"}
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) { setFile(f); handleParse(f); }
            }}
          />
        </div>
        {error && <p className="text-red-600 text-sm">{error}</p>}
      </div>
    );
  }

  if (state === "generating") {
    return (
      <div className="max-w-xl mx-auto py-16 text-center">
        <p className="text-slate-500 text-sm animate-pulse">
          Enriching hotels and building document…
        </p>
      </div>
    );
  }

  if (state === "done") {
    return (
      <div className="max-w-xl mx-auto py-16 text-center space-y-4">
        <p className="text-green-600 font-medium">Document ready!</p>
        <div className="flex justify-center gap-6 text-xs text-slate-500">
          {aiCostUsd !== null && (
            <span>AI cost: <span className="font-medium text-slate-700">${aiCostUsd.toFixed(4)}</span></span>
          )}
          {mapsApiCallsGenerate > 0 && (
            <span>Maps lookups: <span className="font-medium text-slate-700">{mapsApiCallsGenerate}</span></span>
          )}
        </div>
        <button
          onClick={downloadDoc}
          className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium"
        >
          Download .docx
        </button>
        <div>
          <button onClick={reset} className="text-sm text-slate-500 hover:text-slate-700 underline">
            Start over
          </button>
        </div>
      </div>
    );
  }

  if (state === "error" && parseResult) {
    return (
      <div className="max-w-xl mx-auto py-16 space-y-4">
        <p className="text-red-600 text-sm">{error}</p>
        <button
          onClick={() => setState("preview")}
          className="px-4 py-2 bg-slate-100 rounded text-sm hover:bg-slate-200"
        >
          Try again
        </button>
        <button onClick={reset} className="ml-4 text-sm text-slate-500 underline">
          Start over
        </button>
      </div>
    );
  }

  // Preview state
  const result = parseResult!;
  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">
            {result.client_name ? `${result.client_name} — ` : ""}
            {result.destination}
          </h2>
          {result.requirements && (
            <p className="text-xs text-slate-500 mt-0.5">{result.requirements}</p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          {result.maps_api_calls > 0 && (
            <span className="text-xs text-slate-400">{result.maps_api_calls} Google Places lookups</span>
          )}
          <button onClick={reset} className="text-sm text-blue-500 hover:text-blue-700 underline">
            Upload a different file
          </button>
        </div>
      </div>

      {result.grouped_by_sections
        ? result.plans.map((plan) => (
            <div key={plan.label} className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wide px-1">
                {plan.label}
              </h3>
              {plan.hotels.map((h) => {
                const ourPrice = h.discounted_price > 0 ? h.discounted_price : h.online_price;
                return (
                  <div key={h.name} className="text-sm border-l-2 border-slate-200 pl-3 space-y-0.5">
                    <p className="font-medium text-slate-800">{h.name}</p>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
                      {h.category && <span>🏨 {h.category}</span>}
                      {h.room_type && <span>🛏 {h.room_type}</span>}
                      {h.meal_type && <span>🍽 {h.meal_type}</span>}
                      {h.cancellation && <span>🔄 {h.cancellation}</span>}
                    </div>
                    <p className="text-xs text-slate-500">
                      Online: ₹{h.online_price.toLocaleString("en-IN")} · Our price: ₹{ourPrice.toLocaleString("en-IN")}
                      {h.customer_discount > 0 && ` · Save ₹${h.customer_discount.toLocaleString("en-IN")} (${h.discount_pct.toFixed(1)}% off)`}
                    </p>
                  </div>
                );
              })}
            </div>
          ))
        : result.plans.map((plan) => (
            <div key={plan.label} className="bg-white border border-slate-200 rounded-xl p-4">
              <h3 className="font-semibold text-slate-700 mb-3">{plan.label}</h3>
              <div className="space-y-3 mb-3">
                {plan.hotels.map((h) => (
                  <div key={h.name} className="text-sm border-l-2 border-slate-200 pl-3 space-y-0.5">
                    <p className="font-medium text-slate-800">{h.name}</p>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
                      {h.dates && <span>📅 {h.dates}</span>}
                      {h.category && <span>🏨 {h.category}</span>}
                      {h.room_type && <span>🛏 {h.room_type}</span>}
                      {h.meal_type && <span>🍽 {h.meal_type}</span>}
                      {h.cancellation && <span>🔄 {h.cancellation}</span>}
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-xs text-slate-500">
                Online: ₹{plan.pricing.total_online_price.toLocaleString("en-IN")} ·{" "}
                Our price: ₹{plan.pricing.discounted_price.toLocaleString("en-IN")}
              </p>
            </div>
          ))}

      {result.unknown_codes.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-yellow-800">
            Unknown codes — please define them:
          </p>
          {result.unknown_codes.map((u: HotelOptionsUnknownCode) => (
            <div key={`${u.plan_label}-${u.code}`} className="flex items-center gap-3">
              <span className="text-sm text-slate-700 w-32 shrink-0">
                <code className="bg-yellow-100 px-1 rounded">{u.code}</code>
                <span className="text-xs text-slate-400 ml-1">({u.plan_label})</span>
              </span>
              <input
                type="text"
                placeholder={`What does "${u.code}" mean?`}
                className="flex-1 text-sm border border-slate-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
                value={resolvedCodes[u.code] || ""}
                onChange={(e) =>
                  setResolvedCodes((prev) => ({ ...prev, [u.code]: e.target.value }))
                }
                onBlur={(e) => handleCodeBlur(u.code, e.target.value)}
              />
            </div>
          ))}
        </div>
      )}

      {result.not_found.length > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 space-y-3">
          <p className="text-sm font-medium text-orange-800">
            Hotels not found on Google — paste their Maps links:
          </p>
          {result.not_found.map((nf: HotelOptionsNotFound) => (
            <div key={`${nf.plan_label}-${nf.sheet_name}`} className="flex items-center gap-3">
              <span
                className="text-sm text-slate-700 w-48 shrink-0 truncate"
                title={nf.sheet_name}
              >
                {nf.sheet_name}
              </span>
              <input
                type="text"
                placeholder="Paste Google Maps link…"
                className="flex-1 text-sm border border-slate-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
                value={overrides[nf.sheet_name] || ""}
                onChange={(e) =>
                  setOverrides((prev) => ({ ...prev, [nf.sheet_name]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
      )}

      <button
        onClick={handleGenerate}
        disabled={!allResolved}
        className={`w-full py-3 rounded-xl font-medium text-sm transition-colors ${
          allResolved
            ? "bg-blue-600 text-white hover:bg-blue-700"
            : "bg-slate-200 text-slate-400 cursor-not-allowed"
        }`}
      >
        Generate Document
      </button>
    </div>
  );
}
