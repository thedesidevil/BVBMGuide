import { useState } from "react";
import { IngestUpload } from "./IngestUpload";
import { IngestClassify } from "./IngestClassify";
import { IngestExtract } from "./IngestExtract";
import type { IngestFile } from "../types";

interface IngestWizardProps {
  onDone: () => void;
}

type Step = "upload" | "classify" | "extract";

const STEPS: { key: Step; label: string; number: number }[] = [
  { key: "upload", label: "Upload", number: 1 },
  { key: "classify", label: "Classify", number: 2 },
  { key: "extract", label: "Extract & Persist", number: 3 },
];

export function IngestWizard({ onDone }: IngestWizardProps) {
  const [step, setStep] = useState<Step>("upload");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [files, setFiles] = useState<IngestFile[]>([]);

  const canAdvanceToClassify = files.length > 0 && files.some((f) => !f.excluded);
  const canAdvanceToExtract = files.every(
    (f) => f.excluded || (f.state === "classified" && f.assigned_folder)
  ) && files.some((f) => !f.excluded);

  return (
    <div>
      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
              step === s.key ? "bg-blue-600 text-white" :
              STEPS.findIndex((x) => x.key === step) > i ? "bg-green-500 text-white" :
              "bg-slate-200 text-slate-500"
            }`}>
              {STEPS.findIndex((x) => x.key === step) > i ? "✓" : s.number}
            </div>
            <span className={`text-sm font-medium ${step === s.key ? "text-blue-600" : "text-slate-500"}`}>
              {s.label}
            </span>
            {i < STEPS.length - 1 && <div className="w-12 h-px bg-slate-300 mx-2" />}
          </div>
        ))}
      </div>

      {/* Step content */}
      {step === "upload" && (
        <IngestUpload
          sessionId={sessionId}
          files={files}
          onSessionCreated={(sid, f) => { setSessionId(sid); setFiles(f); }}
          onFilesChanged={setFiles}
          onNext={() => setStep("classify")}
          canAdvance={canAdvanceToClassify}
        />
      )}
      {step === "classify" && sessionId && (
        <IngestClassify
          sessionId={sessionId}
          files={files}
          onFilesChanged={setFiles}
          onBack={() => setStep("upload")}
          onNext={() => setStep("extract")}
          canAdvance={canAdvanceToExtract}
        />
      )}
      {step === "extract" && sessionId && (
        <IngestExtract
          sessionId={sessionId}
          files={files}
          onFilesChanged={setFiles}
          onBack={() => setStep("classify")}
          onDone={onDone}
        />
      )}
    </div>
  );
}
