import type { IngestFile } from "../types";

interface IngestUploadProps {
  sessionId: string | null;
  files: IngestFile[];
  onSessionCreated: (sessionId: string, files: IngestFile[]) => void;
  onFilesChanged: (files: IngestFile[]) => void;
  onNext: () => void;
  canAdvance: boolean;
}

export function IngestUpload({ onNext, canAdvance }: IngestUploadProps) {
  return (
    <div>
      <p className="text-slate-400">Upload step placeholder</p>
      <button onClick={onNext} disabled={!canAdvance} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-40">
        Proceed to Classify
      </button>
    </div>
  );
}
