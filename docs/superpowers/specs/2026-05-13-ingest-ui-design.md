# Ingest UI — Design Spec

A 3-step wizard inside the existing Library QC UI for uploading, classifying, and extracting data from new AIG documents into the library database.

## Problem

Adding new AIGs to the library currently requires CLI commands (`python -m src.library ingest` + `python -m src.library build`). There's no visual feedback on classification results, no easy way to correct AI mistakes before data lands in the database, and no dry-run preview of extraction results.

## Solution

Add an "Ingest" tab to the Library QC UI. A linear wizard guides the user through upload, AI classification with manual override, and AI extraction with editable preview — only persisting after explicit human approval.

---

## Architecture

```
Browser (React — Ingest tab)
    ↕ REST API (JSON + multipart upload)
Python backend (FastAPI)
    ↕ reads/writes
library_db/_staging/{session_id}/    (ephemeral upload staging)
aig-library/{country}/               (final source file destination)
library_db/                          (data merge target)
```

All ingest operations are scoped to a **session** (UUID). Staging is cleaned up after persist or abandoned after 24 hours.

---

## Flow & State Machine

```
Upload → Classify → Extract & Persist
```

### Per-file states

| State | Meaning |
|-------|---------|
| `uploaded` | File received, sitting in staging |
| `classified` | AI assigned a folder (user can override) |
| `extracted` | Dry-run complete, data shown for review |
| `excluded` | User marked this file to skip |
| `persisted` | Data merged into library_db, source moved |

### Navigation rules

- Cannot advance to Classify until at least one file is uploaded
- Cannot advance to Extract until all non-excluded files have a confirmed classification
- Can go back to Classify (resets extraction for affected files)
- "Persist All" is one-shot — only available after extraction completes for all non-excluded files

---

## Step 1: Upload

### UI

- Large dashed drop zone: "Drop files here or click to browse"
- Accepts: `.docx`, `.pdf`, `.zip`
- Zip files auto-extracted server-side; only docx/pdf within are kept
- File list below: filename, size, type badge (PDF/DOCX), remove button
- "Proceed to Classify" button (enabled when 1+ files present)

### Backend

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ingest/upload` | Multipart upload → staging. Returns `{ session_id, files }` |
| DELETE | `/api/ingest/{session_id}/files/{file_id}` | Remove a file from staging |

### Constraints

- Max 50MB per file
- No duplicate filenames in a session (re-upload replaces)
- Staging directory: `library_db/_staging/{session_id}/`

### Response shape

```json
{
  "session_id": "uuid",
  "files": [
    { "id": "uuid", "filename": "France Guide.pdf", "size": 2340000, "type": "pdf" }
  ]
}
```

---

## Step 2: Classify

### UI

- Table columns: Filename | AI Suggestion (badge) | Confidence | Override dropdown | Status
- Override dropdown: all existing `aig-library/` folders + AI suggestion (if new) + "New folder..." free-text option
- Rows start with AI suggestion pre-selected
- Manual override highlights the row (amber left border)
- "Classify All" button — triggers parallel AI classification
- Per-file "Re-classify" button
- "Exclude" checkbox per file — greyed out, skipped in extraction
- "Proceed to Extract" button (enabled when all non-excluded files have confirmed folder)

### Confidence indicator

- **High** (green dot): AI returned a folder name that exactly matches an existing `aig-library/` folder
- **Low** (red dot): AI returned a folder name that does NOT exist in `aig-library/` (i.e., it would create a new folder)

### Backend

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ingest/{session_id}/classify` | Run AI classification on all files |
| PUT | `/api/ingest/{session_id}/files/{file_id}` | Update assigned folder or excluded flag |

### Classification logic

Reuses `LibraryIngester._classify_file`:
- Extracts first 3000 chars of document text
- Sends to AI with list of existing folder names
- AI returns `{"folder": "..."}` 

### Response shape

```json
{
  "files": [
    {
      "id": "uuid",
      "filename": "France Guide.pdf",
      "suggested_folder": "France",
      "is_new_folder": false,
      "is_existing_folder": true
    }
  ]
}
```

---

## Step 3: Extract & Persist

### UI

