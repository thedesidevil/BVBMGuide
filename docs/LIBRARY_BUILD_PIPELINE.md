# Library Build Pipeline

How `python -m src.library build` works — from raw AIG files to sharded city-level database.

## Overview

```
aig-library/ (source)     python -m src.library build      library_db/ (output, project root)
  France/              ──────────────────────────────►       _index.json
    Paris_AIG.pdf                                            Paris.json
    Nice_AIG.docx                                            Nice.json
  Italy/                                                     Florence.json
    Florence.pdf                                             Rome.json
    Rome.docx                                                Geneva.json
  ...                                                        ...
```

## Pipeline Steps

### 1. Discover Files

```
aig-library/
  ├── France/
  │     ├── Paris_AIG.pdf        ◄── rglob("*.docx", "*.pdf")
  │     └── Nice_AIG.docx            (skips failed-processing/)
  ├── Italy/
  │     ├── Florence_AIG.pdf
  │     └── Rome_AIG.docx
  └── ...
```

- Recursively finds all `.docx` and `.pdf` files in subfolders of `aig-library/`
- Skips anything under `failed-processing/`
- Checks each file against `_processed_files` index (by relative path + mtime)
- Only processes files that are new or modified since last build (unless `--force`)

### 2. Parallel AI Extraction

Runs N workers (default 5, configurable with `--workers`) concurrently.

For each file:

```
┌─────────────────────────────────────────────────────────┐
│  a) Extract text                                        │
│     .pdf  → PyMuPDF (fitz)                              │
│     .docx → python-docx                                 │
│     Truncated at 50,000 characters                      │
│                                                         │
│  b) Send to AI with extraction prompt                   │
│     max_tokens = 32,000                                 │
│     timeout = 300s                                      │
│                                                         │
│  c) Parse JSON response                                 │
│     → json.loads()                                      │
│     → _repair_truncated_json() if malformed             │
│     → _clean_entry_fees() removes "included" fees       │
└─────────────────────────────────────────────────────────┘
```

The AI extracts structured data into these fields:

| Field | Per-item key | Description |
|-------|-------------|-------------|
| `covered_cities` | — | All cities/towns the guide covers |
| `restaurants` | `city` | Name, cuisine, price, hours, area, highlights, dishes |
| `attractions` | `city` | Name, description, hours, entry fee, duration |
| `hotels` | `city` | Name, location/neighbourhood |
| `local_dishes` | `city` | Name, description, vegetarian flag, where to try |
| `phrases` | `city` | English, local translation, category |
| `safety_tips` | `cities` (list) | Tips fanned out to multiple destinations |
| `souvenirs` | `city` | Item, category, where to buy |
| `emergency_contacts` | `city` | Service, number, notes |
| `connectivity_tips` | `cities` (list) | SIM/eSIM/WiFi tips, multi-city |
| `transport_options` | `city` | Mode, description, pass, cost |
| `health_tips` | `cities` (list) | Vaccination/health tips, multi-city |

### 3. City Routing

Each extracted item is routed to a destination shard based on its `city` field:

```
Regular fields (restaurants, attractions, etc.)
  → item["city"].title() → single destination shard

Multi-city fields (safety_tips, connectivity_tips, health_tips)
  → item["cities"] list → copied to ALL listed destination shards
  → e.g. {"cities": ["France", "Switzerland"], "tip": "..."}
         routes to both France.json AND Switzerland.json

Fallback: if city is empty → uses the parent folder name as destination
```

### 4. Merge Into In-Memory Database

All extracted items accumulate in a single dictionary:

```json
{
  "version": "1.2",
  "built_at": "2026-05-08T...",
  "destinations": {
    "Paris": { "restaurants": [...], "attractions": [...], ... },
    "Florence": { ... },
    "Geneva": { ... }
  },
  "_processed_files": {
    "France/Paris_AIG.pdf": { "mtime": ..., "covered_cities": [...] }
  },
  "_folder_coverage": {
    "France": ["Bordeaux", "Lyon", "Nice", "Paris", "Versailles"]
  }
}
```

**Checkpoint**: saves to disk every 10 files to avoid data loss on crashes.

### 5. Deduplicate

For each destination, deduplicates restaurants, attractions, and local_dishes:

- **Match by**: name (case-insensitive, stripped)
- **Merge strategy**:
  - `must_try_dishes` → always **union** across all source files
  - Other fields → overwrite only if the incoming file is **newer** (by mtime)
  - `source_files` → accumulate all contributing file paths

### 6. Build Folder Coverage Index

Unions `covered_cities` from all processed files, grouped by their parent folder:

```json
"_folder_coverage": {
  "France": ["Bordeaux", "Lyon", "Nice", "Paris", "Versailles"],
  "Italy": ["Florence", "Pisa", "Rome", "Siena", "Venice"],
  "Japan": ["Kyoto", "Osaka", "Tokyo"]
}
```

Used at query time by `find_relevant_folders()` to map cities → library folders.

### 7. Save (Sharded Format)

Output goes to `library_db/` at project root (separate from the source `aig-library/`):

```
library_db/                ← project root, NOT inside aig-library/
  ├── _index.json          ← metadata, _processed_files, _folder_coverage
  ├── Paris.json           ← { restaurants, attractions, hotels, ... }
  ├── Florence.json
  ├── Geneva.json
  ├── Lauterbrunnen.json
  └── ... (one file per destination city)
```

Each city shard contains all data for that city: restaurants, attractions, hotels, local dishes, phrases, safety tips, souvenirs, emergency contacts, connectivity tips, transport options, and health tips.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Incremental builds (mtime check) | Avoids re-processing 175 files when only a few changed |
| City-level sharding | Each city loads independently; query for "Paris" doesn't load "Tokyo" |
| AI determines city routing | Source folder = country/region, but items route to specific cities within |
| Multi-city fan-out for tips | Safety/connectivity/health tips often apply to multiple cities |
| Recency-aware dedup | Newer guides have fresher hours/prices, but dish lists should accumulate |
| Checkpoint every 10 files | AI extraction is slow (~30s/file); don't lose progress on failure |
| Truncate at 50K chars | Keeps AI context manageable; most guides are under this limit |
| Repair truncated JSON | AI sometimes hits token limit mid-response; recovery avoids re-extraction |
