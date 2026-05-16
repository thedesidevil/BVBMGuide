# QC UI Bug Fixes & Audit Feature — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 bugs (change counter, add button, logout) and add 2 features (loading screen, full audit tab) to the Library QC UI.

**Architecture:** Frontend is React 19 + TypeScript + Vite + Tailwind. Backend is FastAPI + Mangum on Lambda with S3 storage. Audit data lives in `_audit.json` alongside city shards. No test suite exists — verify manually via dev server.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS, FastAPI, Python 3.14

**Spec:** `docs/superpowers/specs/2026-05-16-qc-ui-fixes-and-audit-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ui-frontend/vite.config.ts` | Modify | Add auth routes to proxy |
| `ui-frontend/src/components/Layout.tsx` | Modify | Add Audit tab, fix logout link |
| `ui-frontend/src/App.tsx` | Modify | Loading state, auth-failed state, audit mode |
| `ui-frontend/src/components/CityView.tsx` | Modify | Fix change counter, add button, pass user |
| `ui-frontend/src/components/LoadingScreen.tsx` | Create | Full-screen loading progress bar |
| `ui-frontend/src/components/AuditLog.tsx` | Create | Audit tab table UI |
| `ui-frontend/src/api/client.ts` | Modify | Add changed_by to saveCity, getMe helper |
| `ui-frontend/src/types.ts` | Modify | Expand AuditEntry type |
| `src/library/ui/api/city.py` | Modify | Diff logic on PUT, extract user from body |
| `src/library/ui/services/audit_service.py` | Modify | Add log_edit, log_add, 200-cap purge |

---

### Task 1: Fix Logout (Vite Proxy + Frontend)

**Files:**
- Modify: `ui-frontend/vite.config.ts`
- Modify: `ui-frontend/src/components/Layout.tsx`
- Modify: `ui-frontend/src/App.tsx`

- [ ] **Step 1: Add auth routes to Vite proxy**

In `ui-frontend/vite.config.ts`, add `/logout`, `/login`, and `/auth` to the proxy so they reach the backend in dev mode:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/login': 'http://127.0.0.1:8765',
      '/logout': 'http://127.0.0.1:8765',
      '/auth': 'http://127.0.0.1:8765',
    },
  },
})
```

- [ ] **Step 2: Handle auth-failed state in App.tsx**

Add an `authReady` state to App.tsx. Before rendering anything, check `/api/me`. If 401, show a session-expired message. This prevents the blank-screen problem after logout.

In `ui-frontend/src/App.tsx`, add state and check at the top of the component:

```tsx
const [authReady, setAuthReady] = useState(false);
const [userEmail, setUserEmail] = useState<string | null>(null);

