# Library QC UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web app for human QC of library_db data — editable tables for restaurants, attractions, and all other categories, with country/city hierarchy, review tracking, and audit trail.

**Architecture:** FastAPI backend serves a React (Vite) frontend. Backend reads/writes library_db/ JSON shards directly. No external database. Country-level data (connectivity, phrases, safety, etc.) is extracted into `_country/` sub-directory. Review status stored in `_index.json`. Audit trail in `_audit.json`.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, React 18, Vite, TanStack Table, Tailwind CSS

---

## File Structure

```
src/library/
  ui/
    __init__.py              — FastAPI app factory
    server.py                — uvicorn launcher (called by CLI)
    api/
      __init__.py
      tree.py                — GET /api/tree endpoint
      city.py                — GET/PUT /api/city/{name}, DELETE item
      country.py             — GET/PUT /api/country/{name}
      review.py              — POST review status endpoints
      sweep.py               — GET/PUT /api/sweep
      audit.py               — GET /api/audit
    services/
      __init__.py
      db_service.py          — reads/writes library_db/ shards, manages review status
      country_extractor.py   — aggregates country-level data from city shards
      audit_service.py       — reads/writes _audit.json

ui-frontend/                 — React app (separate from Python src)
  package.json
  vite.config.ts
  tailwind.config.js
  src/
    main.tsx
    App.tsx
    api/
      client.ts              — fetch wrapper for all API calls
    components/
      Layout.tsx             — top nav + sidebar + main panel shell
      Sidebar.tsx            — country/city tree with search and status dots
      CityView.tsx           — category tabs + editable table for one city
      CountryView.tsx        — category tabs + editable table for country-level data
      SweepMode.tsx          — cross-city field review
      EditableTable.tsx      — generic table with click-to-edit rows
      DeleteModal.tsx        — confirmation popup with reason textarea
    hooks/
      useUndoStack.ts        — undo state management
    types.ts                 — TypeScript types matching backend schemas
```

---

## Task 1: Add dependencies and create backend skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `src/library/ui/__init__.py`
- Create: `src/library/ui/server.py`
- Create: `src/library/ui/api/__init__.py`
- Modify: `src/library/__main__.py` (add `ui` command)

- [ ] **Step 1: Add FastAPI + uvicorn to requirements.txt**

Add to `requirements.txt`:
```
# QC UI
fastapi>=0.115.0
uvicorn>=0.30.0
```

- [ ] **Step 2: Create FastAPI app factory**

Create `src/library/ui/__init__.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app(db_path: str = "library_db") -> FastAPI:
    app = FastAPI(title="Library QC", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.db_path = db_path

    from .api import tree, city, country, review, sweep, audit
    app.include_router(tree.router, prefix="/api")
    app.include_router(city.router, prefix="/api")
    app.include_router(country.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(sweep.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")

    return app
```

- [ ] **Step 3: Create server launcher**

Create `src/library/ui/server.py`:
```python
import uvicorn
from . import create_app


def run(db_path: str = "library_db", host: str = "127.0.0.1", port: int = 8000):
    app = create_app(db_path=db_path)
    uvicorn.run(app, host=host, port=port)
```

- [ ] **Step 4: Create empty API router modules**

Create `src/library/ui/api/__init__.py`:
```python
```

Create each router stub (`tree.py`, `city.py`, `country.py`, `review.py`, `sweep.py`, `audit.py`) with:
```python
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 5: Add `ui` command to library CLI**

Add to `src/library/__main__.py`:
```python
@app.command()
def ui(
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Server host"),
    port: int = typer.Option(8000, "--port", help="Server port"),
):
    """Launch the Library QC web interface."""
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build' first.")
        raise typer.Exit(1)

    console.print(f"[bold blue]Library QC UI[/bold blue]")
    console.print(f"[dim]http://{host}:{port}[/dim]\n")

    from .ui.server import run
    run(db_path=str(db_path), host=host, port=port)
```

- [ ] **Step 6: Verify server starts**

Run: `python -m src.library ui --help`
Expected: Shows usage with --db, --host, --port options

- [ ] **Step 7: Commit**

```bash
git add requirements.txt src/library/ui/ src/library/__main__.py
git commit -m "feat(library-qc): add FastAPI backend skeleton with ui command"
```

---

## Task 2: Database service layer

**Files:**
- Create: `src/library/ui/services/__init__.py`
- Create: `src/library/ui/services/db_service.py`

- [ ] **Step 1: Create db_service.py**

```python
import json
from pathlib import Path
from typing import Optional


