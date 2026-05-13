import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { IngestFile } from "../types";

interface IngestClassifyProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onNext: () => void;
  canAdvance: boolean;
}

export function IngestClassify({ sessionId, files, onFilesChanged, onBack, onNext, canAdvance }: IngestClassifyProps) {
  const [folders, setFolders] = useState<string[]>([]);
  const [classifying, setClassifying] = useState(false);
  const [newFolderInput, setNewFolderInput] = useState<Record<string, string>>({});

  useEffect(() => {
    api.ingestFolders().then((r) => setFolders(r.folders));
  }, []);

  const handleClassifyAll = async () => {
    setClassifying(true);
    try {
      const result = await api.ingestClassify(sessionId);
      onFilesChanged(result.files as IngestFile[]);
    } finally {
      setClassifying(false);
    }
  };

  const handleOverride = async (fileId: string, folder: string) => {
    if (folder === "__new__") return;
    await api.ingestUpdateFile(sessionId, fileId, { assigned_folder: folder });
    onFilesChanged(files.map((f) => f.id === fileId ? { ...f, assigned_folder: folder, state: "classified" as const, is_new_folder: !folders.includes(folder) } : f));
  };

  const handleNewFolder = async (fileId: string) => {
    const folder = newFolderInput[fileId]?.trim();
    if (!folder) return;
    await api.ingestUpdateFile(sessionId, fileId, { assigned_folder: folder });
    onFilesChanged(files.map((f) => f.id === fileId ? { ...f, assigned_folder: folder, state: "classified" as const, is_new_folder: true } : f));
    if (!folders.includes(folder)) setFolders([...folders, folder].sort());
    setNewFolderInput((prev) => ({ ...prev, [fileId]: "" }));
  };

  const handleExclude = async (fileId: string, excluded: boolean) => {
    await api.ingestUpdateFile(sessionId, fileId, { excluded });
    onFilesChanged(files.map((f) => f.id === fileId ? { ...f, excluded } : f));
  };

  const activeFiles = files.filter((f) => f.state !== "persisted");

  return (
    <div>
      <h2 className="text-lg font-bold text-slate-900 mb-2">Classify Documents</h2>
      <p className="text-sm text-slate-500 mb-6">
        AI will suggest which library folder each file belongs in. You can override the suggestion or exclude files.
      </p>

      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={handleClassifyAll}
          disabled={classifying}
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-60"
        >
          {classifying ? "Classifying..." : "Classify All"}
        </button>
        {classifying && <span className="text-sm text-slate-400">Running AI classification on all files...</span>}
      </div>

      {/* Classification table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b-2 border-slate-200">
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Filename</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">AI Suggestion</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Confidence</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Assigned Folder</th>
              <th className="text-center px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Exclude</th>
            </tr>
          </thead>
          <tbody>
            {activeFiles.map((file) => (
              <tr
                key={file.id}
                className={`border-b border-slate-100 ${file.excluded ? "opacity-50 bg-slate-50" : ""}`}
              >
                <td className="px-4 py-3 font-medium text-slate-700">{file.filename}</td>
                <td className="px-4 py-3">
                  {file.assigned_folder ? (
                    <span className="text-xs font-medium bg-blue-100 text-blue-700 px-2 py-1 rounded-full">
                      {file.assigned_folder}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400 italic">Not classified</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {file.state === "classified" && (
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                      file.is_new_folder ? "text-red-600" : "text-green-600"
                    }`}>
                      <span className={`w-2 h-2 rounded-full ${file.is_new_folder ? "bg-red-500" : "bg-green-500"}`} />
                      {file.is_new_folder ? "Low" : "High"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {!file.excluded && (
                    <div className="flex items-center gap-2">
                      <select
                        value={file.assigned_folder || ""}
                        onChange={(e) => handleOverride(file.id, e.target.value)}
                        className="text-sm border border-slate-200 rounded-md px-2 py-1.5 max-w-[200px]"
                      >
                        <option value="">Select folder...</option>
                        {folders.map((f) => <option key={f} value={f}>{f}</option>)}
                        <option value="__new__">+ New folder...</option>
                      </select>
                      {(!file.assigned_folder || !folders.includes(file.assigned_folder)) && file.state === "uploaded" && (
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            placeholder="Folder name"
                            value={newFolderInput[file.id] || ""}
                            onChange={(e) => setNewFolderInput((prev) => ({ ...prev, [file.id]: e.target.value }))}
                            className="text-sm border border-slate-200 rounded px-2 py-1 w-32"
                          />
                          <button
                            onClick={() => handleNewFolder(file.id)}
                            className="text-xs text-blue-600 font-medium hover:underline"
                          >Set</button>
                        </div>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  <input
                    type="checkbox"
                    checked={file.excluded}
                    onChange={(e) => handleExclude(file.id, e.target.checked)}
                    className="w-4 h-4 accent-slate-500"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Navigation */}
      <div className="flex justify-between mt-8">
        <button onClick={onBack} className="px-4 py-2 text-sm font-medium text-slate-600 border border-slate-200 rounded-md hover:bg-slate-50">
          ← Back to Upload
        </button>
        <button
          onClick={onNext}
          disabled={!canAdvance}
          className="px-6 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Proceed to Extract →
        </button>
      </div>
    </div>
  );
}
