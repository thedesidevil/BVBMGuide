import { useState } from "react";
import { api } from "../api/client";
import type { SweepResult } from "../types";

const SWEEP_CATEGORIES = ["restaurants", "attractions", "hotels", "local_dishes", "transport_options"];
const SWEEP_FIELDS: Record<string, string[]> = {
  restaurants: ["vegetarian_friendly", "pure_vegetarian", "hours", "price_range", "cuisine_type", "must_try_dishes", "best_for"],
  attractions: ["hours", "entry_fee", "recommended_duration", "description"],
  hotels: ["name"],
  local_dishes: ["name", "description"],
  transport_options: ["mode", "description"],
};
const FILTERS = ["all", "missing", "unchecked", "checked"];

export function SweepMode() {
  const [category, setCategory] = useState("restaurants");
  const [field, setField] = useState("vegetarian_friendly");
  const [filter, setFilter] = useState("all");
  const [result, setResult] = useState<SweepResult | null>(null);
  const [edits, setEdits] = useState<Map<string, any>>(new Map());

  const runSweep = async () => {
    const data = await api.getSweep(category, field, filter);
    setResult(data as SweepResult);
    setEdits(new Map());
  };

  const handleFieldEdit = (city: string, index: number, value: any) => {
    const key = `${city}:${index}`;
    setEdits((prev) => new Map(prev).set(key, { city, index, category, field, value }));
  };

  const handleSaveAll = async () => {
    const editList = Array.from(edits.values());
    await api.saveSweep(editList);
    setEdits(new Map());
    runSweep();
  };

  const grouped = (result?.items || []).reduce<Record<string, SweepResult["items"]>>((acc, item) => {
    if (!acc[item.city]) acc[item.city] = [];
    acc[item.city].push(item);
    return acc;
  }, {});

  return (
    <div>
      <div className="flex items-center gap-4 mb-5">
        <h1 className="text-xl font-bold text-slate-900">Sweep Mode</h1>
        <span className="bg-blue-100 text-blue-700 text-xs font-semibold px-3 py-1 rounded-full">SWEEP MODE</span>
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-4 flex flex-wrap gap-4 items-end shadow-sm">
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Category</label>
          <select value={category} onChange={(e) => { setCategory(e.target.value); setField(SWEEP_FIELDS[e.target.value]?.[0] || ""); }} className="px-3 py-2 border border-slate-200 rounded-md text-sm">
            {SWEEP_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Field</label>
          <select value={field} onChange={(e) => setField(e.target.value)} className="px-3 py-2 border border-slate-200 rounded-md text-sm">
            {(SWEEP_FIELDS[category] || []).map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Filter</label>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="px-3 py-2 border border-slate-200 rounded-md text-sm">
            {FILTERS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <button onClick={runSweep} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700">Run Sweep</button>
        <span className="flex-1" />
        {edits.size > 0 && <span className="text-sm text-slate-500">{edits.size} changes</span>}
        {edits.size > 0 && <button onClick={handleSaveAll} className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700">Save All</button>}
      </div>

      {result && (
        <div className="bg-slate-100 rounded-md px-4 py-2 mb-4 text-sm text-slate-600 flex gap-4">
          <span><strong>{result.total}</strong> items</span>
          <span><strong>{Object.keys(grouped).length}</strong> cities</span>
        </div>
      )}

      {result && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          {Object.entries(grouped).map(([city, items]) => (
            <div key={city}>
              <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 font-semibold text-sm text-blue-600">
                ▾ {city} ({items.length})
              </div>
              {items.map((item) => (
                <div key={`${item.city}:${item.index}`} className="px-4 py-3 border-b border-slate-100 flex items-center gap-4 text-sm">
                  <span className="w-48 font-medium text-slate-700">{item.item.name}</span>
                  {(field === "vegetarian_friendly" || field === "pure_vegetarian") ? (
                    <input
                      type="checkbox"
                      checked={edits.has(`${item.city}:${item.index}`) ? edits.get(`${item.city}:${item.index}`).value : !!item.item[field]}
                      onChange={(e) => handleFieldEdit(item.city, item.index, e.target.checked)}
                      className="w-[18px] h-[18px] accent-blue-500"
                    />
                  ) : (
                    <input
                      type="text"
                      defaultValue={Array.isArray(item.item[field]) ? item.item[field].join(", ") : (item.item[field] ?? "")}
                      onBlur={(e) => handleFieldEdit(item.city, item.index, e.target.value)}
                      className="flex-1 px-2 py-1 border border-slate-200 rounded text-sm focus:outline-none focus:border-blue-400"
                    />
                  )}
                  <span className="text-xs text-slate-400 w-48 truncate">{item.item.must_try_dishes?.join(", ") || item.item.description || ""}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