class LibraryDBService:
    """Reads and writes library_db/ shards for the QC UI."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._index: dict = {}
        self._load_index()

    def _load_index(self):
        index_path = self.db_path / "_index.json"
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                self._index = json.load(f)

    def _save_index(self):
        index_path = self.db_path / "_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def get_folder_coverage(self) -> dict[str, list[str]]:
        return self._index.get("_folder_coverage", {})

    def get_review_status(self) -> dict[str, dict]:
        return self._index.get("_review_status", {})

    def set_review_status(self, name: str, status: str, reviewed_by: str = "unknown"):
        if "_review_status" not in self._index:
            self._index["_review_status"] = {}
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        if status == "reviewed":
            self._index["_review_status"][name] = {
                "status": "reviewed",
                "reviewed_at": now,
                "reviewed_by": reviewed_by,
            }
        elif status == "in_progress":
            self._index["_review_status"][name] = {
                "status": "in_progress",
                "last_edited": now,
            }
        else:
            self._index["_review_status"][name] = {"status": "pending"}
        self._save_index()

    def get_city_data(self, city: str) -> Optional[dict]:
        city_path = self.db_path / f"{city}.json"
        if not city_path.exists():
            return None
        with open(city_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_city_data(self, city: str, data: dict):
        city_path = self.db_path / f"{city}.json"
        with open(city_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_country_data(self, country: str) -> Optional[dict]:
        country_dir = self.db_path / "_country"
        country_path = country_dir / f"{country}.json"
        if not country_path.exists():
            return None
        with open(country_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_country_data(self, country: str, data: dict):
        country_dir = self.db_path / "_country"
        country_dir.mkdir(exist_ok=True)
        country_path = country_dir / f"{country}.json"
        with open(country_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_all_city_names(self) -> list[str]:
        return [
            f.stem for f in sorted(self.db_path.glob("*.json"))
            if f.name != "_index.json"
        ]

    def get_tree(self) -> dict:
        """Build country/city hierarchy for the sidebar."""
        coverage = self.get_folder_coverage()
        review_status = self.get_review_status()
        existing_shards = set(self.get_all_city_names())

        tree = {}
        for folder, cities in sorted(coverage.items()):
            city_nodes = []
            for city in sorted(cities):
                if city in existing_shards:
                    shard = self.get_city_data(city)
                    restaurant_count = len(shard.get("restaurants", [])) if shard else 0
                    city_nodes.append({
                        "name": city,
                        "status": review_status.get(city, {}).get("status", "pending"),
                        "restaurant_count": restaurant_count,
                    })
            tree[folder] = {
                "cities": city_nodes,
                "status": review_status.get(folder, {}).get("status", "pending"),
            }

        return tree
```

- [ ] **Step 2: Create `services/__init__.py`**

```python
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from src.library.ui.services.db_service import LibraryDBService; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/library/ui/services/
git commit -m "feat(library-qc): add database service layer for reading/writing shards"
```

---

## Task 3: Country data extractor

**Files:**
- Create: `src/library/ui/services/country_extractor.py`

- [ ] **Step 1: Create country_extractor.py**

This service aggregates country-level data from city shards into `_country/` directory on first access.

```python
import json
from pathlib import Path


COUNTRY_LEVEL_FIELDS = [
    "connectivity_tips",
    "safety_tips",
    "health_tips",
    "phrases",
    "emergency_contacts",
    "transport_options",
]


def extract_country_data(db_path: Path, folder_name: str, city_names: list[str]) -> dict:
    """Aggregate country-level data from city shards for a given folder/country."""
    country_data: dict[str, list] = {field: [] for field in COUNTRY_LEVEL_FIELDS}
    seen_tips: dict[str, set] = {field: set() for field in COUNTRY_LEVEL_FIELDS}

    for city in city_names:
        city_path = db_path / f"{city}.json"
        if not city_path.exists():
            continue
        with open(city_path, "r", encoding="utf-8") as f:
            shard = json.load(f)

        for field in COUNTRY_LEVEL_FIELDS:
            items = shard.get(field, [])
            for item in items:
                # Deduplicate by content (tip text or phrase text)
                key_field = "tip" if "tip" in item else "phrase" if "phrase" in item else "english" if "english" in item else None
                if key_field:
                    key = item.get(key_field, "")
                    if key in seen_tips[field]:
                        continue
                    seen_tips[field].add(key)
                else:
                    # For items without a clear dedup key, use full JSON
                    item_key = json.dumps(item, sort_keys=True)
                    if item_key in seen_tips[field]:
                        continue
                    seen_tips[field].add(item_key)
                country_data[field].append(item)

    # Also check if the folder itself has a shard (e.g., "Japan.json" exists as both folder and shard)
    folder_path = db_path / f"{folder_name}.json"
    if folder_path.exists() and folder_name not in city_names:
        with open(folder_path, "r", encoding="utf-8") as f:
            shard = json.load(f)
        for field in COUNTRY_LEVEL_FIELDS:
            items = shard.get(field, [])
            for item in items:
                key_field = "tip" if "tip" in item else "phrase" if "phrase" in item else "english" if "english" in item else None
                if key_field:
                    key = item.get(key_field, "")
                    if key in seen_tips[field]:
                        continue
                    seen_tips[field].add(key)
                else:
                    item_key = json.dumps(item, sort_keys=True)
                    if item_key in seen_tips[field]:
                        continue
                    seen_tips[field].add(item_key)
                country_data[field].append(item)

    return country_data


def ensure_country_shards(db_path: Path) -> None:
    """Generate _country/ shards from city data if they don't exist yet."""
    country_dir = db_path / "_country"
    if country_dir.exists() and any(country_dir.glob("*.json")):
        return  # Already extracted

    country_dir.mkdir(exist_ok=True)
    index_path = db_path / "_index.json"
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    folder_coverage = index.get("_folder_coverage", {})
    for folder, cities in folder_coverage.items():
        data = extract_country_data(db_path, folder, cities)
        # Only write if there's actual data
        if any(data.values()):
            with open(country_dir / f"{folder}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 2: Verify extraction works**

Run:
```bash
python -c "
from src.library.ui.services.country_extractor import ensure_country_shards
from pathlib import Path
ensure_country_shards(Path('library_db'))
import os
files = os.listdir('library_db/_country')
print(f'{len(files)} country shards created')
print(files[:5])
"
```
Expected: Shows country shards were created.

- [ ] **Step 3: Commit**

```bash
git add src/library/ui/services/country_extractor.py
git commit -m "feat(library-qc): add country data extractor from city shards"
```

---

## Task 4: Audit service

**Files:**
- Create: `src/library/ui/services/audit_service.py`

- [ ] **Step 1: Create audit_service.py**

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditService:
    """Manages the deletion audit trail at library_db/_audit.json."""

    def __init__(self, db_path: str | Path):
        self.audit_path = Path(db_path) / "_audit.json"
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        if self.audit_path.exists():
            with open(self.audit_path, "r", encoding="utf-8") as f:
                self._entries = json.load(f)
        else:
            self._entries = []

    def _save(self):
        with open(self.audit_path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

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
            "deleted_by": deleted_by,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "item_snapshot": item_snapshot,
        }
        self._entries.append(entry)
        self._save()

    def get_entries(self, limit: Optional[int] = None) -> list[dict]:
        entries = list(reversed(self._entries))  # newest first
        if limit:
            return entries[:limit]
        return entries
```

- [ ] **Step 2: Commit**

```bash
git add src/library/ui/services/audit_service.py
git commit -m "feat(library-qc): add audit trail service for deletions"
```

---

## Task 5: API endpoints — tree, city, country

**Files:**
- Modify: `src/library/ui/api/tree.py`
- Modify: `src/library/ui/api/city.py`
- Modify: `src/library/ui/api/country.py`

- [ ] **Step 1: Implement tree endpoint**

`src/library/ui/api/tree.py`:
```python
from fastapi import APIRouter, Request

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/tree")
def get_tree(request: Request):
    db = LibraryDBService(request.app.state.db_path)
    return db.get_tree()
```

- [ ] **Step 2: Implement city endpoints**

`src/library/ui/api/city.py`:
```python
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ..services.db_service import LibraryDBService
from ..services.audit_service import AuditService

router = APIRouter()


class DeleteItemRequest(BaseModel):
    reason: str
    deleted_by: str = "unknown"


@router.get("/city/{name}")
def get_city(name: str, request: Request):
    db = LibraryDBService(request.app.state.db_path)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    return data


@router.put("/city/{name}")
def save_city(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.db_path)
    existing = db.get_city_data(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    db.save_city_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}


@router.delete("/city/{name}/{category}/{index}")
def delete_item(name: str, category: str, index: int, request: Request, body: DeleteItemRequest):
    db = LibraryDBService(request.app.state.db_path)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    items = data.get(category, [])
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail=f"Item index {index} out of range")

    deleted_item = items.pop(index)
    db.save_city_data(name, data)

    audit = AuditService(request.app.state.db_path)
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

