import type { ReactNode } from "react";

type Mode = "city" | "sweep" | "ingest" | "history" | "audit" | "verify" | "hotel_options";

interface LayoutProps {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  lastLibraryMode: "city" | "sweep" | "ingest" | "history" | "audit";
  isAdmin: boolean;
  reviewedCount: number;
  totalCount: number;
  sidebar: ReactNode;
  children: ReactNode;
  userEmail: string | null;
  serverVersion?: string;
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

function SectionTab({
  label, active, onClick,
}: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-md text-sm font-semibold transition-colors ${
        active
          ? "bg-blue-600 text-white"
          : "text-slate-600 hover:bg-slate-100"
      }`}
    >
      {label}
    </button>
  );
}

function activeSection(mode: Mode): "hotel" | "verify" | "library" {
  if (mode === "hotel_options") return "hotel";
  if (mode === "verify") return "verify";
  return "library";
}

const NO_SIDEBAR_MODES: Mode[] = ["ingest", "history", "audit", "verify", "hotel_options"];

export function Layout({ mode, onModeChange, lastLibraryMode, isAdmin, reviewedCount, totalCount, sidebar, children, userEmail, serverVersion }: LayoutProps) {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="bg-white border-b border-slate-200 shadow-sm">
        {/* Top row: logo + section nav + status */}
        <div className="px-6 py-3 flex items-center gap-6">
          <span className="font-bold text-base text-slate-900">BVBM Tools</span>
          <div className="flex gap-1">
            <SectionTab
              label="Hotel Pricing"
              active={activeSection(mode) === "hotel"}
              onClick={() => onModeChange("hotel_options")}
            />
            <SectionTab
              label="AIG Verification"
              active={activeSection(mode) === "verify"}
              onClick={() => onModeChange("verify")}
            />
            {isAdmin && (
              <SectionTab
                label="Library & QC"
                active={activeSection(mode) === "library"}
                onClick={() => onModeChange(lastLibraryMode)}
              />
            )}
          </div>
          <div className="ml-auto flex items-center gap-4 text-sm text-slate-500">
            {isAdmin && <span>{reviewedCount} / {totalCount} cities reviewed</span>}
            {serverVersion && (
              <span className="font-mono text-xs text-slate-300" title="Server git commit">
                {serverVersion}
              </span>
            )}
            {userEmail && (
              <>
                <span className="text-slate-400">{userEmail}</span>
                <a href="/logout" className="text-blue-500 hover:text-blue-700 font-medium">Sign out</a>
              </>
            )}
          </div>
        </div>

        {/* Sub-tabs row: only visible in Library & QC section */}
        {isAdmin && activeSection(mode) === "library" && (
          <div className="px-6 pb-2 flex gap-1 border-t border-slate-100">
            <Tab label="City View"  active={mode === "city"}    onClick={() => onModeChange("city")} />
            <Tab label="Sweep Mode" active={mode === "sweep"}   onClick={() => onModeChange("sweep")} />
            <Tab label="Ingest"     active={mode === "ingest"}  onClick={() => onModeChange("ingest")} />
            <Tab label="History"    active={mode === "history"} onClick={() => onModeChange("history")} />
            <Tab label="Audit"      active={mode === "audit"}   onClick={() => onModeChange("audit")} />
          </div>
        )}
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
