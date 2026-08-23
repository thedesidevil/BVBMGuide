import { useRef, useState } from "react";
import { api } from "../api/client";
import { VerifyTab } from "./VerifyTab";

// ---------------------------------------------------------------------------
// PrepPanel — left half of the AIG page
// ---------------------------------------------------------------------------

type PrepState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "done"; libraryContext: string; clientProfile: string; filenameBase: string }
  | { phase: "error"; message: string };

function triggerDownload(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
}

function PrepPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<PrepState>({ phase: "idle" });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(f: File | undefined | null) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".docx")) {
      setState({ phase: "error", message: "Only .docx files are accepted" });
      return;
    }
    setState({ phase: "idle" });
    setFile(f);
  }

  async function runPrep() {
    if (!file) return;
    setState({ phase: "loading" });
    try {
      const result = await api.aigPrep(file);
      setState({
        phase: "done",
        libraryContext: result.library_context,
        clientProfile: result.client_profile,
        filenameBase: result.filename_base,
      });
    } catch (e: any) {
      setState({ phase: "error", message: e?.message || "Prep failed" });
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="mb-4">
        <h2 className="text-base font-bold text-slate-900">Generate Context File</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Upload a client input file to generate library context + client profile for ChatGPT
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => state.phase !== "loading" && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors mb-4 ${
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
            <div className="text-2xl mb-1">📄</div>
            <p className="text-sm font-medium text-slate-800">{file.name}</p>
            <p className="text-xs text-slate-500 mt-0.5">
              {(file.size / 1024).toFixed(0)} KB — click to change
            </p>
          </>
        ) : (
          <>
            <div className="text-2xl mb-1">📂</div>
            <p className="text-sm font-medium text-slate-700">Drop input .docx here</p>
            <p className="text-xs text-slate-400 mt-0.5">notes file or service voucher</p>
          </>
        )}
      </div>

      {/* Error */}
      {state.phase === "error" && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4">
          {state.message}
        </div>
      )}

      {/* Generate button */}
      {state.phase !== "done" && (
        <button
          disabled={!file || state.phase === "loading"}
          onClick={runPrep}
          className={`w-full py-3 rounded-xl text-sm font-semibold transition-colors mb-4 ${
            !file || state.phase === "loading"
              ? "bg-slate-100 text-slate-400 cursor-not-allowed"
              : "bg-blue-600 text-white hover:bg-blue-700"
          }`}
        >
          {state.phase === "loading" ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
              Generating context…
            </span>
          ) : (
            "Generate Context Files"
          )}
        </button>
      )}

      {/* Download results */}
      {state.phase === "done" && (
        <div className="space-y-3">
          <div className="rounded-xl bg-green-50 border border-green-200 p-4">
            <p className="text-sm font-semibold text-green-800 mb-3">
              Context files ready — download and upload to ChatGPT
            </p>
            <div className="space-y-2">
              <button
                onClick={() =>
                  triggerDownload(
                    state.libraryContext,
                    `${state.filenameBase}_library_context.md`
                  )
                }
                className="w-full flex items-center gap-2 px-4 py-2.5 bg-white border border-green-300 rounded-lg text-sm font-medium text-green-800 hover:bg-green-50 transition-colors"
              >
                <span>📥</span>
                <span>{state.filenameBase}_library_context.md</span>
              </button>
              <button
                onClick={() =>
                  triggerDownload(
                    state.clientProfile,
                    `${state.filenameBase}_client_profile.md`
                  )
                }
                className="w-full flex items-center gap-2 px-4 py-2.5 bg-white border border-green-300 rounded-lg text-sm font-medium text-green-800 hover:bg-green-50 transition-colors"
              >
                <span>📥</span>
                <span>{state.filenameBase}_client_profile.md</span>
              </button>
            </div>
          </div>
          <button
            onClick={() => { setFile(null); setState({ phase: "idle" }); }}
            className="w-full text-sm text-slate-500 hover:text-slate-700 py-2"
          >
            Process another file
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AIGTab — two-panel page root
// ---------------------------------------------------------------------------

export function AIGTab() {
  return (
    <div className="flex gap-6 h-full">
      {/* Left: Generate Context */}
      <div className="flex-1 bg-white border border-slate-200 rounded-xl p-6 overflow-y-auto">
        <PrepPanel />
      </div>

      {/* Divider */}
      <div className="w-px bg-slate-200 self-stretch" />

      {/* Right: Verify */}
      <div className="flex-1 overflow-y-auto">
        <div className="mb-4">
          <h2 className="text-base font-bold text-slate-900">AIG Verification</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Upload a generated guide to run quality checks
          </p>
        </div>
        <VerifyTab hideHeading />
      </div>
    </div>
  );
}