- [ ] **Step 3: Implement country endpoints**

`src/library/ui/api/country.py`:
```python
from fastapi import APIRouter, Request, HTTPException

from ..services.db_service import LibraryDBService
from ..services.country_extractor import ensure_country_shards
from pathlib import Path

router = APIRouter()


@router.get("/country/{name}")
def get_country(name: str, request: Request):
    db_path = Path(request.app.state.db_path)
    ensure_country_shards(db_path)
    db = LibraryDBService(request.app.state.db_path)
    data = db.get_country_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Country '{name}' not found")
    return data


@router.put("/country/{name}")
def save_country(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.db_path)
    db.save_country_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}
```

- [ ] **Step 4: Verify endpoints work**

Run:
```bash
# Start the server in background
python -m src.library ui &
sleep 2
# Test tree endpoint
curl -s http://127.0.0.1:8000/api/tree | python -m json.tool | head -20
# Test city endpoint
curl -s http://127.0.0.1:8000/api/city/Paris | python -m json.tool | head -10
# Kill server
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add src/library/ui/api/tree.py src/library/ui/api/city.py src/library/ui/api/country.py
git commit -m "feat(library-qc): implement tree, city, and country API endpoints"
```

---

## Task 6: API endpoints — review, sweep, audit

**Files:**
- Modify: `src/library/ui/api/review.py`
- Modify: `src/library/ui/api/sweep.py`
- Modify: `src/library/ui/api/audit.py`

- [ ] **Step 1: Implement review endpoint**

`src/library/ui/api/review.py`:
```python
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services.db_service import LibraryDBService

router = APIRouter()


class ReviewRequest(BaseModel):
    reviewed_by: str = "unknown"


@router.post("/city/{name}/review")
def review_city(name: str, request: Request, body: ReviewRequest):
    db = LibraryDBService(request.app.state.db_path)
    db.set_review_status(name, "reviewed", reviewed_by=body.reviewed_by)
    return {"status": "reviewed"}


@router.post("/country/{name}/review")
def review_country(name: str, request: Request, body: ReviewRequest):
    db = LibraryDBService(request.app.state.db_path)
    db.set_review_status(name, "reviewed", reviewed_by=body.reviewed_by)
    return {"status": "reviewed"}
```

- [ ] **Step 2: Implement sweep endpoint**

`src/library/ui/api/sweep.py`:
```python
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel
from typing import Optional

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/sweep")
def get_sweep(
    request: Request,
    category: str = Query(..., description="e.g. restaurants, attractions"),
    field: Optional[str] = Query(None, description="e.g. vegetarian_friendly, hours"),
    filter: Optional[str] = Query(None, description="all, missing, unchecked, checked"),
):
    db = LibraryDBService(request.app.state.db_path)
    coverage = db.get_folder_coverage()
    results = []

    all_cities = db.get_all_city_names()
    for city_name in all_cities:
        data = db.get_city_data(city_name)
        if not data:
            continue
        items = data.get(category, [])
        for idx, item in enumerate(items):
            # Apply field filter
            if field and filter:
                value = item.get(field)
                if filter == "missing" and value not in (None, "", []):
                    continue
                if filter == "unchecked" and value is not False:
                    continue
                if filter == "checked" and value is not True:
                    continue

            results.append({
                "city": city_name,
                "index": idx,
                "item": item,
            })

    return {
        "category": category,
        "field": field,
        "filter": filter,
        "total": len(results),
        "items": results,
    }


class SweepSaveRequest(BaseModel):
    edits: list[dict]  # [{city, index, category, field, value}]


@router.put("/sweep")
def save_sweep(request: Request, body: SweepSaveRequest):
    db = LibraryDBService(request.app.state.db_path)
    affected_cities: set[str] = set()

    for edit in body.edits:
        city = edit["city"]
        index = edit["index"]
        category = edit["category"]
        field_name = edit["field"]
        value = edit["value"]

        data = db.get_city_data(city)
        if not data:
            continue
        items = data.get(category, [])
        if index < 0 or index >= len(items):
            continue
        items[index][field_name] = value
        db.save_city_data(city, data)
        affected_cities.add(city)

    for city in affected_cities:
        db.set_review_status(city, "in_progress")

    return {"status": "saved", "affected_cities": len(affected_cities)}
```

- [ ] **Step 3: Implement audit endpoint**

`src/library/ui/api/audit.py`:
```python
from fastapi import APIRouter, Request, Query
from typing import Optional

from ..services.audit_service import AuditService

router = APIRouter()


@router.get("/audit")
def get_audit(request: Request, limit: Optional[int] = Query(None)):
    audit = AuditService(request.app.state.db_path)
    return audit.get_entries(limit=limit)
```

- [ ] **Step 4: Verify sweep endpoint**

Run:
```bash
python -m src.library ui &
sleep 2
curl -s "http://127.0.0.1:8000/api/sweep?category=restaurants&field=vegetarian_friendly&filter=unchecked" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Total: {d[\"total\"]}'); print(json.dumps(d['items'][:2], indent=2))"
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add src/library/ui/api/review.py src/library/ui/api/sweep.py src/library/ui/api/audit.py
git commit -m "feat(library-qc): implement review, sweep, and audit API endpoints"
```

---

## Task 7: React frontend setup

**Files:**
- Create: `ui-frontend/` directory with Vite + React + Tailwind scaffold

- [ ] **Step 1: Scaffold React project**

```bash
cd /Users/mjain/work/projects/travel/BVBMGuide
npm create vite@latest ui-frontend -- --template react-ts
cd ui-frontend
npm install
npm install -D tailwindcss @tailwindcss/vite
npm install @tanstack/react-table
```

