# Library QC UI — Design Spec

A local web application for human QC of the library database (`library_db/`). Ensures data quality before it's used for AIG generation.

## Problem

The library database is built by AI extraction from 175+ source documents. AI makes systematic errors: missing hours, incorrect vegetarian flags, wrong cuisine classifications, hallucinated dishes. Garbage in = garbage out for AIG generation. A human needs to efficiently review and correct this data.

## Solution

A local web app served by a Python backend that reads/writes `library_db/` JSON shards directly. Provides two modes: city-by-city deep review and cross-city field sweeps.

---

## Architecture

```
Browser (React + Vite)
    ↕ REST API (JSON)
Python backend (FastAPI)
    ↕ reads/writes
library_db/
  ├── _index.json          (metadata, folder coverage, review status)
  ├── _audit.json          (deletion audit trail)
  ├── _country/
  │     ├── Italy.json     (connectivity, phrases, safety, health, emergency, transport)
  │     ├── France.json
  │     └── ...
  ├── Paris.json           (restaurants, attractions, hotels, local_dishes, souvenirs)
  ├── Florence.json
  └── ...
```

**Run command:** `python -m src.library ui`

No external database. No auth (internal tool, single user, local machine).

---

## Layout

### Top Navigation Bar
- Brand: "Library QC"
- Mode tabs: **City View** | **Sweep Mode**
- Right side: progress ("12 / 47 cities reviewed"), last saved timestamp

### Sidebar (260px, left)
- Search box (filters both countries and cities)
- Country/city hierarchy:
  - Countries: collapsible, flag emoji, city count badge
  - Cities: nested under country, status dot (green/yellow/grey), restaurant count
- Clicking a **country** → opens country-level editor in main panel
- Clicking a **city** → opens city-level editor in main panel
- Stats at top: total countries, cities, restaurants, review progress

### Main Panel (flex, right)
- Header: name + level badge (Country/City) + "Mark as Reviewed" button
- Category tabs (context-dependent, see below)
- Table area with toolbar and editable rows

---

## Data Hierarchy

### Country-level data (editable at country node)
- Connectivity tips (SIM, eSIM, WiFi)
- Transport options (trains, metro, passes)
- Phrases (greetings, common phrases)
- Safety tips
- Health tips (vaccinations, water safety)
- Emergency contacts

### City-level data (editable at city node)
- Restaurants
- Attractions
- Hotels
- Local dishes
- Souvenirs

Country-level data applies to all cities within that country. The sidebar visually distinguishes the two levels (amber highlight for country, blue for city).

### Storage: country-level data

Currently, multi-city items (connectivity_tips, safety_tips, health_tips, phrases) are duplicated across every relevant city shard. For the QC UI:

- The **library builder** will be updated to also produce `library_db/_country/{Country}.json` shards containing deduplicated country-level data.
- The UI reads/writes these country shards directly.
- City shards continue to hold city-specific data only (restaurants, attractions, hotels, local_dishes, souvenirs).
- On `library build`, country-level items are routed to country shards instead of being fanned out to city shards.

---

## Table Editing (City View)

### Interaction model
- Click a row to enter edit mode (row highlights blue, fields become editable)
- Text fields: `<textarea>` with `resize: both` — visible diagonal grip handle at bottom-right; column expands with content (table layout, not grid)
- Price range: currency dropdown (INR first, then country-relevant currencies, then rest) + free-text input
- Booleans: checkboxes (Vegetarian Friendly, Pure Vegetarian)
- Multi-value tags: removable pills with "+ add" button (e.g. best_for: casual, romantic, family)
- Missing data: rows with empty required fields highlighted amber with ⚠ markers

