# UI Nav Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current flat tab bar with a 3-section top navigation: "Hotel Pricing" | "AIG Verification" | "Library & QC". Library & QC shows sub-tabs (City View, Sweep Mode, Ingest, History, Audit) when active. Non-admins only see Hotel Pricing and AIG Verification.

**Context:**
- `ui-frontend/src/components/Layout.tsx` — current Layout with flat tab navigation
- `ui-frontend/src/App.tsx` — state management; Mode type is `"city" | "sweep" | "ingest" | "history" | "audit" | "verify" | "hotel_options"`
- Internal tool for 2-5 employees — functional and clear is the goal, not visually polished
- No existing frontend test framework — no frontend tests required (pure nav reorganization)

## Global Constraints

- Do NOT change the `Mode` type or any mode strings — they are used by backend routing and must stay as-is
- Library & QC section is admin-only (hide the nav item entirely for non-admins)
- Clicking "Library & QC" → setMode to whichever library sub-mode was last used (default: `"city"`)
- Clicking "Hotel Pricing" → `setMode("hotel_options")`
- Clicking "AIG Verification" → `setMode("verify")`
- Library sub-modes: `"city" | "sweep" | "ingest" | "history" | "audit"` — all admin-only, no change
- `NO_SIDEBAR_MODES` list stays the same (`"ingest" | "history" | "audit" | "verify" | "hotel_options"`)
- Title text in header: replace the conditional `"Library QC" / "AIG Verify"` with just `"BVBM Tools"`
- Active section highlighting: top nav item uses `bg-blue-600 text-white` for active section; sub-tabs use existing `bg-blue-50 text-blue-600` style
- Non-admin default mode stays `"verify"` (no change to App.tsx `/api/me` handler)

---

### Task 1: 3-section nav in Layout.tsx + last-library-mode in App.tsx

**Files to modify:**
- `ui-frontend/src/components/Layout.tsx`
- `ui-frontend/src/App.tsx`

**Step 1: App.tsx — add `lastLibraryMode` state**

Add a new state variable and update the handler passed to Layout:

```tsx
// In App.tsx, add alongside other useState:
const [lastLibraryMode, setLastLibraryMode] = useState<"city" | "sweep" | "ingest" | "history" | "audit">("city");

// Replace the Layout's onModeChange with a wrapper:
const handleModeChange = (newMode: Mode) => {
  const libraryModes = ["city", "sweep", "ingest", "history", "audit"] as const;
  if ((libraryModes as readonly string[]).includes(newMode)) {
    setLastLibraryMode(newMode as typeof libraryModes[number]);
  }
  setMode(newMode);
};
```

Pass `lastLibraryMode` and `handleModeChange` to `Layout`:
```tsx
<Layout
  mode={mode}
  onModeChange={handleModeChange}
  lastLibraryMode={lastLibraryMode}
  isAdmin={isAdmin}
  ...
>
```

**Step 2: Layout.tsx — update LayoutProps**

```tsx
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
```

**Step 3: Layout.tsx — replace flat tabs with 3-section nav**

Replace the entire `<header>` content with:

```tsx
// Helper: which top-level section is the current mode in?
function activeSection(mode: Mode): "hotel" | "verify" | "library" {
  if (mode === "hotel_options") return "hotel";
  if (mode === "verify") return "verify";
  return "library";
}

// Top-level section nav item
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

// Existing Tab component stays for sub-tabs (same styling as before)
```

Header structure:
```tsx
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
```

- [ ] **Step 1: Add `lastLibraryMode` state and `handleModeChange` wrapper in `App.tsx`; pass `lastLibraryMode` prop to `Layout`**
- [ ] **Step 2: Update `LayoutProps` interface in `Layout.tsx` to include `lastLibraryMode`**
- [ ] **Step 3: Add `activeSection()` helper and `SectionTab` component in `Layout.tsx`**
- [ ] **Step 4: Replace header content with 3-section nav + conditional sub-tabs**
- [ ] **Step 5: Build the frontend** — `cd ui-frontend && npm run build` — no TypeScript errors
- [ ] **Step 6: Commit** with message `feat(ui): 3-section top nav — Hotel Pricing, AIG Verification, Library & QC`
