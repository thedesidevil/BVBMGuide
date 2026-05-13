import { useEffect, useState } from "react";
import { api } from "../api/client";
import { EditableTable } from "./EditableTable";
import { useUndoStack } from "../hooks/useUndoStack";
import type { CityData } from "../types";

const CATEGORIES = [
  { key: "restaurants", label: "Restaurants", singular: "Restaurant" },
  { key: "attractions", label: "Attractions", singular: "Attraction" },
  { key: "hotels", label: "Hotels", singular: "Hotel" },
  { key: "local_dishes", label: "Local Dishes", singular: "Local Dish" },
  { key: "souvenirs", label: "Souvenirs", singular: "Souvenir" },
];

const RESTAURANT_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "cuisine_type", label: "Cuisine", type: "text" as const },
  { key: "hours", label: "Hours", type: "text" as const },
  { key: "price_range", label: "Price Range", type: "text" as const },
  { key: "vegetarian_friendly", label: "Veg Friendly", type: "checkbox" as const },
  { key: "pure_vegetarian", label: "Pure Veg", type: "checkbox" as const },
  { key: "must_try_dishes", label: "Must-Try Dishes", type: "text" as const },
  { key: "best_for", label: "Best For", type: "tags" as const, tagOptions: ["casual", "romantic", "elegant", "family", "wine", "business"] },
];

const ATTRACTION_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "description", label: "Description", type: "text" as const },
  { key: "hours", label: "Hours", type: "text" as const },
  { key: "entry_fee", label: "Entry Fee", type: "text" as const },
  { key: "recommended_duration", label: "Duration", type: "text" as const },
];

const HOTEL_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "location", label: "Location", type: "text" as const },
];

const LOCAL_DISH_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "description", label: "Description", type: "text" as const },
  { key: "vegetarian", label: "Vegetarian", type: "checkbox" as const },
  { key: "where_to_try", label: "Where to Try", type: "text" as const },
];

const SOUVENIR_COLUMNS = [
  { key: "item", label: "Item", type: "text" as const },
  { key: "category", label: "Category", type: "text" as const },
  { key: "where_to_buy", label: "Where to Buy", type: "text" as const },
];

function getColumns(category: string) {
  if (category === "restaurants") return RESTAURANT_COLUMNS;
  if (category === "attractions") return ATTRACTION_COLUMNS;
  if (category === "hotels") return HOTEL_COLUMNS;
  if (category === "local_dishes") return LOCAL_DISH_COLUMNS;
  if (category === "souvenirs") return SOUVENIR_COLUMNS;
  return [{ key: "name", label: "Name", type: "text" as const }];
}

interface CityViewProps {
  cityName: string;
  onRefreshTree: () => void;
}

export function CityView({ cityName, onRefreshTree }: CityViewProps) {
  const [data, setData] = useState<CityData | null>(null);
  const [activeTab, setActiveTab] = useState("restaurants");
  const [unsavedChanges, setUnsavedChanges] = useState(0);
  const undo = useUndoStack();

  useEffect(() => {
    api.getCity(cityName).then((d) => { setData(d as CityData); setUnsavedChanges(0); undo.clear(); });
  }, [cityName]);

  const [pendingDeletions, setPendingDeletions] = useState<{ category: string; item: any; reason: string }[]>([]);

  if (!data) return <div className="text-slate-400 py-10 text-center">Loading...</div>;

  const handleDataChange = (category: string, newItems: any[]) => {
    const prev = [...(data as any)[category]];
    undo.push({ description: `Edit ${category}`, undo: () => setData((d) => d ? { ...d, [category]: prev } : d) });
    setData({ ...data, [category]: newItems });
    setUnsavedChanges((n) => n + 1);
  };

  const handleDelete = (category: string, index: number, reason: string) => {
    const item = (data as any)[category][index];
    const prev = [...(data as any)[category]];
    const prevDeletions = [...pendingDeletions];
    const newItems = prev.filter((_, i) => i !== index);
    setPendingDeletions((d) => [...d, { category, item, reason }]);
    undo.push({
      description: `Delete ${item.name || item.item}`,
      undo: () => {
        setData((d) => d ? { ...d, [category]: prev } : d);
        setPendingDeletions(prevDeletions);
      },
    });
    setData({ ...data, [category]: newItems });
    setUnsavedChanges((n) => n + 1);
  };

  const handleSave = async () => {
    for (const del of pendingDeletions) {
      await api.logDeletion(cityName, del.category, del.item.name || del.item.item || "unknown", del.reason, del.item, "marina");
    }
    await api.saveCity(cityName, data);
    setPendingDeletions([]);
    setUnsavedChanges(0);
    onRefreshTree();
  };

  const handleMarkReviewed = async () => {
    await api.reviewCity(cityName, "marina");
    onRefreshTree();
  };

  return (
    <div>
      <div className="flex items-center gap-4 mb-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{cityName}</h1>
          <p className="text-sm text-slate-500">
            {data.restaurants?.length || 0} restaurants · {data.attractions?.length || 0} attractions
          </p>
        </div>
        <button onClick={handleMarkReviewed} className="ml-auto px-4 py-2 text-sm font-medium text-green-800 bg-green-50 border border-green-300 rounded-md hover:bg-green-100">
          ✓ Mark as Reviewed
        </button>
      </div>

      <div className="flex gap-0.5 border-b-2 border-slate-200 mb-4">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setActiveTab(cat.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-[2px] ${
              activeTab === cat.key ? "text-blue-600 border-blue-600" : "text-slate-500 border-transparent hover:text-slate-700"
            }`}
          >
            {cat.label} <span className={`ml-1 text-xs px-1.5 py-0.5 rounded-full ${activeTab === cat.key ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"}`}>{(data as any)[cat.key]?.length || 0}</span>
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="flex items-center gap-3 mb-4">
          <button className="px-4 py-2 text-sm font-medium border border-slate-200 rounded-md hover:bg-slate-50">
            + Add {CATEGORIES.find((c) => c.key === activeTab)?.singular}
          </button>
          <button onClick={undo.undo} disabled={!undo.canUndo} className="px-4 py-2 text-sm font-medium border border-blue-300 text-blue-600 rounded-md hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed">
            ↩ Undo
          </button>
          <span className="flex-1" />
          {unsavedChanges > 0 && <span className="text-sm text-slate-500">{unsavedChanges} unsaved changes</span>}
          <button onClick={handleSave} className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700">
            Save
          </button>
        </div>

        <EditableTable
          columns={getColumns(activeTab)}
          data={(data as any)[activeTab] || []}
          onDataChange={(newData) => handleDataChange(activeTab, newData)}
          onDelete={(index, reason) => handleDelete(activeTab, index, reason)}
        />
      </div>
    </div>
  );
}
