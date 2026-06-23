import type { ReactNode } from "react";

type Mode = "city" | "sweep" | "ingest" | "history" | "audit" | "verify" | "hotel_options";

interface LayoutProps {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  isAdmin: boolean;
  reviewedCount: number;
  totalCount: number;
  sidebar: ReactNode;
  children: ReactNode;
  userEmail: string | null;
}

function Tab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-md text-sm font-medium ${active ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
    >
      {label}
    </button>
  );
}

const NO_SIDEBAR_MODES: Mode[] = ["ingest", "history", "audit", "verify", "hotel_options"];

export function Layout({ mode, onModeChange, isAdmin, reviewedCount, totalCount, sidebar, children, userEmail }: LayoutProps) {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-6 shadow-sm">
        <span className="font-bold text-base text-slate-900">{isAdmin ? "Library QC" : "AIG Verify"}</span>
        <div className="flex gap-1">
          {isAdmin && (
            <>
              <Tab label="City View"   active={mode === "city"}    onClick={() => onModeChange("city")} />
              <Tab label="Sweep Mode"  active={mode === "sweep"}   onClick={() => onModeChange("sweep")} />
              <Tab label="Ingest"      active={mode === "ingest"}  onClick={() => onModeChange("ingest")} />
              <Tab label="History"     active={mode === "history"} onClick={() => onModeChange("history")} />
              <Tab label="Audit"       active={mode === "audit"}   onClick={() => onModeChange("audit")} />
              <div className="w-px bg-slate-200 mx-1 self-stretch" />
            </>
          )}
          <Tab label="Verify AIG" active={mode === "verify"} onClick={() => onModeChange("verify")} />
          <Tab label="Hotel Options" active={mode === "hotel_options"} onClick={() => onModeChange("hotel_options")} />
        </div>
        <div className="ml-auto flex items-center gap-4 text-sm text-slate-500">
          {isAdmin && <span>{reviewedCount} / {totalCount} cities reviewed</span>}
          {userEmail && (
            <>
              <span className="text-slate-400">{userEmail}</span>
              <a href="/logout" className="text-blue-500 hover:text-blue-700 font-medium">Sign out</a>
            </>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {!NO_SIDEBAR_MODES.includes(mode) && isAdmin && (
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
