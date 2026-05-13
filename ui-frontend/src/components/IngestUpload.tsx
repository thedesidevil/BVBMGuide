import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import type { IngestFile } from "../types";

interface IngestUploadProps {
  sessionId: string | null;
  files: IngestFile[];
  onSessionCreated: (sessionId: string, files: IngestFile[]) => void;
  onFilesChanged: (files: IngestFile[]) => void;
  onNext: () => void;
  canAdvance: boolean;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function IngestUpload({ sessionId, files, onSessionCreated, onFilesChanged, onNext, canAdvance }: IngestUploadProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(async (fileList: FileList | File[]) => {
    const validFiles = Array.from(fileList).filter((f) => {
      const ext = f.name.split(".").pop()?.toLowerCase();
      return ext === "pdf" || ext === "docx" || ext === "zip";
    });
    if (validFiles.length === 0) return;

    setUploading(true);
    try {
      if (!sessionId) {
        const result = await api.ingestUpload(validFiles);
        onSessionCreated(result.session_id, result.files as IngestFile[]);
      } else {
        const result = await api.ingestUploadMore(sessionId, validFiles);
        onFilesChanged(result.files as IngestFile[]);
      }
    } catch (e: any) {
      alert(`Upload failed: ${e.message}`);
    } finally {
      setUploading(false);
    }
  }, [sessionId, onSessionCreated, onFilesChanged]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const handleRemove = async (fileId: string) => {
    if (!sessionId) return;
    const result = await api.ingestDeleteFile(sessionId, fileId);
    onFilesChanged(result.files as IngestFile[]);
  };

  return (
    <div>
      <h2 className="text-lg font-bold text-slate-900 mb-4">Upload Documents</h2>
      <p className="text-sm text-slate-500 mb-6">
        Upload AIG documents (PDF, DOCX, or ZIP) to add to the library. ZIP files will be extracted automatically.
      </p>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
          dragging ? "border-blue-400 bg-blue-50" : "border-slate-300 hover:border-slate-400 hover:bg-slate-50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.zip"
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
        <div className="text-4xl mb-3 text-slate-300">&#128194;</div>
        <p className="text-sm font-medium text-slate-600">
          {uploading ? "Uploading..." : "Drop files here or click to browse"}
        </p>
        <p className="text-xs text-slate-400 mt-1">PDF, DOCX, or ZIP — max 50MB per file</p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">{files.length} file(s) ready</h3>
          <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
            {files.map((file) => (
              <div key={file.id} className="flex items-center gap-3 px-4 py-3">
                <span className={`text-xs font-bold uppercase px-2 py-0.5 rounded ${
                  file.type === "pdf" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"
                }`}>{file.type}</span>
                <span className="flex-1 text-sm text-slate-700 truncate">{file.filename}</span>
                <span className="text-xs text-slate-400">{formatSize(file.size)}</span>
                <button
                  onClick={() => handleRemove(file.id)}
                  className="text-red-400 hover:text-red-600 text-sm px-2 py-1 rounded hover:bg-red-50"
                >Remove</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Next button */}
      <div className="flex justify-end mt-8">
        <button
          onClick={onNext}
          disabled={!canAdvance}
          className="px-6 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Proceed to Classify →
        </button>
      </div>
    </div>
  );
}
