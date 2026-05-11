# Design: src/ Directory Reorganization

## Problem

The current `src/` is a flat directory mixing two independent concerns:
1. **Library management** — building and maintaining the restaurant/destination database
2. **AIG generation** — producing personalized travel guides from client itineraries

These share some utilities but operate independently, at different times, by potentially different users. The flat structure makes it hard to reason about, and the single `cli.py` handling both creates coupling. The codebase needs to support future deployment as AWS Lambda functions with a web UI.

## Design

### Target Structure

```
src/
  common/
    __init__.py
    ai_provider.py      — unified AI client (OpenAI-compatible)
    models.py           — shared Pydantic models
    maps.py             — Google Maps URL builder

  library/
    __init__.py
    __main__.py         — CLI: python -m src.library <cmd>
    builder.py          — builds library_db from aig-library/ folders
    ingester.py         — classifies & stages new AIGs into library
    qc.py              — library quality checks & verification

  aig/
    __init__.py
    __main__.py         — CLI: python -m src.aig <cmd>
    parser.py           — parses itinerary PDF + booking/flight docs
    validator.py        — found/missing check + go/abort gate
    generator.py        — orchestrator: calls section modules in order
    sections/
      __init__.py
      cover.py
      table_of_contents.py
      client_info.py
      itinerary_day.py
      places_around_stay.py
      shopping.py
      local_dishes.py
      getting_around.py
      cultural_etiquette.py
      packing_list.py
      connectivity.py
      safety_emergency.py
      health.py
      thank_you.py
```

### File Migration

| Current | Destination | Action |
|---|---|---|
| `src/cli.py` | — | Delete (replaced by two `__main__.py`) |
| `src/ai_provider.py` | `src/common/ai_provider.py` | Move |
| `src/models.py` | `src/common/models.py` | Move |
| `src/maps.py` | `src/common/maps.py` | Move |
| `src/library/builder.py` | `src/library/builder.py` | Stay (update imports) |
| `src/library/ingester.py` | `src/library/ingester.py` | Stay (update imports) |
| `src/library/qc.py` | `src/library/qc.py` | Stay (update imports) |
| `src/library/__init__.py` | `src/library/__init__.py` | Update imports |
| `src/pdf_parser.py` | `src/aig/parser.py` | Move |
| `src/ai_processor.py` | `src/aig/ai_processor.py` | Move |
| `src/user_input.py` | — | Delete (replaced by validator.py) |
| `src/generator.py` | — | Delete (rebuild from scratch per-section) |
| `src/qc.py` | — | Delete (generation QC rebuilds per-section) |

### CLI Design

**Library** (`python -m src.library`):
- `build [--force] [--library PATH] [--workers N]` — full library rebuild
- `ingest` — classify and stage new AIGs from input/
- `verify` — run quality checks on library_db
- `stats` — show DB statistics
- `find "city1, city2"` — test city→folder matching
- `clean` — remove orphaned entries

**AIG** (`python -m src.aig`):
- `generate <input_dir> [--output PATH] [--library PATH]` — full generation pipeline
- `parse <input_dir>` — parse-only, show found/missing summary

### AIG Generation Flow

```
input_dir/
  ├── itinerary.pdf
  ├── bookings.pdf (optional)
  └── flights.pdf (optional)

→ parser.py extracts structured data from all input files
→ validator.py presents FOUND / MISSING summary
→ user confirms "go" or "abort" (in CLI; in Lambda, UI handles this)
→ generator.py calls each section module in sequence
→ each section returns docx elements
→ generator.py assembles final .docx
```

### Section Module Contract

Each section module exports:
```python
def build(context: AIGContext) -> list[DocxElement]:
    """Generate this section's document elements."""
```

`AIGContext` dataclass holds: parsed itinerary, food preferences, restaurant data, library database handle, AI client, output settings.

### Scope of This Change

**In scope (structural reorganization only):**
- Create directory structure
- Move existing files to new locations
- Update all import paths
- Write library `__main__.py` (mirrors current CLI commands)
- Write AIG `__main__.py` (stub — `generate` and `parse` commands exist but section logic is placeholder)
- Delete old `cli.py`, `generator.py`, `user_input.py`, `qc.py`
- Update CLAUDE.md with new commands

**Out of scope (future sessions):**
- Implementing AIG section modules (will be built one at a time)
- AWS Lambda handlers
- Web UI
- S3 integration
- Validator logic (beyond basic stub)

### Verification

After reorganization:
1. `python -m src.library build --help` — should show usage
2. `python -m src.library stats --library aig-library` — should show DB stats (proves library code still works)
3. `python -m src.aig generate --help` — should show usage
4. `python -m src.aig parse --help` — should show usage
5. No import errors when importing any module
