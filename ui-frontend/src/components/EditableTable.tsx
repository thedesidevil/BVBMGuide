import { useState } from "react";
import { DeleteModal } from "./DeleteModal";

interface Column {
  key: string;
  label: string;
  type: "text" | "checkbox" | "tags";
  tagOptions?: string[];
}

interface EditableTableProps {
  columns: Column[];
  data: Record<string, any>[];
  onDataChange: (newData: Record<string, any>[]) => void;
  onDelete: (index: number, reason: string) => void;
}

export function EditableTable({ columns, data, onDataChange, onDelete }: EditableTableProps) {
  const [editingRow, setEditingRow] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ index: number; name: string } | null>(null);

  const handleFieldChange = (rowIndex: number, key: string, value: any) => {
    const updated = [...data];
    updated[rowIndex] = { ...updated[rowIndex], [key]: value };
    onDataChange(updated);
  };

  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 border-b-2 border-slate-200">
            {columns.map((col) => (
              <th key={col.key} className="text-left px-3 py-3 text-xs font-semibold text-slate-500 uppercase">
                {col.label}
              </th>
            ))}
            <th className="w-10"></th>
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIdx) => {
            const isEditing = editingRow === rowIdx;
            const isMissing = columns.some(
              (c) => c.type === "text" && !row[c.key] && ["name", "cuisine_type", "hours"].includes(c.key)
            );
            return (
              <tr
                key={rowIdx}
                onClick={() => setEditingRow(rowIdx)}
                className={`border-b border-slate-100 cursor-pointer transition-colors ${
                  isEditing ? "bg-blue-50 border-l-4 border-l-blue-500" :
                  isMissing ? "bg-amber-50 border-l-4 border-l-amber-400" :
                  "hover:bg-slate-50"
                }`}
              >
                {columns.map((col) => (
                  <td key={col.key} className="px-3 py-3">
                    {isEditing && col.type === "text" && (
                      <textarea
                        value={Array.isArray(row[col.key]) ? row[col.key].join(", ") : (row[col.key] ?? "")}
                        onChange={(e) => {
                          const val = ["cuisine_type", "must_try_dishes", "where_to_buy", "where_to_try"].includes(col.key)
                            ? e.target.value.split(",").map((s: string) => s.trim())
                            : e.target.value;
                          handleFieldChange(rowIdx, col.key, val);
                        }}
                        className="w-full min-h-[32px] px-2 py-1 border border-slate-300 rounded-md resize-both text-sm focus:outline-none focus:border-blue-400"
                      />
                    )}
                    {isEditing && col.type === "checkbox" && (
                      <input
                        type="checkbox"
                        checked={!!row[col.key]}
                        onChange={(e) => handleFieldChange(rowIdx, col.key, e.target.checked)}
                        className="w-[18px] h-[18px] accent-blue-500"
                      />
                    )}
                    {isEditing && col.type === "tags" && (
                      <div className="flex flex-wrap gap-1 items-center">
                        {(row[col.key] || []).map((tag: string, i: number) => (
                          <span key={i} className="bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation();
                              const updated = (row[col.key] || []).filter((_: any, idx: number) => idx !== i);
                              handleFieldChange(rowIdx, col.key, updated);
                            }}
                          >{tag} ×</span>
                        ))}
                        {col.tagOptions && (
                          <select
                            className="text-xs border border-slate-200 rounded px-1 py-0.5"
                            value=""
                            onChange={(e) => {
                              if (e.target.value) {
                                const updated = [...(row[col.key] || []), e.target.value];
                                handleFieldChange(rowIdx, col.key, updated);
                              }
                            }}
                          >
                            <option value="">+ add</option>
                            {col.tagOptions.filter((o) => !(row[col.key] || []).includes(o)).map((o) => (
                              <option key={o} value={o}>{o}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    )}
                    {!isEditing && col.type === "text" && (
                      <span className={row[col.key] ? "text-slate-700" : "text-amber-500 italic"}>
                        {Array.isArray(row[col.key]) ? row[col.key].join(", ") : (row[col.key] || "⚠ missing")}
                      </span>
                    )}
                    {!isEditing && col.type === "checkbox" && (
                      <input type="checkbox" checked={!!row[col.key]} readOnly className="w-[18px] h-[18px] accent-blue-500 pointer-events-none" />
                    )}
                    {!isEditing && col.type === "tags" && (
                      <div className="flex flex-wrap gap-1">
                        {(row[col.key] || []).map((tag: string, i: number) => (
                          <span key={i} className="bg-slate-200 text-slate-600 text-xs px-2 py-1 rounded-full">{tag}</span>
                        ))}
                      </div>
                    )}
                  </td>
                ))}
                <td className="px-2">
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget({ index: rowIdx, name: row.name || row.item || "item" }); }}
                    className="text-red-400 hover:text-red-600 hover:bg-red-50 rounded p-1"
                    title="Delete"
                  >🗑</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {deleteTarget && (
        <DeleteModal
          itemName={deleteTarget.name}
          onConfirm={(reason) => { onDelete(deleteTarget.index, reason); setDeleteTarget(null); }}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </>
  );
}
