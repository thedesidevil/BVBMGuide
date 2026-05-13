import type { IngestFile } from "../types";

interface IngestClassifyProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onNext: () => void;
  canAdvance: boolean;
}

export function IngestClassify({ onBack, onNext, canAdvance }: IngestClassifyProps) {
  return (
    <div>
      <p className="text-slate-400">Classify step placeholder</p>
      <div className="flex gap-3 mt-4">
        <button onClick={onBack} className="px-4 py-2 border border-slate-200 rounded">Back</button>
        <button onClick={onNext} disabled={!canAdvance} className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-40">Proceed to Extract</button>
      </div>
    </div>
  );
}
