# Library QC UI — Bug Fixes & Audit Feature

**Date**: 2026-05-16  
**Scope**: 3 bug fixes + 2 new features for the Library QC web UI

---

## Bug 1: Change Counter Counts Keystrokes, Not Fields

**Problem**: `CityView.handleDataChange` increments `unsavedChanges` on every call to `onDataChange`, which fires on every keystroke in `EditableTable`. Typing "hello" shows "5 unsaved changes."

**Fix**:

Replace the integer `unsavedChanges` counter with a `Set<string>` of dirty field identifiers (`"rowIndex:fieldKey"`). The displayed count reflects unique fields touched, not event count.

- `CityView.tsx`: Change `unsavedChanges` from `number` to `Set<string>`. On each `onDataChange`, diff the new data against the original (loaded from API) to determine which fields actually differ. Display `dirtyFields.size` in the badge.
- Store the original loaded data in a ref (`originalData`) to diff against.
- On save, clear the set and update `originalData` to match current state.
- Deletions still count as 1 change each (add the deletion to the set as `"deleted:category:index"`).
- Adding a new row counts as 1 change (`"added:category:index"`).

**Result**: "3 unsaved changes" means 3 distinct fields/rows were modified.

---

## Bug 2: "+ Add" Button Non-functional

**Problem**: The `+ Add {singular}` button in `CityView.tsx:149` has no `onClick` handler.

**Fix**:

Add `onClick` handler that:
1. Creates a new empty row object matching the active category schema (e.g., `{ name: "", cuisine_type: [], hours: "", ... }` for restaurants).
2. Appends it to the current category array via `handleDataChange`.
3. Pushes an undo entry.
4. Sets `editingRow` in EditableTable to the new row's index (auto-enters edit mode).

**Implementation detail**: `EditableTable` needs to accept an optional `initialEditRow` prop so `CityView` can tell it to immediately edit the newly added row. Alternatively, just append and let the user click to edit — simpler, and the row will be highlighted amber (missing required fields) which draws attention.

**Chosen approach**: Append the new empty row. It will appear at the bottom (or top if sorted) with amber highlighting on missing required fields. User clicks it to edit. No need for `initialEditRow` prop — keeps it simple.

**Empty row templates by category**:
- restaurants: `{ name: "", cuisine_type: [], hours: "", price_range: "", vegetarian_friendly: false, pure_vegetarian: false, must_try_dishes: "", best_for: [] }`
- attractions: `{ name: "", description: "", hours: "", entry_fee: "", recommended_duration: "" }`
- hotels: `{ name: "", location: "" }`
- local_dishes: `{ name: "", description: "", vegetarian: false, where_to_try: "" }`
- souvenirs: `{ item: "", category: "", where_to_buy: "" }`

---

## Bug 3: Logout Not Working

**Problem**: `<a href="/logout">` in Layout.tsx navigates to the backend's `/logout` endpoint. The backend clears the session and redirects to `/login`. But the SPA catches the navigation or the React app re-renders over the login page.

**Fix**:

Two changes:

1. **Layout.tsx**: Change the `<a href="/logout">` to a button with `onClick={() => { window.location.href = '/logout'; }}`. This ensures full-page navigation, bypassing any client-side routing.

2. **App.tsx**: Before rendering the main app, check auth status. If `/api/me` returns 401, redirect to `/login` via `window.location.href`. This handles the case where the user lands on the app after session expiry.

Actually, looking more carefully — the existing `<a href="/logout">` should work as a full-page navigation since there's no client-side router (it's just React state, not react-router). The real issue is likely that in production (Lambda), the session cookie isn't being cleared properly due to cookie settings (domain/path mismatch or SameSite issues), OR the SPA is being served from `/` via StaticFiles mount and the `/logout` route isn't being reached.

**Root cause investigation**: In `__init__.py`, the `StaticFiles` mount at `/` with `html=True` is a catch-all that serves `index.html` for any unmatched path. Since it's mounted last via `app.mount("/", ...)`, and FastAPI routes are matched before mounts, `/logout` should resolve to the explicit route. However, the order of middleware matters — the `RequireGoogleAuthMiddleware` lists `/logout` as a PUBLIC_PATH, so it shouldn't redirect.

**Confirmed cause**: The Vite dev proxy only forwards `/api` routes to the backend (see `vite.config.ts`). In dev, clicking `/logout` hits Vite's dev server which serves `index.html` (SPA fallback). The React app re-renders, calls `/api/me` → 401, but never redirects. In prod (Lambda), the route should work since FastAPI handles it directly, but the frontend still doesn't gracefully handle session expiry.