useEffect(() => {
  fetch("/api/me", { credentials: "same-origin" })
    .then((r) => {
      if (r.ok) return r.json();
      if (r.status === 401) return null;
      return null;
    })
    .then((data) => {
      if (data?.email) setUserEmail(data.email);
      setAuthReady(true);
    })
    .catch(() => setAuthReady(true));
}, []);
```

No special redirect needed — if auth is disabled (local dev), `/api/me` returns 401 and we just proceed. The `userEmail` is passed to child components for audit tracking.

- [ ] **Step 3: Pass userEmail down through Layout**

Remove the internal `/api/me` fetch from `Layout.tsx` and accept `userEmail` as a prop from App.tsx instead (single source of truth):

In `Layout.tsx`, change the interface:
```tsx
interface LayoutProps {
  mode: "city" | "sweep" | "ingest" | "history" | "audit";
  onModeChange: (mode: "city" | "sweep" | "ingest" | "history" | "audit") => void;
  reviewedCount: number;
  totalCount: number;
  sidebar: ReactNode;
  children: ReactNode;
  userEmail: string | null;
}
```

Remove the internal `useEffect` + `useState` for `userEmail`. Use the prop directly.

- [ ] **Step 4: Verify**

Run: `cd ui-frontend && npm run dev`

1. Open browser, click Sign Out — should redirect to `/login` (backend).
2. In local dev (no auth), app loads normally without errors in console.

- [ ] **Step 5: Commit**

```bash
git add ui-frontend/vite.config.ts ui-frontend/src/components/Layout.tsx ui-frontend/src/App.tsx
git commit -m "fix: logout routing and auth state handling"
```

---

### Task 2: Fix Change Counter (Track Fields, Not Keystrokes)

**Files:**
- Modify: `ui-frontend/src/components/CityView.tsx`

- [ ] **Step 1: Replace unsavedChanges counter with dirty-field tracking**

Replace the integer `unsavedChanges` state with a `Set<string>` and store the original loaded data for diffing. In `CityView.tsx`:

```tsx
const [originalData, setOriginalData] = useState<CityData | null>(null);
const [dirtyFields, setDirtyFields] = useState<Set<string>>(new Set());
```

Update the `useEffect` that loads city data:
```tsx
useEffect(() => {
  api.getCity(cityName).then((d) => {
    const cityData = d as CityData;
    setData(cityData);
    setOriginalData(JSON.parse(JSON.stringify(cityData)));
    setDirtyFields(new Set());
    undo.clear();
  });
}, [cityName]);
```

- [ ] **Step 2: Rewrite handleDataChange to diff against original**

Replace the current `handleDataChange`:

```tsx
const handleDataChange = (category: string, newItems: any[]) => {
  const prev = [...(data as any)[category]];
  undo.push({ description: `Edit ${category}`, undo: () => { setData((d) => d ? { ...d, [category]: prev } : d); recalcDirty({ ...data!, [category]: prev }); } });
  const newData = { ...data!, [category]: newItems };
  setData(newData);
  recalcDirty(newData);
};

