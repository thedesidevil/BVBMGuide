# BVBMGuide

AI-powered All Inclusive Guide (AIG) generation system for **Bon Voyage by Marina**.

## Overview

BVBMGuide is a Python CLI + web UI tool that generates personalized 30–40 page travel documents (AIGs) for clients. It takes a client itinerary PDF as input and produces a formatted Word document with restaurant recommendations, logistics, and destination-specific content drawn from a curated reference library.

## Repository Structure

```
BVBMGuide/
├── aig-library/          # Reference AIGs organized by destination folder
├── library_db/           # Sharded JSON database (one file per destination city)
├── input/                # Place letterhead DOCX and hotel comparison XLSXs here
├── src/
│   ├── common/           # Shared utilities (AI provider, Pydantic models, Maps)
│   ├── library/          # Library DB management + web UI
│   │   └── ui/           # FastAPI server + React frontend
│   ├── hotel_options/    # Hotel comparison document generator
│   └── aig/              # AIG generation (parser, sections, validator)
├── docs/                 # Specs, QC checklists, requirements
└── ui-frontend/          # React + Vite frontend source
```

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in AI_API_KEY, AI_BASE_URL, AI_MODEL, GOOGLE_MAPS_API_KEY
```

### Library Web UI

```bash
python -m src.library ui --port 8765
# Open http://localhost:8765
```

The UI provides four tabs:

| Tab | Purpose |
|-----|---------|
| **Library** | Browse and edit the destination database (restaurants, attractions, hotels, …) |
| **Ingest** | Upload new reference AIGs, classify them, extract data, persist to the library |
| **Verify** | QC-check a generated AIG against 12 automated rules + AI narrative |
| **Hotel Options** | Parse a hotel comparison XLSX and generate a formatted client-facing Word doc |

### Library CLI

```bash
# Build the database from aig-library/ (run once, or after adding new files)
python -m src.library build --force

# Ingest new reference AIGs
python -m src.library ingest --input <folder>

# View library statistics
python -m src.library stats

# Find which folders cover specific cities
python -m src.library find "Amsterdam, Florence, Rome"

# Run structural QC checks
python -m src.library qc [--verify-sources] [--spot-check]

# Inspect a single AIG file (re-extract without modifying DB)
python -m src.library inspect <file.pdf> [--field restaurants]
```

### AIG Generation CLI

```bash
# Parse an itinerary PDF and show found/missing summary
python -m src.aig parse <input_dir_or_pdf> [--days]

# Generate an All Inclusive Guide
python -m src.aig generate <input_dir_or_pdf> [--db library_db] [--output output.docx]
```

## Environment Configuration

Create a `.env` file at the project root:

```
AI_API_KEY=<your Anthropic or OpenAI-compatible key>
AI_BASE_URL=<API endpoint>
AI_MODEL=<model name, e.g. claude-opus-4-5>
GOOGLE_MAPS_API_KEY=<your Google Maps key>
LETTERHEAD_PATH=input/BVBM Company Letterhead.docx   # optional, defaults to this path
```

## Hotel Options Generator

The **Hotel Options** tab accepts a structured Excel workbook with hotel comparison data and produces a branded Word document for the client.

**Excel format expected:**
- Cell A1: requirements summary (e.g. "2 Adults, Refundable with Breakfast")
- Section headers like `London (Jun 28 – Jul 4)` for date extraction
- PLAN A / PLAN B / … headers grouping hotel rows
- Columns: hotel name, category, room type, cancellation policy, meal plan, online price, B2B price

**What the generator does:**
1. Parses all plans and hotels from the workbook
2. Resolves property codes via a persisted code dictionary
3. Looks up each hotel on Google Places to verify existence and get Maps links
4. Enriches each hotel with AI-written descriptions and photos
5. Builds a letterhead-based DOCX with pricing, savings, and hotel cards per plan

## What is an AIG?

An All Inclusive Guide is a 30–40 page travel document covering:
- Day-by-day itinerary with restaurant recommendations (min. 3 per day)
- Important places, souvenir shopping, must-try local dishes
- Getting around, cultural etiquette, local phrases
- Packing list, mobile connectivity, safety & emergency contacts, health guidance

See `docs/AIG_STRUCTURE.md` for the exact section order and formatting conventions, and `docs/AIG_QC_CHECK.md` for the generation quality checklist.

## Documentation

| Document | Description |
|----------|-------------|
| `docs/REQUIREMENTS.md` | Full functional & technical requirements |
| `docs/AIG_STRUCTURE.md` | Output document format and section conventions |
| `docs/AIG_QC_CHECK.md` | QC checklist for every generated AIG |
| `docs/LIBRARY_INVENTORY.md` | Catalog of reference AIGs by destination |
| `docs/CUSTOMGPT_INSTRUCTIONS.md` | Original GPT system prompt this tool replaces |

---

*Bon Voyage by Marina — Pune, India*