### Toolbar (per table)
- "+ Add [item]" button
- "↩ Undo" button (reverts last action)
- Unsaved changes counter
- "Save" button (writes to that city's JSON shard)

### Per-row delete
- Trash icon on each row
- Click → modal popup: "Why are you deleting this?" with textarea for reason
- Must provide reason to confirm deletion
- Deletion logged to audit trail

### Restaurant columns
| Column | Input type |
|--------|-----------|
| Name | textarea |
| Cuisine | textarea (comma-separated) |
| Hours | textarea |
| Price Range | currency dropdown + textarea |
| Vegetarian Friendly | checkbox |
| Pure Vegetarian | checkbox |
| Must-Try Dishes | textarea (comma-separated) |
| Best For | tag pills (predefined set: casual, romantic, elegant, family, wine, business) |

### Attraction columns
| Column | Input type |
|--------|-----------|
| Name | textarea |
| Description | textarea |
| Hours | textarea |
| Entry Fee | currency dropdown + textarea |
| Recommended Duration | textarea |

### Other category columns
Each category (hotels, local_dishes, souvenirs, etc.) gets a table with columns matching its schema in the library database. All follow the same edit pattern: click row → inline edit → save.

---

## Sweep Mode

Full-page view for reviewing one field across all cities simultaneously.

### Controls
- **Category dropdown**: Restaurants, Attractions, Hotels, Local Dishes, etc.
- **Field dropdown**: populated based on selected category (e.g. Vegetarian Friendly, Hours, Price Range)
- **Filter dropdown**: All, Only missing, Only unchecked, Only checked
- Stats bar: total count, filtered count, progress

### Table
- Rows grouped by city (collapsible city headers with count)
- Columns: City badge, item Name, the target field (editable), context column (related data to aid judgment)
- "Save All" button — writes changes across all affected city shards

### Context column
Shows related data to help the reviewer decide. Examples:
- Reviewing "Vegetarian Friendly" → shows must-try dishes (if dishes are all meat, probably not veg-friendly)
- Reviewing "Hours" → shows restaurant name and area
- Reviewing "Entry Fee" → shows attraction name and duration

---

## Review Status Tracking

### States
- **Pending** (grey dot) — never reviewed
- **In Progress** (yellow dot) — has been opened/edited but not marked reviewed
- **Reviewed** (green dot) — explicitly marked by user clicking "Mark as Reviewed"

### Rules
- Country review and city review are **independent**. Marking a country as reviewed does NOT mark its cities.
- When `python -m src.library build` processes new/updated files for a city, that city's status resets to **Pending**. Same for country-level data.
- Only the affected cities/countries reset, not the entire database.
- Status stored in `library_db/_index.json` under a `_review_status` key.

### Storage format
```json
"_review_status": {
  "Italy": { "status": "reviewed", "reviewed_at": "2026-05-13T...", "reviewed_by": "marina" },
  "Florence": { "status": "in_progress", "last_edited": "2026-05-13T..." },
  "Paris": { "status": "reviewed", "reviewed_at": "2026-05-12T...", "reviewed_by": "marina" },
  "Tokyo": { "status": "pending" }
}
```

---

## Audit Trail

All deletions are logged to `library_db/_audit.json`:

```json
[
  {
    "action": "delete",
    "category": "restaurants",
    "city": "Florence",
    "item_name": "Bad Restaurant",
    "reason": "Permanently closed as of 2025",
    "deleted_by": "marina",
    "deleted_at": "2026-05-13T14:30:00Z",
    "item_snapshot": { ...full item data at time of deletion... }
  }
]
```

The full item is snapshotted so deletions can be reversed if needed.

**User identity:** Since this is a local single-user tool with no auth, the `deleted_by` / `reviewed_by` field is read from a config value in `.env` (e.g. `QC_USER=marina`). Defaults to `"unknown"` if not set.

---

## Data Model Changes

Add to `Restaurant` schema (in library builder extraction + `src/common/models.py`):

```python
pure_vegetarian: bool = False  # Entire restaurant is vegetarian (no meat/fish served)
```

The existing `vegetarian_friendly: bool` means "has vegetarian options on the menu."

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tree` | Country/city hierarchy with review status and counts |
| GET | `/api/country/{name}` | Country-level data (connectivity, phrases, safety, etc.) |
| GET | `/api/city/{name}` | Full city shard data |
| PUT | `/api/city/{name}` | Save edited city data (writes JSON shard) |
| PUT | `/api/country/{name}` | Save edited country-level data |
| POST | `/api/city/{name}/review` | Mark city as reviewed |
| POST | `/api/country/{name}/review` | Mark country as reviewed |
| DELETE | `/api/city/{name}/{category}/{index}` | Delete an item (requires `reason` in body) |
| GET | `/api/sweep` | Query params: category, field, filter → returns cross-city data |
| PUT | `/api/sweep` | Bulk save sweep mode edits |
| GET | `/api/audit` | Audit trail entries |

---

## Tech Stack

- **Backend**: FastAPI (Python), reads/writes `library_db/` JSON directly
- **Frontend**: React (Vite) with a lightweight table component (e.g. TanStack Table)
- **Styling**: Tailwind CSS (light theme, slate/blue/green accents)
- **State**: No database — JSON files are the source of truth
- **Run**: `python -m src.library ui` starts FastAPI server + serves static frontend

---

## Visual Design

- Light theme: white backgrounds, slate-200 borders, blue accents for selections
- 14px base font, comfortable spacing for desktop use
- Resizable textareas with visible grip handles
- Status dots: green (reviewed), yellow (in progress), grey (pending)
- Warning rows: amber background + left border for missing data
- Edit rows: blue background + left border
- Tags as rounded pills (slate for display, green for removable)
- Country headers: amber highlight when selected, blue for cities

---

## Scope Boundaries

**In scope:**
- All data categories editable (restaurants, attractions, hotels, local_dishes, phrases, safety_tips, souvenirs, emergency_contacts, connectivity_tips, transport_options, health_tips)
- City view and sweep mode
- Review status tracking with auto-reset on rebuild
- Audit trail for deletions
- Undo (in-memory, per session)
- Pure Vegetarian field addition

**Out of scope (future):**
- Multi-user with auth
- Remote deployment (Lambda)
- Diff preview before save
- Bulk import/export
- Commenting/notes on items
