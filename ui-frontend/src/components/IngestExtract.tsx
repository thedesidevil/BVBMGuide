import { useState, useCallback } from "react";
import { api } from "../api/client";
import { EditableTable } from "./EditableTable";
import type { IngestFile } from "../types";

interface IngestExtractProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onDone: () => void;
}

type Category =
  | "restaurants"
  | "attractions"
  | "hotels"
  | "local_dishes"
  | "souvenirs"
  | "phrases"
  | "safety_tips"
  | "connectivity_tips"
  | "transport_options"
  | "health_tips"
  | "emergency_contacts";

const CATEGORIES: { key: Category; label: string }[] = [
  { key: "restaurants", label: "Restaurants" },
  { key: "attractions", label: "Attractions" },
  { key: "hotels", label: "Hotels" },
  { key: "local_dishes", label: "Local Dishes" },
  { key: "souvenirs", label: "Souvenirs" },
  { key: "phrases", label: "Phrases" },
  { key: "safety_tips", label: "Safety Tips" },
  { key: "connectivity_tips", label: "Connectivity" },
  { key: "transport_options", label: "Transport" },
  { key: "health_tips", label: "Health Tips" },
  { key: "emergency_contacts", label: "Emergency" },
];

const COLUMNS: Record<Category, { key: string; label: string; type: "text" | "checkbox" | "tags" }[]> = {
  restaurants: [
    { key: "name", label: "Name", type: "text" },
    { key: "cuisine_type", label: "Cuisine", type: "text" },
    { key: "hours", label: "Hours", type: "text" },
    { key: "price_range", label: "Price Range", type: "text" },
    { key: "vegetarian_friendly", label: "Veg Friendly", type: "checkbox" },
  ],
  attractions: [
    { key: "name", label: "Name", type: "text" },
    { key: "description", label: "Description", type: "text" },
    { key: "hours", label: "Hours", type: "text" },
    { key: "entry_fee", label: "Entry Fee", type: "text" },
  ],
  hotels: [
    { key: "name", label: "Name", type: "text" },
    { key: "description", label: "Description", type: "text" },
  ],
  local_dishes: [
    { key: "name", label: "Name", type: "text" },
    { key: "description", label: "Description", type: "text" },
  ],
  souvenirs: [
    { key: "name", label: "Name", type: "text" },
    { key: "description", label: "Description", type: "text" },
  ],
  phrases: [
    { key: "english", label: "English", type: "text" },
    { key: "local", label: "Local", type: "text" },
  ],
  safety_tips: [
    { key: "tip", label: "Tip", type: "text" },
  ],
  connectivity_tips: [
    { key: "tip", label: "Tip", type: "text" },
  ],
  transport_options: [
    { key: "name", label: "Name", type: "text" },
    { key: "description", label: "Description", type: "text" },
  ],
  health_tips: [
    { key: "tip", label: "Tip", type: "text" },
  ],
  emergency_contacts: [
    { key: "name", label: "Name", type: "text" },
    { key: "description", label: "Description", type: "text" },
  ],
};

function FileStatusIcon({ state }: { state: IngestFile["state"] }) {
  switch (state) {
    case "extracted":
    case "persisted":
      return <span className="text-emerald-500 font-bold">&#10003;</span>;
    case "failed":
      return <span className="text-red-500 font-bold">&#10007;</span>;
    case "excluded":
      return <span className="text-slate-400">&ndash;</span>;
    default:
      return <span className="text-slate-300">&bull;</span>;
  }
}

