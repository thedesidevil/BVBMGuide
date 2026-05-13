import { useState } from "react";

interface DeleteModalProps {
  itemName: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export function DeleteModal({ itemName, onConfirm, onCancel }: DeleteModalProps) {
  const [reason, setReason] = useState("");

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-lg p-6 w-[420px]">
        <h3 className="text-lg font-semibold text-slate-900 mb-2">Delete "{itemName}"?</h3>
        <p className="text-sm text-slate-500 mb-4">Please provide a reason for this deletion. This will be logged for audit purposes.</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Why are you deleting this?"
          className="w-full h-24 px-3 py-2 border border-slate-200 rounded-lg text-sm resize-y focus:outline-none focus:border-blue-400"
        />
        <div className="flex justify-end gap-3 mt-4">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-slate-600 border border-slate-200 rounded-md hover:bg-slate-50">
            Cancel
          </button>
          <button
            onClick={() => reason.trim() && onConfirm(reason)}
            disabled={!reason.trim()}
            className="px-4 py-2 text-sm text-white bg-red-600 rounded-md hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
