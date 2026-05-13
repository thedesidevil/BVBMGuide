import type { IngestFile } from "../types";

interface IngestExtractProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onDone: () => void;
}

export function IngestExtract({ onBack, onDone }: IngestExtractProps) {
  return (
    <div>
      <p className="text-slate-400">Extract & Persist step placeholder</p>
      <div className="flex gap-3 mt-4">
        <button onClick={onBack} className="px-4 py-2 border border-slate-200 rounded">Back</button>
        <button onClick={onDone} className="px-4 py-2 bg-emerald-600 text-white rounded">Done</button>
      </div>
    </div>
  );
}