- [ ] **Step 2: Configure Tailwind**

Add to `ui-frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
```

Replace `ui-frontend/src/index.css` with:
```css
@import "tailwindcss";
```

- [ ] **Step 3: Create TypeScript types**

Create `ui-frontend/src/types.ts`:
```typescript
export interface CityNode {
  name: string;
  status: "pending" | "in_progress" | "reviewed";
  restaurant_count: number;
}

export interface CountryNode {
  cities: CityNode[];
  status: "pending" | "in_progress" | "reviewed";
}

export type TreeData = Record<string, CountryNode>;

export interface Restaurant {
  name: string;
  city?: string;
  cuisine_type?: string[];
  hours?: string;
  price_range?: string;
  area?: string;
  ambience?: string;
  nearby_landmarks?: string[];
  must_try_dishes?: string[];
  best_for?: string[];
  vegetarian_friendly?: boolean;
  pure_vegetarian?: boolean;
  highlights?: string[];
  source_files?: string[];
}

export interface Attraction {
  name: string;
  city?: string;
  description?: string;
  hours?: string;
  entry_fee?: string;
  recommended_duration?: string;
  source_files?: string[];
}

export interface CityData {
  restaurants: Restaurant[];
  attractions: Attraction[];
  hotels: any[];
  local_dishes: any[];
  phrases: any[];
  safety_tips: any[];
  souvenirs: any[];
  emergency_contacts: any[];
  connectivity_tips: any[];
  transport_options: any[];
  health_tips: any[];
  source_files: string[];
}

export interface SweepItem {
  city: string;
  index: number;
  item: Record<string, any>;
}

export interface SweepResult {
  category: string;
  field: string | null;
  filter: string | null;
  total: number;
  items: SweepItem[];
}

export interface AuditEntry {
  action: string;
  category: string;
  city: string;
  item_name: string;
  reason: string;
  deleted_by: string;
  deleted_at: string;
  item_snapshot: Record<string, any>;
}
```

- [ ] **Step 4: Create API client**

