import { useEffect, useState } from "react";
import { api } from "../api/client";

interface HistoryEntry {
  filename: string;
  destination: string;
  covered_cities: string[];
  ingested_at: string;
}

type SortKey = "filename" | "destination" | "covered_cities" | "ingested_at";

function formatDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function IngestHistory() {
  const [files, setFiles] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("ingested_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    api.ingestHistory().then((data) => {
      setFiles(data.files);
      setLoading(false);
    });
  }, []);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "ingested_at" ? "desc" : "asc");
    }
  };

  const sorted = [...files].sort((a, b) => {
    let aVal: string;
    let bVal: string;
    if (sortKey === "covered_cities") {
      aVal = a.covered_cities.join(", ");
      bVal = b.covered_cities.join(", ");
    } else {
      aVal = a[sortKey] ?? "";
      bVal = b[sortKey] ?? "";
    }
    const cmp = aVal.localeCompare(bVal, undefined, { numeric: true, sensitivity: "base" });
    return sortDir === "asc" ? cmp : -cmp;
  });

  const SortHeader = ({ label, col }: { label: string; col: SortKey }) => (
    <th
      onClick={() => handleSort(col)}
      className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase cursor-pointer select-none hover:text-slate-700"
    >
      {label}
      {sortKey === col && <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>}
    </th>
  );

  if (loading) {
    return <div className="text-slate-400 text-center py-20">Loading history...</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Ingest History</h2>
          <p className="text-sm text-slate-500 mt-1">{files.length} documents in the library</p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b-2 border-slate-200">
              <SortHeader label="Filename" col="filename" />
              <SortHeader label="Destination" col="destination" />
              <SortHeader label="Cities Covered" col="covered_cities" />
              <SortHeader label="Ingested On" col="ingested_at" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((entry) => (
              <tr key={entry.filename} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 font-medium text-slate-700">{entry.filename}</td>
                <td className="px-4 py-3">
                  <span className="text-xs font-medium bg-blue-100 text-blue-700 px-2 py-1 rounded-full">
                    {entry.destination}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {entry.covered_cities.map((city) => (
                      <span key={city} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                        {city}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-500">{formatDate(entry.ingested_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
