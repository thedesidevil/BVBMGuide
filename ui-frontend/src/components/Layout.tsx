import { useEffect, useState, type ReactNode } from "react";

interface LayoutProps {
  mode: "city" | "sweep" | "ingest" | "history";
  onModeChange: (mode: "city" | "sweep" | "ingest" | "history") => void;
  reviewedCount: number;
  totalCount: number;
  sidebar: ReactNode;
  children: ReactNode;
}

export function Layout({ mode, onModeChange, reviewedCount, totalCount, sidebar, children }: LayoutProps) {
  const [userEmail, setUserEmail] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/me", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (data?.email) setUserEmail(data.email); })
      .catch(() => {});
  }, []);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-6 shadow-sm">
        <span className="font-bold text-base text-slate-900">Library QC</span>
        <div className="flex gap-1">
          <button
            onClick={() => onModeChange("city")}
            className={`px-4 py-2 rounded-md text-sm font-medium ${mode === "city" ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
          >
            City View
          </button>
          <button
            onClick={() => onModeChange("sweep")}
            className={`px-4 py-2 rounded-md text-sm font-medium ${mode === "sweep" ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
          >
            Sweep Mode
          </button>
          <button
            onClick={() => onModeChange("ingest")}
            className={`px-4 py-2 rounded-md text-sm font-medium ${mode === "ingest" ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
          >
            Ingest
          </button>
          <button
            onClick={() => onModeChange("history")}
            className={`px-4 py-2 rounded-md text-sm font-medium ${mode === "history" ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
          >
            History
          </button>
        </div>
        <div className="ml-auto flex items-center gap-4 text-sm text-slate-500">
          <span>{reviewedCount} / {totalCount} cities reviewed</span>
          {userEmail && (
            <>
              <span className="text-slate-400">{userEmail}</span>
              <a href="/logout" className="text-blue-500 hover:text-blue-700 font-medium">Sign out</a>
            </>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {mode !== "ingest" && mode !== "history" && (
          <aside className="w-[260px] bg-white border-r border-slate-200 overflow-y-auto flex-shrink-0">
            {sidebar}
          </aside>
        )}
        <main className="flex-1 overflow-y-auto p-6 bg-slate-50">
          {children}
        </main>
      </div>
    </div>
  );
}