- **Left panel:** file list with status (pending / extracting spinner / done checkmark / failed red / excluded grey)
- **Right panel:** extracted data for selected file in editable tables (reuses `EditableTable` component)
- Category tabs per file: Restaurants, Attractions, Hotels, Local Dishes, Souvenirs, Connectivity Tips, Safety Tips, Phrases, etc.
- Each file shows target city name (inferred from content by the builder)
- Per-file actions: "Exclude" button, inline field editing
- **Bottom bar:** summary stats ("8 files ready, 1 excluded — 142 restaurants, 38 attractions will be added") + "Persist All" button

### Backend

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ingest/{session_id}/extract` | Start extraction (returns immediately, processes async) |
| GET | `/api/ingest/{session_id}/extract/status` | Poll for per-file progress and results |
| PUT | `/api/ingest/{session_id}/files/{file_id}/data` | Save user edits to extracted data |
| POST | `/api/ingest/{session_id}/persist` | Commit: merge data + move files + cleanup |

### Extraction logic

Reuses `LibraryBuilder._process_file`:
- Each file processed independently
- Progress streamed per-file (frontend polls status endpoint)
- Results stored in staging until persist

### Persist action

On "Persist All":
1. For each non-excluded file with extracted data:
   - Merge items into target city shard (dedup by name within category)
   - Move source file from staging to `aig-library/{assigned_folder}/`
   - Record file in `_index.json` `_processed_files`
   - Update `_folder_coverage` if new cities discovered
2. Reset `_review_status` to "pending" for all affected cities
3. Delete staging directory for this session

### Deduplication

On merge, items are deduped by `name` (or `item` for souvenirs) within each category in the target city shard. If a restaurant with the same name already exists, it is skipped (not overwritten).

---

## API Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ingest/upload` | Upload files (multipart) |
| DELETE | `/api/ingest/{session_id}/files/{file_id}` | Remove staged file |
| POST | `/api/ingest/{session_id}/classify` | Run AI classification |
| PUT | `/api/ingest/{session_id}/files/{file_id}` | Update file assignment/exclusion |
| POST | `/api/ingest/{session_id}/extract` | Start AI extraction |
| GET | `/api/ingest/{session_id}/extract/status` | Poll extraction progress |
| PUT | `/api/ingest/{session_id}/files/{file_id}/data` | Edit extracted data |
| POST | `/api/ingest/{session_id}/persist` | Commit everything |

---

## Staging Directory Structure

```
library_db/_staging/
  {session_id}/
    meta.json              — session metadata (created_at, file list, states)
    uploads/
      {file_id}.pdf        — original uploaded file
      {file_id}.docx
    extracted/
      {file_id}.json       — extraction results (editable before persist)
```

---

## Frontend Components

```
ui-frontend/src/components/
  IngestWizard.tsx          — wizard container, step navigation, session state
  IngestUpload.tsx          — drop zone, file list, upload handling
  IngestClassify.tsx        — classification table with override dropdowns
  IngestExtract.tsx         — file list + editable preview panel
```

---

## Edge Cases

- **Zip contains nested zips:** Flatten one level only. Nested zips are ignored.
- **File extraction fails:** Mark file as "failed" with error message. User can exclude and proceed with remaining files.
- **Classification returns unknown folder:** Show it as a new suggestion with "low" confidence. User must confirm.
- **Session abandoned:** Cron-style cleanup of staging directories older than 24 hours (simple check on server start or periodic).
- **Duplicate city detection in extraction:** If a file produces data for multiple cities, each city is handled as a separate merge target.
- **Large batches:** Extraction is parallelized server-side (same worker pool as the CLI builder, default 5 concurrent).

---

## Scope Boundaries

**In scope:**
- Upload (docx/pdf/zip)
- AI classification with manual override
- AI extraction with editable dry-run preview
- Per-file exclude
- Persist with dedup merge + file move
- Session-based staging with cleanup

**Out of scope:**
- Re-extraction of files already in the library (use CLI `inspect` for that)
- Batch re-classification of existing library files
- Progress WebSocket (polling is sufficient for this use case)
- Authentication (same as rest of QC UI — local single-user tool)