export function IngestExtract({
  sessionId,
  files,
  onFilesChanged,
  onBack,
  onDone,
}: IngestExtractProps) {
  const [extracting, setExtracting] = useState(false);
  const [persisting, setPersisting] = useState(false);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<Category>("restaurants");
  const [error, setError] = useState<string | null>(null);
  const [persistResult, setPersistResult] = useState<{
    persisted_files: number;
    affected_cities: string[];
  } | null>(null);

  const extractableFiles = files.filter((f) => !f.excluded && f.state !== "failed");
  const extractedFiles = files.filter((f) => f.state === "extracted");
  const selectedFile = files.find((f) => f.id === selectedFileId) ?? null;

  const handleStartExtraction = useCallback(async () => {
    setExtracting(true);
    setError(null);
    try {
      await api.ingestExtract(sessionId);
      // Poll status to get extraction results
      const result = await api.ingestStatus(sessionId);
      onFilesChanged(result.files as IngestFile[]);
      // Auto-select first extracted file
      const firstExtracted = (result.files as IngestFile[]).find(
        (f) => f.state === "extracted"
      );
      if (firstExtracted) {
        setSelectedFileId(firstExtracted.id);
      }
    } catch (err: any) {
      setError(err.message || "Extraction failed");
    } finally {
      setExtracting(false);
    }
  }, [sessionId, onFilesChanged]);

  const handleDataChange = useCallback(
    async (fileId: string, category: Category, newData: Record<string, any>[]) => {
      const file = files.find((f) => f.id === fileId);
      if (!file || !file.data) return;

      const updatedData = { ...file.data, [category]: newData };
      const updatedFiles = files.map((f) =>
        f.id === fileId ? { ...f, data: updatedData } : f
      );
      onFilesChanged(updatedFiles);

      // Save to backend
      try {
        await api.ingestSaveData(sessionId, fileId, updatedData);
      } catch (err: any) {
        setError(`Failed to save: ${err.message}`);
      }
    },
    [sessionId, files, onFilesChanged]
  );

  const handleDeleteRow = useCallback(
    (fileId: string, category: Category, index: number, _reason: string) => {
      const file = files.find((f) => f.id === fileId);
      if (!file || !file.data) return;

      const categoryData = [...(file.data[category] || [])];
      categoryData.splice(index, 1);
      handleDataChange(fileId, category, categoryData);
    },
    [files, handleDataChange]
  );

  const handlePersist = useCallback(async () => {
    setPersisting(true);
    setError(null);
    try {
      const result = await api.ingestPersist(sessionId);
      setPersistResult(result);
    } catch (err: any) {
      setError(err.message || "Persist failed");
    } finally {
      setPersisting(false);
    }
  }, [sessionId]);

  // Success screen after persist
  if (persistResult) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mb-6">
          <span className="text-emerald-600 text-3xl">&#10003;</span>
        </div>
        <h2 className="text-xl font-semibold text-slate-800 mb-2">
          Successfully Persisted
        </h2>
        <p className="text-slate-600 mb-6">
          {persistResult.persisted_files} file{persistResult.persisted_files !== 1 ? "s" : ""} merged
          into the library database.
        </p>
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 mb-8 w-full max-w-md">
          <h3 className="text-sm font-semibold text-slate-500 uppercase mb-2">
            Affected Cities
          </h3>
          <div className="flex flex-wrap gap-2">
            {persistResult.affected_cities.map((city) => (
              <span
                key={city}
                className="bg-blue-100 text-blue-800 text-sm px-3 py-1 rounded-full"
              >
                {city}
              </span>
            ))}
          </div>
        </div>
        <button
          onClick={onDone}
          className="px-6 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors"
        >
          Done
        </button>
      </div>
    );
  }

  const hasExtractedData = extractedFiles.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">
            Extract & Persist
          </h2>
          <p className="text-sm text-slate-500">
            {hasExtractedData
              ? `${extractedFiles.length} of ${extractableFiles.length} files extracted`
              : `${extractableFiles.length} files ready for extraction`}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={onBack}
            className="px-4 py-2 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition-colors"
          >
            Back to Classify
          </button>
          {!hasExtractedData && (
            <button
              onClick={handleStartExtraction}
              disabled={extracting || extractableFiles.length === 0}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {extracting ? "Extracting..." : "Start Extraction"}
            </button>
          )}
          {hasExtractedData && (
            <button
              onClick={handlePersist}
              disabled={persisting}
              className="px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {persisting ? "Persisting..." : "Persist All"}
            </button>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-6 mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="text-red-400 hover:text-red-600 ml-4"
          >
            &#10005;
          </button>
        </div>
      )}

      {/* Extracting spinner */}
      {extracting && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="animate-spin w-8 h-8 border-4 border-blue-200 border-t-blue-600 rounded-full mb-4"></div>
          <p className="text-slate-600">Running AI extraction on {extractableFiles.length} files...</p>
          <p className="text-sm text-slate-400 mt-1">This may take a minute</p>
        </div>
      )}

      {/* Main content: file list + data panel */}
      {!extracting && (
        <div className="flex flex-1 overflow-hidden">
          {/* Left panel: file list */}
          <div className="w-64 border-r border-slate-200 overflow-y-auto">
            <div className="p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
                Files
              </h3>
              {files.map((file) => (
                <button
                  key={file.id}
                  onClick={() => {
                    if (file.state === "extracted") {
                      setSelectedFileId(file.id);
                      setActiveCategory("restaurants");
                    }
                  }}
                  disabled={file.state !== "extracted"}
                  className={`w-full text-left px-3 py-2 rounded-lg mb-1 text-sm flex items-center gap-2 transition-colors ${
                    selectedFileId === file.id
                      ? "bg-blue-50 border border-blue-200"
                      : file.state === "extracted"
                      ? "hover:bg-slate-50 cursor-pointer"
                      : "opacity-60 cursor-default"
                  }`}
                >
                  <FileStatusIcon state={file.state} />
                  <span className="truncate flex-1 text-slate-700">
                    {file.filename}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Right panel: extracted data */}
          <div className="flex-1 overflow-y-auto">
            {!selectedFile && (
              <div className="flex items-center justify-center h-full text-slate-400">
                {hasExtractedData
                  ? "Select a file to view extracted data"
                  : "Click \"Start Extraction\" to begin"}
              </div>
            )}

            {selectedFile && selectedFile.data && (
              <div className="p-4">
                {/* File header */}
                <div className="mb-4">
                  <h3 className="text-base font-semibold text-slate-800">
                    {selectedFile.filename}
                  </h3>
                  <p className="text-xs text-slate-500">
                    Folder: {selectedFile.assigned_folder || "unassigned"}
                  </p>
                </div>

                {/* Category tabs */}
                <div className="flex flex-wrap gap-1 mb-4 border-b border-slate-200 pb-2">
                  {CATEGORIES.map(({ key, label }) => {
                    const count = (selectedFile.data?.[key] || []).length;
                    return (
                      <button
                        key={key}
                        onClick={() => setActiveCategory(key)}
                        className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                          activeCategory === key
                            ? "bg-blue-600 text-white"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        {label}
                        {count > 0 && (
                          <span
                            className={`ml-1 text-xs ${
                              activeCategory === key
                                ? "text-blue-200"
                                : "text-slate-400"
                            }`}
                          >
                            ({count})
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {/* Table */}
                <div className="border border-slate-200 rounded-lg overflow-hidden">
                  {(selectedFile.data[activeCategory] || []).length === 0 ? (
                    <div className="p-8 text-center text-slate-400 text-sm">
                      No {activeCategory.replace(/_/g, " ")} extracted from this file
                    </div>
                  ) : (
                    <EditableTable
                      columns={COLUMNS[activeCategory]}
                      data={selectedFile.data[activeCategory] || []}
                      onDataChange={(newData) =>
                        handleDataChange(selectedFile.id, activeCategory, newData)
                      }
                      onDelete={(index, reason) =>
                        handleDeleteRow(selectedFile.id, activeCategory, index, reason)
                      }
                    />
                  )}
                </div>
              </div>
            )}

            {selectedFile && selectedFile.state === "failed" && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <span className="text-red-500 text-2xl block mb-2">&#10007;</span>
                  <p className="text-slate-600">Extraction failed for this file</p>
                  {selectedFile.error && (
                    <p className="text-sm text-red-500 mt-1">{selectedFile.error}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
