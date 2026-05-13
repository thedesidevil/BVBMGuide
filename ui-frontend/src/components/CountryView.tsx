import { useEffect, useState } from "react";
import { api } from "../api/client";
import { EditableTable } from "./EditableTable";
import { useUndoStack } from "../hooks/useUndoStack";

const COUNTRY_CATEGORIES = [
  { key: "connectivity_tips", label: "Connectivity" },
  { key: "transport_options", label: "Transport" },
  { key: "phrases", label: "Phrases" },
  { key: "safety_tips", label: "Safety Tips" },
  { key: "health_tips", label: "Health" },
  { key: "emergency_contacts", label: "Emergency" },
];

const TIP_COLUMNS = [
  { key: "tip", label: "Tip", type: "text" as const },
];

const PHRASE_COLUMNS = [
  { key: "english", label: "English", type: "text" as const },
  { key: "local", label: "Local", type: "text" as const },
  { key: "category", label: "Category", type: "text" as const },
];

const EMERGENCY_COLUMNS = [
  { key: "service", label: "Service", type: "text" as const },
  { key: "number", label: "Number", type: "text" as const },
  { key: "notes", label: "Notes", type: "text" as const },
];

function getCountryColumns(category: string) {
  if (category === "phrases") return PHRASE_COLUMNS;
  if (category === "emergency_contacts") return EMERGENCY_COLUMNS;
  return TIP_COLUMNS;
}

interface CountryViewProps {
  countryName: string;
  onRefreshTree: () => void;
}

export function CountryView({ countryName, onRefreshTree }: CountryViewProps) {
  const [data, setData] = useState<Record<string, any[]> | null>(null);
  const [activeTab, setActiveTab] = useState("connectivity_tips");
  const [unsavedChanges, setUnsavedChanges] = useState(0);
  const undo = useUndoStack();

  useEffect(() => {
    api.getCountry(countryName).then((d) => { setData(d as Record<string, any[]>); setUnsavedChanges(0); undo.clear(); });
  }, [countryName]);

  if (!data) return <div className="text-slate-400 py-10 text-center">Loading...</div>;

  const handleDataChange = (category: string, newItems: any[]) => {
    const prev = [...(data[category] || [])];
    undo.push({ description: `Edit ${category}`, undo: () => setData((d) => d ? { ...d, [category]: prev } : d) });
    setData({ ...data, [category]: newItems });
    setUnsavedChanges((n) => n + 1);
  };

  const handleSave = async () => {
    await api.saveCountry(countryName, data);
    setUnsavedChanges(0);
    onRefreshTree();
  };

  const handleMarkReviewed = async () => {
    await api.reviewCountry(countryName, "marina");
    onRefreshTree();
  };

  return (
    <div>
      <div className="flex items-center gap-4 mb-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{countryName} <span className="text-sm font-medium bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full ml-2">Country</span></h1>
          <p className="text-sm text-slate-500">Country-level data shared across all cities</p>
        </div>
        <button onClick={handleMarkReviewed} className="ml-auto px-4 py-2 text-sm font-medium text-green-800 bg-green-50 border border-green-300 rounded-md hover:bg-green-100">
          ✓ Mark as Reviewed
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 mb-4 text-sm text-blue-700">
        ℹ️ Country-level data applies to all cities in {countryName}. City-specific data is edited within each city.
      </div>

      <div className="flex gap-0.5 border-b-2 border-slate-200 mb-4">
        {COUNTRY_CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setActiveTab(cat.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-[2px] ${
              activeTab === cat.key ? "text-blue-600 border-blue-600" : "text-slate-500 border-transparent hover:text-slate-700"
            }`}
          >
            {cat.label} <span className={`ml-1 text-xs px-1.5 py-0.5 rounded-full ${activeTab === cat.key ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"}`}>{(data[cat.key] || []).length}</span>
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="flex items-center gap-3 mb-4">
          <button className="px-4 py-2 text-sm font-medium border border-slate-200 rounded-md hover:bg-slate-50">+ Add</button>
          <button onClick={undo.undo} disabled={!undo.canUndo} className="px-4 py-2 text-sm font-medium border border-blue-300 text-blue-600 rounded-md hover:bg-blue-50 disabled:opacity-40">↩ Undo</button>
          <span className="flex-1" />
          {unsavedChanges > 0 && <span className="text-sm text-slate-500">{unsavedChanges} unsaved changes</span>}
          <button onClick={handleSave} className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700">Save</button>
        </div>
        <EditableTable
          columns={getCountryColumns(activeTab)}
          data={data[activeTab] || []}
          onDataChange={(newData) => handleDataChange(activeTab, newData)}
          onDelete={() => {}}
        />
      </div>
    </div>
  );
}