Create `ui-frontend/src/api/client.ts`:
```typescript
const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export const api = {
  getTree: () => request<Record<string, any>>("/tree"),
  getCity: (name: string) => request<Record<string, any>>(`/city/${encodeURIComponent(name)}`),
  saveCity: (name: string, data: any) =>
    request(`/city/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteItem: (city: string, category: string, index: number, reason: string, deletedBy: string) =>
    request(`/city/${encodeURIComponent(city)}/${category}/${index}`, {
      method: "DELETE",
      body: JSON.stringify({ reason, deleted_by: deletedBy }),
    }),
  getCountry: (name: string) => request<Record<string, any>>(`/country/${encodeURIComponent(name)}`),
  saveCountry: (name: string, data: any) =>
    request(`/country/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(data) }),
  reviewCity: (name: string, reviewedBy: string) =>
    request(`/city/${encodeURIComponent(name)}/review`, {
      method: "POST",
      body: JSON.stringify({ reviewed_by: reviewedBy }),
    }),
  reviewCountry: (name: string, reviewedBy: string) =>
    request(`/country/${encodeURIComponent(name)}/review`, {
      method: "POST",
      body: JSON.stringify({ reviewed_by: reviewedBy }),
    }),
  getSweep: (category: string, field?: string, filter?: string) => {
    const params = new URLSearchParams({ category });
    if (field) params.set("field", field);
    if (filter) params.set("filter", filter);
    return request<Record<string, any>>(`/sweep?${params}`);
  },
  saveSweep: (edits: any[]) =>
    request("/sweep", { method: "PUT", body: JSON.stringify({ edits }) }),
  getAudit: (limit?: number) =>
    request<any[]>(`/audit${limit ? `?limit=${limit}` : ""}`),
};
```

- [ ] **Step 5: Verify frontend dev server starts**

```bash
cd ui-frontend && npm run dev
```
Expected: Vite dev server starts, proxies /api to FastAPI backend.

- [ ] **Step 6: Commit**

```bash
git add ui-frontend/
git commit -m "feat(library-qc): scaffold React frontend with Vite, Tailwind, types, API client"
```

---

## Task 8: Layout shell and Sidebar component

**Files:**
- Create: `ui-frontend/src/App.tsx`
- Create: `ui-frontend/src/components/Layout.tsx`
- Create: `ui-frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: Create Layout component**

`ui-frontend/src/components/Layout.tsx`:
```typescript
import { ReactNode } from "react";

interface LayoutProps {
  mode: "city" | "sweep";
  onModeChange: (mode: "city" | "sweep") => void;
  reviewedCount: number;
  totalCount: number;
  sidebar: ReactNode;
  children: ReactNode;
}

export function Layout({ mode, onModeChange, reviewedCount, totalCount, sidebar, children }: LayoutProps) {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top nav */}
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
        </div>
        <div className="ml-auto text-sm text-slate-500">
          {reviewedCount} / {totalCount} cities reviewed
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[260px] bg-white border-r border-slate-200 overflow-y-auto flex-shrink-0">
          {sidebar}
        </aside>
        <main className="flex-1 overflow-y-auto p-6 bg-slate-50">
          {children}
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create Sidebar component**

`ui-frontend/src/components/Sidebar.tsx`:
```typescript
import { useState, useMemo } from "react";
import { TreeData } from "../types";

interface SidebarProps {
  tree: TreeData;
  selectedCity: string | null;
  selectedCountry: string | null;
  onSelectCity: (city: string) => void;
  onSelectCountry: (country: string) => void;
}

const STATUS_COLORS = {
  reviewed: "bg-green-500",
  in_progress: "bg-amber-400",
  pending: "bg-slate-300",
};

export function Sidebar({ tree, selectedCity, selectedCountry, onSelectCity, onSelectCountry }: SidebarProps) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set(Object.keys(tree)));

  const filteredTree = useMemo(() => {
    if (!search.trim()) return tree;
    const q = search.toLowerCase();
    const result: TreeData = {};
    for (const [country, node] of Object.entries(tree)) {
      if (country.toLowerCase().includes(q)) {
        result[country] = node;
      } else {
        const matchedCities = node.cities.filter((c) => c.name.toLowerCase().includes(q));
        if (matchedCities.length > 0) {
          result[country] = { ...node, cities: matchedCities };
        }
      }
    }
    return result;
  }, [tree, search]);

  const toggleExpand = (country: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(country)) next.delete(country);
      else next.add(country);
      return next;
    });
  };

  const totalCities = Object.values(tree).reduce((sum, n) => sum + n.cities.length, 0);
  const totalRestaurants = Object.values(tree).reduce(
    (sum, n) => sum + n.cities.reduce((s, c) => s + c.restaurant_count, 0), 0
  );

  return (
    <div className="py-4">
      <div className="px-4 pb-4 text-xs text-slate-500 border-b border-slate-200 mb-3">
        <div className="mb-1"><strong>{Object.keys(tree).length}</strong> countries · <strong>{totalCities}</strong> cities · <strong>{totalRestaurants}</strong> restaurants</div>
      </div>
      <div className="px-3 mb-3">
        <input
          type="text"
          placeholder="Search countries or cities..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-slate-200 rounded-md bg-slate-50 focus:outline-none focus:border-blue-400"
        />
      </div>
      {Object.entries(filteredTree).map(([country, node]) => (
        <div key={country} className="mb-1">
          <button
            onClick={() => { toggleExpand(country); onSelectCountry(country); }}
            className={`w-full px-4 py-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wide cursor-pointer transition-colors ${
              selectedCountry === country ? "bg-amber-50 text-amber-800 border-r-[3px] border-amber-400" : "text-slate-500 hover:bg-slate-50"
            }`}
          >
            <span className={`text-[10px] transition-transform ${expanded.has(country) ? "rotate-90" : ""}`}>▶</span>
            {country}
            <span className="ml-auto text-[10px] font-medium bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
              {node.cities.length}
            </span>
          </button>
          {expanded.has(country) && (
            <div>
              {node.cities.map((city) => (
                <button
                  key={city.name}
                  onClick={() => onSelectCity(city.name)}
                  className={`w-full pl-9 pr-4 py-[7px] flex items-center gap-2.5 text-[13px] cursor-pointer transition-colors ${
                    selectedCity === city.name ? "bg-blue-50 text-blue-600 font-medium border-r-[3px] border-blue-500" : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full ${STATUS_COLORS[city.status]}`} />
                  {city.name}
                  <span className="ml-auto text-[11px] text-slate-400">{city.restaurant_count}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Wire up App.tsx**

`ui-frontend/src/App.tsx`:
```typescript
import { useEffect, useState } from "react";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { TreeData } from "./types";
import { api } from "./api/client";

export default function App() {
  const [mode, setMode] = useState<"city" | "sweep">("city");
  const [tree, setTree] = useState<TreeData>({});
  const [selectedCity, setSelectedCity] = useState<string | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);

  useEffect(() => {
    api.getTree().then((data) => setTree(data as TreeData));
  }, []);

  const reviewedCount = Object.values(tree).reduce(
    (sum, n) => sum + n.cities.filter((c) => c.status === "reviewed").length, 0
  );
  const totalCount = Object.values(tree).reduce((sum, n) => sum + n.cities.length, 0);

  return (
    <Layout
      mode={mode}
      onModeChange={setMode}
      reviewedCount={reviewedCount}
      totalCount={totalCount}
      sidebar={
        <Sidebar
          tree={tree}
          selectedCity={selectedCity}
          selectedCountry={selectedCountry}
          onSelectCity={(city) => { setSelectedCity(city); setSelectedCountry(null); }}
          onSelectCountry={(country) => { setSelectedCountry(country); setSelectedCity(null); }}
        />
      }
    >
      <div className="text-slate-400 text-center py-20">
        {selectedCity && <p>City view for <strong>{selectedCity}</strong> — next task</p>}
        {selectedCountry && <p>Country view for <strong>{selectedCountry}</strong> — next task</p>}
        {!selectedCity && !selectedCountry && <p>Select a city or country from the sidebar</p>}
      </div>
    </Layout>
  );
}
```

- [ ] **Step 4: Test with both servers running**

Terminal 1: `python -m src.library ui`
Terminal 2: `cd ui-frontend && npm run dev`

Open browser at Vite dev URL. Verify sidebar loads with countries and cities.

- [ ] **Step 5: Commit**

```bash
git add ui-frontend/src/
git commit -m "feat(library-qc): add Layout and Sidebar components with country/city hierarchy"
```

---

## Task 9: Editable table component (CityView)

**Files:**
- Create: `ui-frontend/src/components/CityView.tsx`
- Create: `ui-frontend/src/components/EditableTable.tsx`
- Create: `ui-frontend/src/components/DeleteModal.tsx`
- Create: `ui-frontend/src/hooks/useUndoStack.ts`

- [ ] **Step 1: Create useUndoStack hook**

`ui-frontend/src/hooks/useUndoStack.ts`:
```typescript
import { useState, useCallback } from "react";

interface UndoEntry {
  description: string;
  undo: () => void;
}

export function useUndoStack() {
  const [stack, setStack] = useState<UndoEntry[]>([]);

  const push = useCallback((entry: UndoEntry) => {
    setStack((prev) => [...prev, entry]);
  }, []);

  const undo = useCallback(() => {
    setStack((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      last.undo();
      return prev.slice(0, -1);
    });
  }, []);

  const clear = useCallback(() => setStack([]), []);

  return { canUndo: stack.length > 0, undo, push, clear, count: stack.length };
}
```

- [ ] **Step 2: Create DeleteModal component**

`ui-frontend/src/components/DeleteModal.tsx`:
```typescript
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
```

- [ ] **Step 3: Create EditableTable component**

`ui-frontend/src/components/EditableTable.tsx`:
```typescript
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
                          const val = col.key === "cuisine_type" || col.key === "must_try_dishes"
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
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget({ index: rowIdx, name: row.name || "item" }); }}
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
```

- [ ] **Step 4: Create CityView component**

`ui-frontend/src/components/CityView.tsx`:
```typescript
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { EditableTable } from "./EditableTable";
import { useUndoStack } from "../hooks/useUndoStack";
import { CityData } from "../types";

const CATEGORIES = [
  { key: "restaurants", label: "Restaurants" },
  { key: "attractions", label: "Attractions" },
  { key: "hotels", label: "Hotels" },
  { key: "local_dishes", label: "Local Dishes" },
  { key: "souvenirs", label: "Souvenirs" },
];

