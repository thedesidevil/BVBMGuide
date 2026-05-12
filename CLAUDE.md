# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BVBMGuide is a Python CLI tool that generates All Inclusive Guides (AIGs) — personalized 30-40 page travel documents for clients of "Bon Voyage by Marina". It takes an itinerary PDF as input and produces a formatted Word document with restaurant recommendations, logistics, and destination-specific content.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# --- Library Management (python -m src.library) ---

# Build/rebuild the library database from aig-library/ files
python -m src.library build [--library aig-library] [--db library_db] [--force] [--workers 5]

# Classify and move new AIGs into the library
python -m src.library ingest --input <folder>

# View library statistics
python -m src.library stats [--db library_db]

# Find which library folders cover specific cities
python -m src.library find "Amsterdam, Florence, Rome" [--db library_db]

# Run verification checks on the library database
python -m src.library verify [--db library_db] [--library aig-library]

# Run comprehensive QC (structural + optional source verification)
python -m src.library qc [--db library_db] [--verify-sources] [--spot-check]

# Clean contaminated or duplicate entries
python -m src.library clean [--db library_db] --dump contaminated.tsv
python -m src.library clean [--db library_db] --apply contaminated.tsv

# Inspect a single AIG file (re-extract without modifying DB)
python -m src.library inspect <file.pdf> [--field restaurants]

# --- AIG Generation (python -m src.aig) ---

# Parse an itinerary and show found/missing summary
python -m src.aig parse <input_dir_or_pdf> [--days]

# Generate an All Inclusive Guide (section logic being built incrementally)
python -m src.aig generate <input_dir_or_pdf> [--db library_db] [--output output.docx]
```

No test suite exists. No lint/format tooling is configured.

## Environment Configuration

Requires a `.env` file with:
- `AI_API_KEY` — Anthropic or OpenAI API key
- `AI_BASE_URL` — API endpoint (supports any OpenAI-compatible endpoint)
- `AI_MODEL` — model name (e.g., `claude-opus-4-5`)
- `GOOGLE_MAPS_API_KEY` — for geocoding/proximity calculations

## Architecture

The codebase is split into three packages under `src/`:

```
src/
  common/          — shared utilities (ai_provider, models, maps)
  library/         — library database management (build, ingest, QC)
  aig/             — AIG generation (parse, validate, generate sections)
    sections/      — one module per AIG section (built incrementally)
```

### src/common/
- **`ai_provider.py`** — Unified client wrapping `openai.OpenAI` to support any OpenAI-compatible endpoint
- **`models.py`** — Pydantic v2 models: `ItineraryData`, `UserInputs`, `FoodPreferences`, `Restaurant`, `AIGDocument`
- **`maps.py`** — Google Maps search URL builder (no API key needed)

### src/library/
- **`builder.py`** — `LibraryBuilder` (AI extraction from DOCX/PDF) and `LibraryDatabase` (sharded DB reader)
- **`ingester.py`** — Classifies new AIGs into correct destination folders
- **`qc.py`** — `LibraryQC` structural checks, contamination cleanup, deduplication

### src/aig/
- **`parser.py`** — AI-first itinerary parser (regex fallback) extracting structured data from PDFs
- **`ai_processor.py`** — Food preference parsing + restaurant ranking via AI
- **`validator.py`** — Found/missing check with go/abort gate
- **`sections/`** — One module per AIG section, each exporting `build(context)` (being built incrementally)

## Data: The AIG Library

`aig-library/` contains reference guides (DOCX/PDF) organized in destination folders. `library_db/` (at project root) is the sharded database — one JSON file per destination city, plus `_index.json` with metadata and coverage index. Rebuild with `python -m src.library build --force`.

## AIG Output Requirements (from `docs/AIG_QC_CHECK.md`)

Every generated AIG must include these mandatory sections in order:
Cover Page → Table of Contents → Client Information + Trip Summary → Day-wise Itinerary → Important Places Around Your Stay → Souvenir Shopping Guide → Must-Try Local Dishes → Getting Around → Cultural Etiquette & Local Phrases → Tailored Packing List → Mobile Connectivity Guide → Safety & Emergency Contacts → Health & Vaccination Guidance → Thank You Page

Key generation rules:
- **Day header format**: `Day X: Day, Date – Title` (e.g., `Day 1: Monday, 12 Jan – Arrival in Tokyo`)
- **Restaurants per day**: minimum 3 options; lunch near attractions, dinner near hotel; must match dietary preferences; include full opening hours
- **Google Maps links**: required on every hotel, attraction, restaurant, shopping place, and essential service
- **TOC**: exclude cover page and TOC itself; use dotted lines with page numbers
- **Client info page**: itinerary summary as a table with city, dates, hotel (+ Maps link), and transport summary
- **Packing list**: season- and activity-specific, not generic
- **Title**: creative and destination-specific (e.g., *Sakura Adventures: Journey Through Japan*), never generic

## Key Documentation in `docs/`

- `REQUIREMENTS.md` — Full functional & technical requirements (authoritative spec)
- `AIG_STRUCTURE.md` — Exact output document format, section order, and formatting conventions
- `AIG_QC_CHECK.md` — Final QC checklist and quality rules for every generated AIG
- `CUSTOMGPT_INSTRUCTIONS.md` — Original GPT system prompt this tool replaces
- `INSTRUCTION_ANALYSIS.md` — Rules for restaurant selection, content generation
- `LIBRARY_INVENTORY.md` — Catalog of all reference AIGs with destinations