const recalcDirty = (currentData: CityData) => {
  if (!originalData) return;
  const dirty = new Set<string>();
  for (const cat of CATEGORIES) {
    const orig = (originalData as any)[cat.key] || [];
    const curr = (currentData as any)[cat.key] || [];
    // Detect added rows
    if (curr.length > orig.length) {
      for (let i = orig.length; i < curr.length; i++) {
        dirty.add(`added:${cat.key}:${i}`);
      }
    }
    // Detect field-level edits
    const minLen = Math.min(orig.length, curr.length);
    for (let i = 0; i < minLen; i++) {
      for (const col of getColumns(cat.key)) {
        const ov = JSON.stringify(orig[i]?.[col.key] ?? "");
        const cv = JSON.stringify(curr[i]?.[col.key] ?? "");
        if (ov !== cv) {
          dirty.add(`${cat.key}:${i}:${col.key}`);
        }
      }
    }
  }
  // Include pending deletions
  for (const del of pendingDeletions) {
    dirty.add(`deleted:${del.category}:${del.item.name || del.item.item}`);
  }
  setDirtyFields(dirty);
};
```

- [ ] **Step 3: Update handleDelete to recalculate dirty state**

```tsx
const handleDelete = (category: string, index: number, reason: string) => {
  const item = (data as any)[category][index];
  const prev = [...(data as any)[category]];
  const prevDeletions = [...pendingDeletions];
  const newItems = prev.filter((_, i) => i !== index);
  const newDeletions = [...pendingDeletions, { category, item, reason }];
  setPendingDeletions(newDeletions);
  undo.push({
    description: `Delete ${item.name || item.item}`,
    undo: () => {
      setData((d) => d ? { ...d, [category]: prev } : d);
      setPendingDeletions(prevDeletions);
      recalcDirty({ ...data!, [category]: prev });
    },
  });
  const newData = { ...data!, [category]: newItems };
  setData(newData);
  // Recalc with new deletions factored in
  if (!originalData) return;
  const dirty = new Set<string>();
  for (const cat of CATEGORIES) {
    const orig = (originalData as any)[cat.key] || [];
    const curr = (newData as any)[cat.key] || [];
    if (curr.length > orig.length) {
      for (let i = orig.length; i < curr.length; i++) dirty.add(`added:${cat.key}:${i}`);
    }
    const minLen = Math.min(orig.length, curr.length);
    for (let i = 0; i < minLen; i++) {
      for (const col of getColumns(cat.key)) {
        const ov = JSON.stringify(orig[i]?.[col.key] ?? "");
        const cv = JSON.stringify(curr[i]?.[col.key] ?? "");
        if (ov !== cv) dirty.add(`${cat.key}:${i}:${col.key}`);
      }
    }
  }
  for (const del of newDeletions) {
    dirty.add(`deleted:${del.category}:${del.item.name || del.item.item}`);
  }
  setDirtyFields(dirty);
};
```

- [ ] **Step 4: Update the save handler to reset dirty state**

```tsx
const handleSave = async () => {
  for (const del of pendingDeletions) {
    await api.logDeletion(cityName, del.category, del.item.name || del.item.item || "unknown", del.reason, del.item, userEmail || "Mayur Local");
  }
  await api.saveCity(cityName, data, userEmail || "Mayur Local");
  setPendingDeletions([]);
  setOriginalData(JSON.parse(JSON.stringify(data)));
  setDirtyFields(new Set());
  onRefreshTree();
};
```

- [ ] **Step 5: Update the display badge**

Change line 156 from:
```tsx
{unsavedChanges > 0 && <span className="text-sm text-slate-500">{unsavedChanges} unsaved changes</span>}
```
To:
```tsx
{dirtyFields.size > 0 && <span className="text-sm text-slate-500">{dirtyFields.size} unsaved changes</span>}
```

- [ ] **Step 6: Verify**

Run: `cd ui-frontend && npm run dev`

1. Select a city, click a row, edit one text field — badge should show "1 unsaved changes"
2. Edit same field again (more characters) — still shows "1"
3. Edit a second field — shows "2 unsaved changes"
4. Click Save — badge disappears

- [ ] **Step 7: Commit**

```bash
git add ui-frontend/src/components/CityView.tsx
git commit -m "fix: change counter tracks unique fields, not keystrokes"
```

---

### Task 3: Fix "+ Add" Button

**Files:**
- Modify: `ui-frontend/src/components/CityView.tsx`

- [ ] **Step 1: Define empty row templates**

Add a helper function above the `CityView` component:

```tsx
function emptyRow(category: string): Record<string, any> {
  switch (category) {
    case "restaurants":
      return { name: "", cuisine_type: [], hours: "", price_range: "", vegetarian_friendly: false, pure_vegetarian: false, must_try_dishes: "", best_for: [] };
    case "attractions":
      return { name: "", description: "", hours: "", entry_fee: "", recommended_duration: "" };
    case "hotels":
      return { name: "", location: "" };
    case "local_dishes":
      return { name: "", description: "", vegetarian: false, where_to_try: "" };
    case "souvenirs":
      return { item: "", category: "", where_to_buy: "" };
    default:
      return { name: "" };
  }
}
```

- [ ] **Step 2: Wire up the button onClick**

Replace the add button (line 149-151) with:

```tsx
<button
  onClick={() => {
    const newItem = emptyRow(activeTab);
    const currentItems = (data as any)[activeTab] || [];
    const newItems = [...currentItems, newItem];
    handleDataChange(activeTab, newItems);
  }}
  className="px-4 py-2 text-sm font-medium border border-slate-200 rounded-md hover:bg-slate-50"
>
  + Add {CATEGORIES.find((c) => c.key === activeTab)?.singular}
</button>
```

The new row will appear at the bottom with amber highlighting (missing required fields), drawing the user's attention to click and edit it.

- [ ] **Step 3: Verify**

Run: `cd ui-frontend && npm run dev`

1. Select a city, click "+ Add Restaurant" — new empty row appears at bottom with amber highlight
2. Click the new row — enters edit mode
3. Fill in fields, click Save — persists correctly
4. Click Undo after adding — row disappears

- [ ] **Step 4: Commit**

```bash
git add ui-frontend/src/components/CityView.tsx
git commit -m "fix: wire up Add button to append empty rows"
```

---

### Task 4: Loading Screen

**Files:**
- Create: `ui-frontend/src/components/LoadingScreen.tsx`
- Modify: `ui-frontend/src/App.tsx`

- [ ] **Step 1: Create LoadingScreen component**

Create `ui-frontend/src/components/LoadingScreen.tsx`:

```tsx
import { useEffect, useState } from "react";

