# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BVBMGuide is a Python CLI tool that generates All Inclusive Guides (AIGs) — personalized 30-40 page travel documents for clients of "Bon Voyage by Marina". It takes an itinerary PDF as input and produces a formatted Word document with restaurant recommendations, logistics, and destination-specific content.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Generate an AIG from an itinerary PDF
python -m src.cli generate <itinerary_pdf> [--library aig-library] [--output output.docx]

# Parse only (no full guide generation)
python -m src.cli parse <itinerary_pdf>

# List restaurants for a destination from the library
python -m src.cli list_restaurants <destination> [--library aig-library]

# Build/rebuild the restaurant JSON database from library files
python -m src.cli build_library [--library aig-library]

# View library statistics
python -m src.cli library_stats [--library aig-library]
```

No test suite exists. No lint/format tooling is configured.

## Environment Configuration

Requires a `.env` file with:
- `AI_API_KEY` — Anthropic or OpenAI API key
- `AI_BASE_URL` — API endpoint (supports any OpenAI-compatible endpoint)
- `AI_MODEL` — model name (e.g., `claude-opus-4-5`)
- `GOOGLE_MAPS_API_KEY` — for geocoding/proximity calculations

## Architecture: Processing Pipeline

The core flow is a sequential pipeline in `src/`:

```
PDF Input → pdf_parser.py → user_input.py → ai_processor.py → library_builder.py → aig_generator.py → .docx Output
```

1. **`pdf_parser.py`** — Extracts structured data (destination, client name, days, activities) from the itinerary PDF using PyMuPDF
2. **`user_input.py`** — Collects interactive input (hotel, food preferences, dates) via `rich` terminal UI
3. **`ai_processor.py`** — Uses LLM to parse free-text food preferences into structured JSON (`FoodPreferences` model) and generate activity descriptions/supplementary content
4. **`library_builder.py`** — Builds and queries `library_db.json`, the indexed restaurant database derived from the AIG library; `LibraryDatabase` is used at runtime to look up restaurants by destination
5. **`aig_generator.py`** — Assembles the final `.docx` with day sections, restaurant recommendations (2 options per meal), packing lists, cultural notes, etc.

Supporting modules:
- **`ai_provider.py`** — Unified client wrapping `openai.OpenAI` to support both Anthropic and OpenAI endpoints
- **`models.py`** — Pydantic v2 models: `ItineraryData`, `UserInputs`, `FoodPreferences`, `Restaurant`, `AIGDocument`

## Data: The AIG Library

`aig-library/` contains 91 reference guides (DOCX/PDF) organized in destination folders. This is both the source of restaurant data and the style reference for output documents. `library_db.json` (inside `aig-library/`) is the pre-indexed version — rebuild it with `build_library` after adding new guides.

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
- `LIBRARY_INVENTORY.md` — Catalog of all 91 reference AIGs with destinations