const RESTAURANT_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "cuisine_type", label: "Cuisine", type: "text" as const },
  { key: "hours", label: "Hours", type: "text" as const },
  { key: "price_range", label: "Price Range", type: "text" as const },
  { key: "vegetarian_friendly", label: "Veg Friendly", type: "checkbox" as const },
  { key: "pure_vegetarian", label: "Pure Veg", type: "checkbox" as const },
  { key: "must_try_dishes", label: "Must-Try Dishes", type: "text" as const },
  { key: "best_for", label: "Best For", type: "tags" as const, tagOptions: ["casual", "romantic", "elegant", "family", "wine", "business"] },
];

const ATTRACTION_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "description", label: "Description", type: "text" as const },
  { key: "hours", label: "Hours", type: "text" as const },
  { key: "entry_fee", label: "Entry Fee", type: "text" as const },
  { key: "recommended_duration", label: "Duration", type: "text" as const },
];

function getColumns(category: string) {
  if (category === "restaurants") return RESTAURANT_COLUMNS;
  if (category === "attractions") return ATTRACTION_COLUMNS;
  return [{ key: "name", label: "Name", type: "text" as const }];
}

interface CityViewProps {
  cityName: string;
  onRefreshTree: () => void;
}

export function CityView({ cityName, onRefreshTree }: CityViewProps) {
  const [data, setData] = useState<CityData | null>(null);
  const [activeTab, setActiveTab] = useState("restaurants");
  const [unsavedChanges, setUnsavedChanges] = useState(0);
  const undo = useUndoStack();

  useEffect(() => {
    api.getCity(cityName).then((d) => { setData(d as CityData); setUnsavedChanges(0); undo.clear(); });
  }, [cityName]);

  if (!data) return <div className="text-slate-400 py-10 text-center">Loading...</div>;

  const handleDataChange = (category: string, newItems: any[]) => {
    const prev = [...(data as any)[category]];
    undo.push({ description: `Edit ${category}`, undo: () => setData((d) => d ? { ...d, [category]: prev } : d) });
    setData({ ...data, [category]: newItems });
    setUnsavedChanges((n) => n + 1);
  };

  const handleDelete = async (category: string, index: number, reason: string) => {
    const item = (data as any)[category][index];
    const prev = [...(data as any)[category]];
    await api.deleteItem(cityName, category, index, reason, "marina");
    const newItems = prev.filter((_, i) => i !== index);
    undo.push({ description: `Delete ${item.name}`, undo: () => setData((d) => d ? { ...d, [category]: prev } : d) });
    setData({ ...data, [category]: newItems });
  };

  const handleSave = async () => {
    await api.saveCity(cityName, data);
    setUnsavedChanges(0);
    onRefreshTree();
  };

  const handleMarkReviewed = async () => {
    await api.reviewCity(cityName, "marina");
    onRefreshTree();
  };

  return (
    <div>
      <div className="flex items-center gap-4 mb-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{cityName}</h1>
          <p className="text-sm text-slate-500">
            {data.restaurants.length} restaurants · {data.attractions.length} attractions
          </p>
        </div>
        <button onClick={handleMarkReviewed} className="ml-auto px-4 py-2 text-sm font-medium text-green-800 bg-green-50 border border-green-300 rounded-md hover:bg-green-100">
          ✓ Mark as Reviewed
        </button>
      </div>

      {/* Category tabs */}
      <div className="flex gap-0.5 border-b-2 border-slate-200 mb-4">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setActiveTab(cat.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-[2px] ${
              activeTab === cat.key ? "text-blue-600 border-blue-600" : "text-slate-500 border-transparent hover:text-slate-700"
            }`}
          >
            {cat.label} <span className={`ml-1 text-xs px-1.5 py-0.5 rounded-full ${activeTab === cat.key ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"}`}>{(data as any)[cat.key]?.length || 0}</span>
          </button>
        ))}
      </div>

      {/* Table area */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="flex items-center gap-3 mb-4">
          <button className="px-4 py-2 text-sm font-medium border border-slate-200 rounded-md hover:bg-slate-50">
            + Add {CATEGORIES.find((c) => c.key === activeTab)?.label.slice(0, -1)}
          </button>
          <button onClick={undo.undo} disabled={!undo.canUndo} className="px-4 py-2 text-sm font-medium border border-blue-300 text-blue-600 rounded-md hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed">
            ↩ Undo
          </button>
          <span className="flex-1" />
          {unsavedChanges > 0 && <span className="text-sm text-slate-500">{unsavedChanges} unsaved changes</span>}
          <button onClick={handleSave} className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700">
            Save
          </button>
        </div>

        <EditableTable
          columns={getColumns(activeTab)}
          data={(data as any)[activeTab] || []}
          onDataChange={(newData) => handleDataChange(activeTab, newData)}
          onDelete={(index, reason) => handleDelete(activeTab, index, reason)}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire CityView into App.tsx**

Update `App.tsx` to render `<CityView cityName={selectedCity} />` when a city is selected.

- [ ] **Step 6: Test end-to-end**

Run both servers. Click a city in sidebar → verify restaurant table loads with editable rows. Click a row → verify fields become editable. Test save button.

- [ ] **Step 7: Commit**

```bash
git add ui-frontend/src/
git commit -m "feat(library-qc): add CityView with editable table, delete modal, undo"
```

---

## Task 10: CountryView and SweepMode components

**Files:**
- Create: `ui-frontend/src/components/CountryView.tsx`
- Create: `ui-frontend/src/components/SweepMode.tsx`
- Modify: `ui-frontend/src/App.tsx`

- [ ] **Step 1: Create CountryView component**

`ui-frontend/src/components/CountryView.tsx`:
```typescript
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { EditableTable } from "./EditableTable";
import { useUndoStack } from "../hooks/useUndoStack";

const COUNTRY_CATEGORIES = [
  { key: "connectivity_tips", label: "Connectivity" },
  { key: "transport_options", label: "Transport" },
  { key: "phrases", label: "Phrases" },
  { key: "safety_tips", label: "Safety Tips" },
  { key: "health_tips", label: "Health" },
  { key: "emergency_contacts", label: "Emergency" },
];

const TIP_COLUMNS = [
  { key: "tip", label: "Tip", type: "text" as const },
];

const PHRASE_COLUMNS = [
  { key: "english", label: "English", type: "text" as const },
  { key: "local", label: "Local", type: "text" as const },
  { key: "category", label: "Category", type: "text" as const },
];

const EMERGENCY_COLUMNS = [
  { key: "service", label: "Service", type: "text" as const },
  { key: "number", label: "Number", type: "text" as const },
  { key: "notes", label: "Notes", type: "text" as const },
];

function getCountryColumns(category: string) {
  if (category === "phrases") return PHRASE_COLUMNS;
  if (category === "emergency_contacts") return EMERGENCY_COLUMNS;
  return TIP_COLUMNS;
}

interface CountryViewProps {
  countryName: string;
  onRefreshTree: () => void;
}

export function CountryView({ countryName, onRefreshTree }: CountryViewProps) {
  const [data, setData] = useState<Record<string, any[]> | null>(null);
  const [activeTab, setActiveTab] = useState("connectivity_tips");
  const [unsavedChanges, setUnsavedChanges] = useState(0);
  const undo = useUndoStack();

  useEffect(() => {
    api.getCountry(countryName).then((d) => { setData(d as Record<string, any[]>); setUnsavedChanges(0); undo.clear(); });
  }, [countryName]);

  if (!data) return <div className="text-slate-400 py-10 text-center">Loading...</div>;

  const handleDataChange = (category: string, newItems: any[]) => {
    const prev = [...(data[category] || [])];
    undo.push({ description: `Edit ${category}`, undo: () => setData((d) => d ? { ...d, [category]: prev } : d) });
    setData({ ...data, [category]: newItems });
    setUnsavedChanges((n) => n + 1);
  };

  const handleSave = async () => {
    await api.saveCountry(countryName, data);
    setUnsavedChanges(0);
    onRefreshTree();
  };

  const handleMarkReviewed = async () => {
    await api.reviewCountry(countryName, "marina");
    onRefreshTree();
  };

  return (
    <div>
      <div className="flex items-center gap-4 mb-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{countryName} <span className="text-sm font-medium bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full ml-2">Country</span></h1>
          <p className="text-sm text-slate-500">Country-level data shared across all cities</p>
        </div>
        <button onClick={handleMarkReviewed} className="ml-auto px-4 py-2 text-sm font-medium text-green-800 bg-green-50 border border-green-300 rounded-md hover:bg-green-100">
          ✓ Mark as Reviewed
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 mb-4 text-sm text-blue-700">
        ℹ️ Country-level data applies to all cities in {countryName}. City-specific data is edited within each city.
      </div>

      <div className="flex gap-0.5 border-b-2 border-slate-200 mb-4">
        {COUNTRY_CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setActiveTab(cat.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-[2px] ${
              activeTab === cat.key ? "text-blue-600 border-blue-600" : "text-slate-500 border-transparent hover:text-slate-700"
            }`}
          >
            {cat.label} <span className={`ml-1 text-xs px-1.5 py-0.5 rounded-full ${activeTab === cat.key ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"}`}>{(data[cat.key] || []).length}</span>
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="flex items-center gap-3 mb-4">
          <button className="px-4 py-2 text-sm font-medium border border-slate-200 rounded-md hover:bg-slate-50">+ Add</button>
          <button onClick={undo.undo} disabled={!undo.canUndo} className="px-4 py-2 text-sm font-medium border border-blue-300 text-blue-600 rounded-md hover:bg-blue-50 disabled:opacity-40">↩ Undo</button>
          <span className="flex-1" />
          {unsavedChanges > 0 && <span className="text-sm text-slate-500">{unsavedChanges} unsaved changes</span>}
          <button onClick={handleSave} className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700">Save</button>
        </div>
        <EditableTable
          columns={getCountryColumns(activeTab)}
          data={data[activeTab] || []}
          onDataChange={(newData) => handleDataChange(activeTab, newData)}
          onDelete={() => {}}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create SweepMode component**

`ui-frontend/src/components/SweepMode.tsx`:
```typescript
import { useState } from "react";
import { api } from "../api/client";
import { SweepResult } from "../types";

const SWEEP_CATEGORIES = ["restaurants", "attractions", "hotels", "local_dishes", "transport_options"];
const SWEEP_FIELDS: Record<string, string[]> = {
  restaurants: ["vegetarian_friendly", "pure_vegetarian", "hours", "price_range", "cuisine_type", "must_try_dishes", "best_for"],
  attractions: ["hours", "entry_fee", "recommended_duration", "description"],
  hotels: ["name"],
  local_dishes: ["name", "description"],
  transport_options: ["mode", "description"],
};
const FILTERS = ["all", "missing", "unchecked", "checked"];

export function SweepMode() {
  const [category, setCategory] = useState("restaurants");
  const [field, setField] = useState("vegetarian_friendly");
  const [filter, setFilter] = useState("all");
  const [result, setResult] = useState<SweepResult | null>(null);
  const [edits, setEdits] = useState<Map<string, any>>(new Map());

  const runSweep = async () => {
    const data = await api.getSweep(category, field, filter);
    setResult(data as SweepResult);
    setEdits(new Map());
  };

  const handleFieldEdit = (city: string, index: number, value: any) => {
    const key = `${city}:${index}`;
    setEdits((prev) => new Map(prev).set(key, { city, index, category, field, value }));
  };

  const handleSaveAll = async () => {
    const editList = Array.from(edits.values());
    await api.saveSweep(editList);
    setEdits(new Map());
    runSweep(); // refresh
  };

  // Group items by city
  const grouped = (result?.items || []).reduce<Record<string, typeof result.items>>((acc, item) => {
    if (!acc[item.city]) acc[item.city] = [];
    acc[item.city].push(item);
    return acc;
  }, {});

  return (
    <div>
      <div className="flex items-center gap-4 mb-5">
        <h1 className="text-xl font-bold text-slate-900">Sweep Mode</h1>
        <span className="bg-blue-100 text-blue-700 text-xs font-semibold px-3 py-1 rounded-full">SWEEP MODE</span>
      </div>

      {/* Controls */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-4 flex flex-wrap gap-4 items-end shadow-sm">
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Category</label>
          <select value={category} onChange={(e) => { setCategory(e.target.value); setField(SWEEP_FIELDS[e.target.value]?.[0] || ""); }} className="px-3 py-2 border border-slate-200 rounded-md text-sm">
            {SWEEP_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Field</label>
          <select value={field} onChange={(e) => setField(e.target.value)} className="px-3 py-2 border border-slate-200 rounded-md text-sm">
            {(SWEEP_FIELDS[category] || []).map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Filter</label>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="px-3 py-2 border border-slate-200 rounded-md text-sm">
            {FILTERS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <button onClick={runSweep} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700">Run Sweep</button>
        <span className="flex-1" />
        {edits.size > 0 && <span className="text-sm text-slate-500">{edits.size} changes</span>}
        {edits.size > 0 && <button onClick={handleSaveAll} className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700">Save All</button>}
      </div>

      {/* Stats */}
      {result && (
        <div className="bg-slate-100 rounded-md px-4 py-2 mb-4 text-sm text-slate-600 flex gap-4">
          <span><strong>{result.total}</strong> items</span>
          <span><strong>{Object.keys(grouped).length}</strong> cities</span>
        </div>
      )}

      {/* Results grouped by city */}
      {result && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          {Object.entries(grouped).map(([city, items]) => (
            <div key={city}>
              <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 font-semibold text-sm text-blue-600">
                ▾ {city} ({items.length})
              </div>
              {items.map((item) => (
                <div key={`${item.city}:${item.index}`} className="px-4 py-3 border-b border-slate-100 flex items-center gap-4 text-sm">
                  <span className="w-48 font-medium text-slate-700">{item.item.name}</span>
                  {(field === "vegetarian_friendly" || field === "pure_vegetarian") ? (
                    <input
                      type="checkbox"
                      checked={edits.has(`${item.city}:${item.index}`) ? edits.get(`${item.city}:${item.index}`).value : !!item.item[field]}
                      onChange={(e) => handleFieldEdit(item.city, item.index, e.target.checked)}
                      className="w-[18px] h-[18px] accent-blue-500"
                    />
                  ) : (
                    <input
                      type="text"
                      defaultValue={Array.isArray(item.item[field]) ? item.item[field].join(", ") : (item.item[field] ?? "")}
                      onBlur={(e) => handleFieldEdit(item.city, item.index, e.target.value)}
                      className="flex-1 px-2 py-1 border border-slate-200 rounded text-sm focus:outline-none focus:border-blue-400"
                    />
                  )}
                  <span className="text-xs text-slate-400 w-48 truncate">{item.item.must_try_dishes?.join(", ") || item.item.description || ""}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Update App.tsx to wire all views**

Update `App.tsx` to import and render `CityView`, `CountryView`, and `SweepMode` based on current selection and mode.

- [ ] **Step 4: Test all views end-to-end**

Verify:
- City view loads and edits save
- Country view loads country-level data
- Sweep mode runs queries and saves bulk edits

- [ ] **Step 5: Commit**

```bash
git add ui-frontend/src/
git commit -m "feat(library-qc): add CountryView and SweepMode components"
```

---

## Task 11: Data model update and library builder integration

**Files:**
- Modify: `src/common/models.py`
- Modify: `src/library/builder.py` (review status reset on rebuild)

- [ ] **Step 1: Add pure_vegetarian to Restaurant model**

In `src/common/models.py`, in the `Restaurant` class:
```python
class Restaurant(BaseModel):
    """A restaurant from the library or curated."""

    name: str
    location: str
    cuisine_type: list[str] = Field(default_factory=list)
    price_range: Optional[str] = None
    ambience: Optional[str] = None
    must_try_dishes: list[str] = Field(default_factory=list)
    hours: Optional[str] = None
    google_maps_link: Optional[str] = None
    best_for: list[str] = Field(default_factory=list)
    vegetarian_friendly: bool = False
    pure_vegetarian: bool = False  # Entire restaurant is vegetarian (no meat/fish served)
    is_curated: bool = False
    source_file: Optional[str] = None
```

- [ ] **Step 2: Reset review status on library rebuild**

In `src/library/builder.py`, at the end of `build_database()` after saving shards, add logic to reset review status for affected cities:

```python
# Reset review status for cities that were just rebuilt
index_path = output_path / "_index.json"
if index_path.exists():
    with open(index_path, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    review_status = index_data.get("_review_status", {})
    for city in affected_cities:
        if city in review_status:
            review_status[city] = {"status": "pending"}
    index_data["_review_status"] = review_status
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 3: Commit**

```bash
git add src/common/models.py src/library/builder.py
git commit -m "feat(library-qc): add pure_vegetarian field, reset review status on rebuild"
```

---

## Task 12: Static file serving and production build

**Files:**
- Modify: `src/library/ui/__init__.py` (serve static frontend in production)
- Modify: `src/library/__main__.py` (build command for frontend)

- [ ] **Step 1: Add static file serving to FastAPI**

Update `src/library/ui/__init__.py` to serve the built frontend:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path


def create_app(db_path: str = "library_db") -> FastAPI:
    app = FastAPI(title="Library QC", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.db_path = db_path

    from .api import tree, city, country, review, sweep, audit
    app.include_router(tree.router, prefix="/api")
    app.include_router(city.router, prefix="/api")
    app.include_router(country.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(sweep.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")

    # Serve built frontend if it exists
    dist_path = Path(__file__).parent.parent.parent.parent / "ui-frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")

    return app
```

- [ ] **Step 2: Build and verify production mode**

```bash
cd ui-frontend && npm run build
cd ..
python -m src.library ui
# Open http://127.0.0.1:8000 — should serve the React app with working API
```

- [ ] **Step 3: Add ui-frontend/node_modules to .gitignore**

```
# Frontend
ui-frontend/node_modules/
ui-frontend/dist/
```

- [ ] **Step 4: Commit**

```bash
git add src/library/ui/__init__.py .gitignore ui-frontend/
git commit -m "feat(library-qc): add static file serving for production frontend build"
```

---

## Verification

After all tasks are complete:

1. `python -m src.library ui` — starts server at http://127.0.0.1:8000
2. Sidebar shows country/city hierarchy with review status dots
3. Click a city → editable restaurant table loads
4. Edit a field → unsaved changes counter increments → Save writes to JSON
5. Click trash → delete modal asks for reason → item removed + audit logged
6. Click "Mark as Reviewed" → status dot turns green
7. Click a country → shows connectivity/phrases/safety data
8. Switch to Sweep Mode → pick restaurants + vegetarian_friendly + unchecked → see cross-city results
9. `library_db/_audit.json` contains deletion entries
10. `library_db/_index.json` contains `_review_status` entries
11. Re-running `python -m src.library build` resets affected cities to pending