interface LoadingScreenProps {
  loaded: boolean;
}

export function LoadingScreen({ loaded }: LoadingScreenProps) {
  const [progress, setProgress] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (loaded) {
      setProgress(100);
      const timer = setTimeout(() => setVisible(false), 400);
      return () => clearTimeout(timer);
    }
    // Animate to 90% over 3 seconds using intervals
    const start = Date.now();
    const duration = 3000;
    const interval = setInterval(() => {
      const elapsed = Date.now() - start;
      const fraction = Math.min(elapsed / duration, 1);
      // Ease-out curve: fast start, slow finish
      const eased = 1 - Math.pow(1 - fraction, 3);
      setProgress(Math.round(eased * 90));
    }, 50);
    return () => clearInterval(interval);
  }, [loaded]);

  if (!visible) return null;

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center bg-slate-50 transition-opacity duration-300 ${loaded ? "opacity-0" : "opacity-100"}`}>
      <div className="w-80 text-center">
        <h1 className="text-xl font-bold text-slate-900 mb-6">Library QC</h1>
        <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-200 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-sm text-slate-500 mt-3">Loading library data...</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Integrate LoadingScreen into App.tsx**

In `App.tsx`, add:

```tsx
import { LoadingScreen } from "./components/LoadingScreen";
```

Add a `treeLoaded` state:
```tsx
const [treeLoaded, setTreeLoaded] = useState(false);
```

Update the tree-loading useEffect:
```tsx
useEffect(() => {
  api.getTree().then((data) => {
    setTree(data as TreeData);
    setTreeLoaded(true);
  });
}, []);
```

Render the LoadingScreen at the top of the return JSX (before Layout):
```tsx
return (
  <>
    <LoadingScreen loaded={treeLoaded} />
    <Layout ...>
      {/* existing content */}
    </Layout>
  </>
);
```

- [ ] **Step 3: Verify**

Run: `cd ui-frontend && npm run dev`

1. Hard refresh the page — loading bar appears, fills smoothly, fades when data arrives
2. On fast connections (local dev), the bar appears briefly and disappears quickly — acceptable

- [ ] **Step 4: Commit**

```bash
git add ui-frontend/src/components/LoadingScreen.tsx ui-frontend/src/App.tsx
git commit -m "feat: add loading progress bar on initial page load"
```

---

### Task 5: Audit Backend — Expand audit_service.py

**Files:**
- Modify: `src/library/ui/services/audit_service.py`

- [ ] **Step 1: Add log_edit and log_add methods with 200-cap purge**

Rewrite `src/library/ui/services/audit_service.py`:

```python
from datetime import datetime, timezone
from typing import Optional

from ..storage import StorageBackend

MAX_AUDIT_ENTRIES = 200


