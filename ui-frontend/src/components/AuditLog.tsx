import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditEntry } from "../types";

const ACTION_STYLES: Record<string, string> = {
  edit: "bg-blue-100 text-blue-700",
  delete: "bg-red-100 text-red-700",
  add: "bg-green-100 text-green-700",
};

export function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getAudit(200).then((data) => {
      setEntries(data as AuditEntry[]);
      setLoading(false);
    });
  }, []);

  const filtered = filter === "all" ? entries : entries.filter((e) => e.action === filter);

  const formatDetails = (entry: AuditEntry): string => {
    if (entry.action === "edit" && entry.changes) {
      return entry.changes
        .map((c) => {
          const oldStr = Array.isArray(c.old) ? c.old.join(", ") : String(c.old ?? "");
          const newStr = Array.isArray(c.new) ? c.new.join(", ") : String(c.new ?? "");
          return `${c.field}: "${oldStr}" → "${newStr}"`;
        })
        .join("; ");
    }
    if (entry.action === "delete") return entry.reason || "";
    if (entry.action === "add") return `Added: ${entry.item_name}`;
    return "";
  };

  const formatTime = (iso: string): string => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  };

  if (loading) return <div className="text-slate-400 py-10 text-center">Loading audit log...</div>;

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center gap-4 mb-5">
        <h1 className="text-xl font-bold text-slate-900">Audit Log</h1>
        <div className="flex gap-1 ml-4">
          {["all", "edit", "delete", "add"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md ${filter === f ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
            >
              {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <span className="ml-auto text-sm text-slate-400">{filtered.length} entries</span>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b-2 border-slate-200">
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Time</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">User</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Action</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">City</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Category</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Item</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Details</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((entry, i) => (
              <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{formatTime(entry.changed_at)}</td>
                <td className="px-4 py-3 text-slate-700">{entry.changed_by}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 text-xs font-medium rounded-full ${ACTION_STYLES[entry.action] || ""}`}>
                    {entry.action}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-700">{entry.city}</td>
                <td className="px-4 py-3 text-slate-500">{entry.category}</td>
                <td className="px-4 py-3 text-slate-700 font-medium">{entry.item_name}</td>
                <td className="px-4 py-3 text-slate-500 max-w-xs truncate" title={formatDetails(entry)}>
                  {formatDetails(entry)}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-400">No audit entries</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