**Fix (both dev and prod)**:
1. In `vite.config.ts`: add `/logout` and `/login` and `/auth` to the proxy config so they reach the backend in dev.
2. In Layout.tsx: keep the `<a href="/logout">` (it's fine for full-page nav), but add `target="_self"` for clarity.
3. In App.tsx: after the `/api/me` fetch returns 401, set an `authFailed` state. When `authFailed && GOOGLE_OAUTH likely enabled` (i.e., the 401 happened), show a "Session expired" message with a link to `/login` instead of rendering the blank app.

---

## Feature 1: Loading Progress Bar on Initial Load

**Problem**: On Lambda, the first `/api/tree` call may take several seconds as the backend reads all JSON files from S3. Users see a blank screen.

**Design**:

A full-screen loading overlay that shows while `api.getTree()` is in-flight:

- Centered card with "Library QC" title and animated progress bar
- Progress fills from 0% to ~90% over 3 seconds using CSS animation (ease-out curve)
- When data arrives, jumps to 100% and fades out (200ms transition)
- If the fetch takes longer than 3s, the bar holds at 90% until complete
- Subtle "Loading library data..." text below the bar
- Disappears once tree data is loaded and the app renders

**Implementation**:
- New component: `LoadingScreen.tsx`
- `App.tsx` wraps the tree-loading state: show `LoadingScreen` when `tree` is empty/null, show `Layout` when loaded
- Progress animation via CSS `@keyframes` + a `loaded` class that triggers the 100% jump
- No backend changes needed

---

## Feature 2: Audit Tab

**Problem**: No visibility into who changed what. Current audit only tracks deletions.

**Design**:

### Backend Changes

**Expand audit logging to cover all mutation types:**

| Action | Trigger | Logged Data |
|--------|---------|-------------|
| `edit` | PUT /api/city/{name} | category, city, fields changed (before/after), user |
| `delete` | Delete via UI (existing) | category, city, item_name, reason, snapshot, user |
| `add` | PUT /api/city/{name} (new rows detected) | category, city, item added, user |

**How edits/additions are detected**: The PUT `/api/city/{name}` endpoint compares incoming data against current stored data:
- For each category, compare arrays item-by-item (by index, since items don't have stable IDs)
- Fields that differ → log as `edit` entry with `{field, old_value, new_value}`
- Extra items at end of array → log as `add`
- Fewer items → already handled by explicit delete flow

**Audit entry schema** (expanded):
```json
{
  "action": "edit" | "delete" | "add",
  "category": "restaurants",
  "city": "Paris",
  "item_name": "Cafe de Flore",
  "changes": [{"field": "hours", "old": "9-17", "new": "9-22"}],  // for edits
  "reason": "Duplicate",  // for deletes
  "item_snapshot": {},  // for deletes and adds
  "changed_by": "marina@example.com",
  "changed_at": "2026-05-16T12:34:56.789Z"
}
```

**200-entry cap**: After appending new entries, if total exceeds 200, trim from the front (oldest entries removed). Applied on every write.

**User identity**: 
- Auth enabled: use email from session (`request.session["user"]["email"]`)
- Auth disabled: use `"Mayur Local"`
- Frontend sends the user identity with save requests (new field in PUT body: `changed_by`)

### Frontend Changes

**New tab**: "Audit" added as 5th tab in Layout.tsx header, after "History".

**New component**: `AuditLog.tsx`
- Fetches `GET /api/audit?limit=200`
- Displays a table with columns: Time, User, Action, City, Category, Item, Details
- Action column uses colored badges: blue for edit, red for delete, green for add
- Details column: for edits shows "field: old → new"; for deletes shows reason; for adds shows item name
- Sortable by time (default: newest first)
- Optional filter by action type (all/edit/delete/add)

**Mode addition**: Add `"audit"` to the mode union type in App.tsx and Layout.tsx.

### Data Flow

1. User edits a field in CityView → clicks Save
2. Frontend sends PUT `/api/city/{name}` with `{ ...cityData, changed_by: userEmail }`
3. Backend diffs incoming vs stored data
4. Backend writes city JSON, then appends audit entries for each change detected
5. Backend trims audit to 200 entries max
6. Audit tab fetches and displays the log

---

## Files Modified

| File | Changes |
|------|---------|
| `ui-frontend/src/components/CityView.tsx` | Bug 1 (change tracking), Bug 2 (add button), pass user to save |
| `ui-frontend/src/components/EditableTable.tsx` | No changes needed |
| `ui-frontend/src/components/Layout.tsx` | Bug 3 (logout fix), add Audit tab |
| `ui-frontend/src/App.tsx` | Feature 1 (loading screen), add audit mode, auth-failed state |
| `ui-frontend/vite.config.ts` | Bug 3 (proxy /logout, /login, /auth to backend) |
| `ui-frontend/src/components/LoadingScreen.tsx` | **New** — loading progress bar |
| `ui-frontend/src/components/AuditLog.tsx` | **New** — audit tab UI |
| `ui-frontend/src/api/client.ts` | Update saveCity to include changed_by |
| `src/library/ui/api/city.py` | Diff logic for audit logging on PUT |
| `src/library/ui/services/audit_service.py` | New methods: log_edit, log_add; 200-cap purge |
| `src/library/ui/__init__.py` | Possibly: helper to extract user from request |