class AuditService:
    """Manages the audit trail at _audit.json."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        data = self.backend.read_json("_audit.json")
        self._entries = data if isinstance(data, list) else []

    def _save(self):
        if len(self._entries) > MAX_AUDIT_ENTRIES:
            self._entries = self._entries[-MAX_AUDIT_ENTRIES:]
        self.backend.write_json("_audit.json", self._entries)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_deletion(
        self,
        category: str,
        city: str,
        item_name: str,
        reason: str,
        item_snapshot: dict,
        deleted_by: str = "unknown",
    ):
        entry = {
            "action": "delete",
            "category": category,
            "city": city,
            "item_name": item_name,
            "reason": reason,
            "changed_by": deleted_by,
            "changed_at": self._now(),
            "item_snapshot": item_snapshot,
        }
        self._entries.append(entry)
        self._save()

    def log_edit(
        self,
        category: str,
        city: str,
        item_name: str,
        changes: list[dict],
        changed_by: str = "unknown",
    ):
        entry = {
            "action": "edit",
            "category": category,
            "city": city,
            "item_name": item_name,
            "changes": changes,
            "changed_by": changed_by,
            "changed_at": self._now(),
        }
        self._entries.append(entry)
        self._save()

    def log_add(
        self,
        category: str,
        city: str,
        item_name: str,
        item_snapshot: dict,
        changed_by: str = "unknown",
    ):
        entry = {
            "action": "add",
            "category": category,
            "city": city,
            "item_name": item_name,
            "item_snapshot": item_snapshot,
            "changed_by": changed_by,
            "changed_at": self._now(),
        }
        self._entries.append(entry)
        self._save()

    def get_entries(self, limit: Optional[int] = None) -> list[dict]:
        entries = list(reversed(self._entries))
        if limit:
            return entries[:limit]
        return entries
```

- [ ] **Step 2: Commit**

```bash
git add src/library/ui/services/audit_service.py
git commit -m "feat: expand audit service with edit/add logging and 200-entry cap"
```

---

### Task 6: Audit Backend — Diff Logic in city.py

**Files:**
- Modify: `src/library/ui/api/city.py`

- [ ] **Step 1: Add diff logic to the PUT endpoint**

Rewrite `src/library/ui/api/city.py` to detect edits and additions by comparing incoming data against stored data:

```python
import json
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ..services.db_service import LibraryDBService
from ..services.audit_service import AuditService

router = APIRouter()

AUDITED_CATEGORIES = ("restaurants", "attractions", "hotels", "local_dishes", "souvenirs")


class DeleteItemRequest(BaseModel):
    reason: str
    deleted_by: str = "unknown"


def _diff_city(existing: dict, incoming: dict, changed_by: str, city: str, audit: AuditService):
    """Compare existing vs incoming city data and log edits/additions."""
    for category in AUDITED_CATEGORIES:
        orig_items = existing.get(category, [])
        new_items = incoming.get(category, [])

        min_len = min(len(orig_items), len(new_items))
        for i in range(min_len):
            changes = []
            for key in set(list(orig_items[i].keys()) + list(new_items[i].keys())):
                old_val = orig_items[i].get(key)
                new_val = new_items[i].get(key)
                if json.dumps(old_val, sort_keys=True, default=str) != json.dumps(new_val, sort_keys=True, default=str):
                    changes.append({"field": key, "old": old_val, "new": new_val})
            if changes:
                item_name = new_items[i].get("name") or new_items[i].get("item") or f"item_{i}"
                audit.log_edit(
                    category=category,
                    city=city,
                    item_name=item_name,
                    changes=changes,
                    changed_by=changed_by,
                )

        # New items added at end
        for i in range(min_len, len(new_items)):
            item_name = new_items[i].get("name") or new_items[i].get("item") or f"item_{i}"
            audit.log_add(
                category=category,
                city=city,
                item_name=item_name,
                item_snapshot=new_items[i],
                changed_by=changed_by,
            )


@router.get("/city/{name}")
def get_city(name: str, request: Request):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    return data


@router.put("/city/{name}")
def save_city(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.storage_backend)
    existing = db.get_city_data(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")

    changed_by = body.pop("changed_by", "unknown")
    audit = AuditService(request.app.state.storage_backend)
    _diff_city(existing, body, changed_by, name, audit)

    db.save_city_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}


@router.delete("/city/{name}/{category}/{index}")
def delete_item(name: str, category: str, index: int, request: Request, body: DeleteItemRequest):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    items = data.get(category, [])
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail=f"Item index {index} out of range")

    deleted_item = items.pop(index)
    db.save_city_data(name, data)

    audit = AuditService(request.app.state.storage_backend)
    audit.log_deletion(
        category=category,
        city=name,
        item_name=deleted_item.get("name", "unknown"),
        reason=body.reason,
        item_snapshot=deleted_item,
        deleted_by=body.deleted_by,
    )
    db.set_review_status(name, "in_progress")
    return {"status": "deleted"}
```

- [ ] **Step 2: Commit**

```bash
git add src/library/ui/api/city.py
git commit -m "feat: diff-based audit logging on city save"
```

---

### Task 7: Audit Frontend — Update API Client & Types

**Files:**
- Modify: `ui-frontend/src/api/client.ts`
- Modify: `ui-frontend/src/types.ts`

- [ ] **Step 1: Update saveCity to include changed_by**

In `ui-frontend/src/api/client.ts`, change the `saveCity` method:

```ts
saveCity: (name: string, data: any, changedBy?: string) =>
  request(`/city/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ ...data, changed_by: changedBy || "unknown" }) }),
```

- [ ] **Step 2: Expand AuditEntry type**

In `ui-frontend/src/types.ts`, replace the existing `AuditEntry` interface:

```ts
export interface AuditEntry {
  action: "edit" | "delete" | "add";
  category: string;
  city: string;
  item_name: string;
  changes?: { field: string; old: any; new: any }[];
  reason?: string;
  item_snapshot?: Record<string, any>;
  changed_by: string;
  changed_at: string;
}
```

- [ ] **Step 3: Commit**

```bash
git add ui-frontend/src/api/client.ts ui-frontend/src/types.ts
git commit -m "feat: update API client and types for expanded audit"
```

---

### Task 8: Audit Frontend — AuditLog Component

**Files:**
- Create: `ui-frontend/src/components/AuditLog.tsx`

- [ ] **Step 1: Create the AuditLog component**

Create `ui-frontend/src/components/AuditLog.tsx`:

```tsx
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
```

- [ ] **Step 2: Commit**

```bash
git add ui-frontend/src/components/AuditLog.tsx
git commit -m "feat: add AuditLog component"
```

---

### Task 9: Wire Everything Together in App.tsx and Layout.tsx

**Files:**
- Modify: `ui-frontend/src/App.tsx`
- Modify: `ui-frontend/src/components/Layout.tsx`
- Modify: `ui-frontend/src/components/CityView.tsx`

- [ ] **Step 1: Add Audit tab to Layout.tsx**

In `Layout.tsx`, add the Audit button after the History button:

```tsx
<button
  onClick={() => onModeChange("audit")}
  className={`px-4 py-2 rounded-md text-sm font-medium ${mode === "audit" ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
>
  Audit
</button>
```

Also hide sidebar for audit mode — update the condition on line 64:
```tsx
{mode !== "ingest" && mode !== "history" && mode !== "audit" && (
```

- [ ] **Step 2: Update App.tsx with audit mode and pass userEmail**

Import AuditLog:
```tsx
import { AuditLog } from "./components/AuditLog";
```

Update mode type (already done in Task 1 when we added it to LayoutProps). Add the audit route in the render:
```tsx
{mode === "audit" && <AuditLog />}
```

Pass `userEmail` to Layout and CityView:
```tsx
<Layout ... userEmail={userEmail}>
```

Pass `userEmail` to CityView:
```tsx
<CityView cityName={selectedCity} onRefreshTree={...} userEmail={userEmail} />
```

- [ ] **Step 3: Update CityView to accept and use userEmail prop**

Add `userEmail` to CityViewProps:
```tsx
interface CityViewProps {
  cityName: string;
  onRefreshTree: () => void;
  userEmail: string | null;
}

export function CityView({ cityName, onRefreshTree, userEmail }: CityViewProps) {
```

The `handleSave` (updated in Task 2) already uses `userEmail || "Mayur Local"`.

- [ ] **Step 4: Verify end-to-end**

Run both servers:
- Terminal 1: `cd /Users/mjain/work/projects/travel/BVBMGuide && python -m src.library.ui.server`
- Terminal 2: `cd /Users/mjain/work/projects/travel/BVBMGuide/ui-frontend && npm run dev`

Test:
1. App loads with progress bar, then shows UI
2. Select a city, edit a field — badge shows "1 unsaved changes"
3. Click "+ Add Restaurant" — new empty row appears
4. Click Save — changes persist
5. Click Audit tab — shows the edit/add entries just made
6. Delete a row (with reason) — shows in Audit tab as delete entry
7. Sign out link works (redirects to login page)

- [ ] **Step 5: Commit**

```bash
git add ui-frontend/src/App.tsx ui-frontend/src/components/Layout.tsx ui-frontend/src/components/CityView.tsx
git commit -m "feat: wire audit tab, loading screen, and user identity through app"
```

---

## Execution Order

Tasks 1-4 can be done in any order (independent bugs/features). Tasks 5-6 (backend audit) must precede Tasks 7-9 (frontend audit integration). Task 9 ties everything together.

Recommended serial order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
