# Hotel Document v2.0 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the hotel accommodation proposal from a corporate Word report into a luxury travel dossier matching Bon Voyage By Marina's premium brand, including new AI-generated per-hotel content fields and a complete visual overhaul of every document section.

**Architecture:** New AI-generated fields (`positioning_statement`, `insight_text`, `perfect_for`, `things_to_know`) are added to `EnrichedHotel` and populated during `enrich_hotel()`. `generator.py` is restructured with named render functions and a new design system (forest green accent, no navy blue, wider margins, more white space), rebuilding every page section while keeping the same `build_document()` public signature.

**Tech Stack:** python-docx, httpx, Anthropic API (via existing ai_client), Google Places API (hotel photos), Pexels API (destination cover photo)

## Global Constraints

- Output format: DOCX only (no PDF conversion)
- Font: Arial throughout all body/heading text; Georgia only for cover title/subtitle
- Accent colour: Forest Green `#2D6A4F` — used ONLY for savings, recommendation badge, insight box left border
- No dark navy (`#1F497D`) anywhere in the redesigned document
- Margins: increase from `Inches(0.75)` to `Inches(1.0)` throughout
- White space: ~25–35% more than current — achieved via larger `space_before`/`space_after` on paragraphs
- All layouts must support 1–15 hotels; no hardcoded coordinates
- `build_document()` public signature stays unchanged — service layer calls it as-is
- No test suite: verification is a generated DOCX opened in macOS Preview/Word
- Emojis: leave existing emoji usage in place for now (TBD to replace with icons later)
- Image decisions: Pexels for destination cover photo (better travel photography); Google Places photos for hotel hero images
- Hero image width: `Inches(6.5)` full-width; aspect ratio preserved (never stretched)

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `src/hotel_options/models.py` | Modify | Add 4 fields to `EnrichedHotel` |
| `src/common/brand_voice.py` | Modify | Add 3 new AI prompt constants |
| `src/hotel_options/enricher.py` | Modify | `fetch_destination_photo_pexels()` + extend `enrich_hotel()` |
| `src/library/ui/services/hotel_options_service.py` | Modify | Try Pexels first for cover photo; pass `PEXELS_API_KEY` |
| `src/hotel_options/generator.py` | Rewrite | All new design system + render functions |

---

### Task 1: Extend EnrichedHotel model with new AI-generated fields

**Files:**
- Modify: `src/hotel_options/models.py`

**Interfaces:**
- Produces: `EnrichedHotel` now has `positioning_statement: str`, `insight_text: str`, `perfect_for: list[str]`, `things_to_know: list[str]`

- [ ] **Step 1: Add four new fields to `EnrichedHotel`**

Open `src/hotel_options/models.py`. Replace the `EnrichedHotel` dataclass with:

```python
@dataclass
class EnrichedHotel:
    official_name: str
    address: str
    phone: str
    rating: float
    rating_count: int
    maps_url: str
    photo_bytes: bytes | None
    description: str
    cancellation: str
    meal_type: str
    category: str
    dates: str = ""
    positioning_statement: str = ""
    insight_text: str = ""
    perfect_for: list[str] = field(default_factory=list)
    things_to_know: list[str] = field(default_factory=list)
```

Also add `field` to the import at the top:
```python
from dataclasses import dataclass, field
```

- [ ] **Step 2: Verify import works**

```bash
cd /Users/mjain/work/projects/travel/BVBMGuide && python -c "from src.hotel_options.models import EnrichedHotel; e = EnrichedHotel('n','a','p',4.5,100,'u',None,'d','c','m','cat'); print(e.positioning_statement, e.perfect_for)"
```

Expected output: ` []`

- [ ] **Step 3: Commit**

```bash
git add src/hotel_options/models.py
git commit -m "feat(hotel-redesign): add AI-generated fields to EnrichedHotel"
```

---

### Task 2: Add new AI prompts to brand_voice.py

**Files:**
- Modify: `src/common/brand_voice.py`

**Interfaces:**
- Produces: `POSITIONING_SYSTEM`, `INSIGHT_SYSTEM`, `TAGS_SYSTEM` exported from `src.common.brand_voice`

- [ ] **Step 1: Add three new prompt constants to `brand_voice.py`**

Append to the end of `src/common/brand_voice.py`:

```python

_POSITIONING_GUIDELINES = """\
Positioning Statement Guidelines
──────────────────────────────────
Write one sentence that positions this hotel for the client. Max 18 words.

It should answer: "Why did Bon Voyage By Marina select this hotel for this specific trip?"
It should feel like something a knowledgeable travel consultant would say to a client.
It must be specific — location, connectivity, value, or character — not generic.

Examples:
  "A dependable value option with excellent connectivity to Wimbledon."
  "A refined Kensington address ideal for exploring central London on foot."
  "One of Mayfair's most sought-after stays, within walking distance of Hyde Park."
  "A practical and well-rated base with direct rail links to the Wimbledon grounds."

Never use: "world-class", "luxurious experience", "perfect choice", "nestled", "boasts".
Never use recommendation language like "we recommend" or "excellent pick".
Output only the statement. No quotes. No punctuation at the end except a period.\
"""

POSITIONING_SYSTEM = f"{BVBM_BRAND_VOICE}\n\n{_POSITIONING_GUIDELINES}"


_INSIGHT_GUIDELINES = """\
Bon Voyage Insight Guidelines
───────────────────────────────
Write 2–3 sentences from the perspective of a senior travel advisor at Bon Voyage By Marina.
This is a personal note about why this hotel was selected — honest, warm, and specific.
It should feel like advice from a trusted expert, not marketing copy.

What to cover (choose 2–3 that are most relevant):
- What makes this hotel a smart choice for this particular trip
- A specific feature of the location, connectivity, or property that others overlook
- An honest observation that helps the client make a confident decision

Examples:
  "Although not the newest property in Kensington, its location and value make it one of
  our favourite recommendations for this itinerary."
  
  "The rooms are simple, but the direct rail connection makes this one of the smartest
  choices for Wimbledon. Most guests are back in central London within 20 minutes."
  
  "This is a hotel we keep coming back to — the location is genuinely hard to beat at
  this price point, and the breakfast is one of the better ones in the area."

Length: 30–55 words. Never exceed 60. Never write only one sentence.
Never use: "we recommend", "excellent choice", "perfect for", "nestled", "boasts".
Never repeat information already visible in the hotel details table.
Output only the insight text.\
"""

INSIGHT_SYSTEM = f"{BVBM_BRAND_VOICE}\n\n{_INSIGHT_GUIDELINES}"


_TAGS_GUIDELINES = """\
Hotel Tags Guidelines
──────────────────────
Generate two lists for this hotel:

1. "perfect_for" — up to 4 labels (1–3 words each) describing who this hotel suits best.
   Choose from or adapt these examples:
   Couples, Families, Business Travellers, Luxury Seekers, First-Time Visitors,
   Wimbledon Guests, Quiet Location, Excellent Value, Premium Location,
   Solo Travellers, Sports Fans, City Explorers, Budget-Conscious Travellers

2. "things_to_know" — up to 3 short, balanced bullet points about this hotel.
   These are practical, honest observations that help a client decide.
   They are NOT negative reviews, but they are not marketing either.
   Examples:
     "Rooms are compact by international standards."
     "Excellent transport links — 10 minutes to the city centre."
     "Breakfast included; gets busy after 9 AM."
     "Non-refundable rate — plan your travel dates carefully."
     "Quiet neighbourhood, a short taxi ride from main attractions."

Return ONLY valid JSON in this exact format, no other text:
{"perfect_for": ["label1", "label2"], "things_to_know": ["bullet1", "bullet2"]}\
"""

TAGS_SYSTEM = f"{BVBM_BRAND_VOICE}\n\n{_TAGS_GUIDELINES}"
```

- [ ] **Step 2: Verify import works**

```bash
cd /Users/mjain/work/projects/travel/BVBMGuide && python -c "from src.common.brand_voice import POSITIONING_SYSTEM, INSIGHT_SYSTEM, TAGS_SYSTEM; print('OK', len(POSITIONING_SYSTEM), len(INSIGHT_SYSTEM), len(TAGS_SYSTEM))"
```

Expected: `OK <number> <number> <number>` (no errors)

- [ ] **Step 3: Commit**

```bash
git add src/common/brand_voice.py
git commit -m "feat(hotel-redesign): add positioning, insight, and tags AI prompt systems"
```

---

### Task 3: Add Pexels photo fetching + extend enrich_hotel() with new AI fields

**Files:**
- Modify: `src/hotel_options/enricher.py`
- Modify: `src/library/ui/services/hotel_options_service.py`
- Modify: `.env` (add PEXELS_API_KEY)

**Interfaces:**
- Consumes: `POSITIONING_SYSTEM`, `INSIGHT_SYSTEM`, `TAGS_SYSTEM` from `src.common.brand_voice`
- Consumes: `EnrichedHotel.positioning_statement`, `insight_text`, `perfect_for`, `things_to_know` (from Task 1)
- Produces: `fetch_destination_photo_pexels(destination, pexels_api_key) -> bytes | None`
- Produces: `enrich_hotel()` returns `EnrichedHotel` with all 4 new fields populated

- [ ] **Step 1: Add Pexels fetch function to `enricher.py`**

Add this import at the top of `src/hotel_options/enricher.py`:
```python
import json as _json
```

Add these after the existing imports, before the existing `_PLACES_BASE` constant:

```python
_PEXELS_SEARCH = "https://api.pexels.com/v1/search"
```

Add this function after `fetch_destination_photo()`:

```python
def fetch_destination_photo_pexels(destination: str, pexels_api_key: str) -> bytes | None:
    """Fetch a curated travel photo for the destination from Pexels."""
    try:
        resp = httpx.get(
            _PEXELS_SEARCH,
            params={
                "query": f"{destination} travel landmark skyline",
                "per_page": 3,
                "orientation": "landscape",
            },
            headers={"Authorization": pexels_api_key},
            timeout=10,
        )
        photos = resp.json().get("photos", [])
        if not photos:
            return None
        url = photos[0]["src"]["large2x"]
        photo_resp = httpx.get(url, follow_redirects=True, timeout=15)
        return photo_resp.content if photo_resp.status_code == 200 else None
    except Exception:
        return None
```

- [ ] **Step 2: Add new AI prompts import and three new prompt templates to `enricher.py`**

Replace the import line for `HOTEL_DESCRIPTION_SYSTEM` in `enricher.py`:
```python
from src.common.brand_voice import HOTEL_DESCRIPTION_SYSTEM, POSITIONING_SYSTEM, INSIGHT_SYSTEM, TAGS_SYSTEM
```

Add these prompt templates after `_DESCRIPTION_PROMPT`:

```python
_POSITIONING_PROMPT = """\
Write a one-line positioning statement for this hotel. Max 18 words.

Hotel: {name}
Category: {category}
Address: {address}
Rating: {rating}/5 ({rating_count} reviews)
Cancellation: {cancellation}
Meal plan: {meal_type}
Destination: {destination}

Output only the statement, nothing else. No quotes."""


_INSIGHT_PROMPT = """\
Write a "Bon Voyage Insight" for this hotel — 2 to 3 sentences from a senior travel advisor's perspective.

Hotel: {name}
Category: {category}
Address: {address}
Rating: {rating}/5 ({rating_count} reviews)
Destination: {destination}

Output only the insight text, nothing else."""


_TAGS_PROMPT = """\
Generate hotel tags for this property.

Hotel: {name}
Category: {category}
Address: {address}
Rating: {rating}/5 ({rating_count} reviews)
Destination: {destination}

Return ONLY valid JSON: {{"perfect_for": [...], "things_to_know": [...]}}"""
```

- [ ] **Step 3: Extend `enrich_hotel()` to populate new fields**

In `enrich_hotel()`, after the existing `description = ai_client.complete(...)` call, add:

```python
    # Positioning statement
    positioning_statement = ai_client.complete(
        _POSITIONING_PROMPT.format(
            name=official_name, category=hotel.category, address=address,
            rating=rating, rating_count=rating_count,
            cancellation=hotel.cancellation or "Not specified",
            meal_type=hotel.meal_type or "Not specified",
            destination=destination,
        ),
        max_tokens=60,
        temperature=0.3,
        system=POSITIONING_SYSTEM,
    ).strip().strip('"')

    # Insight text
    insight_text = ai_client.complete(
        _INSIGHT_PROMPT.format(
            name=official_name, category=hotel.category, address=address,
            rating=rating, rating_count=rating_count,
            destination=destination,
        ),
        max_tokens=120,
        temperature=0.4,
        system=INSIGHT_SYSTEM,
    ).strip()

    # Tags (perfect_for + things_to_know)
    perfect_for: list[str] = []
    things_to_know: list[str] = []
    try:
        tags_raw = ai_client.complete(
            _TAGS_PROMPT.format(
                name=official_name, category=hotel.category, address=address,
                rating=rating, rating_count=rating_count,
                destination=destination,
            ),
            max_tokens=200,
            temperature=0.3,
            system=TAGS_SYSTEM,
        ).strip()
        start, end = tags_raw.find("{"), tags_raw.rfind("}") + 1
        if start >= 0 and end > start:
            tags = _json.loads(tags_raw[start:end])
            perfect_for = tags.get("perfect_for", [])[:4]
            things_to_know = tags.get("things_to_know", [])[:3]
    except Exception:
        pass
```

Then update the `return EnrichedHotel(...)` call at the end of `enrich_hotel()`:

```python
    return EnrichedHotel(
        official_name=official_name,
        address=address,
        phone=phone,
        rating=rating,
        rating_count=rating_count,
        maps_url=maps_url,
        photo_bytes=photo_bytes,
        description=description,
        cancellation=hotel.cancellation,
        meal_type=hotel.meal_type,
        category=hotel.category,
        dates=hotel.dates,
        positioning_statement=positioning_statement,
        insight_text=insight_text,
        perfect_for=perfect_for,
        things_to_know=things_to_know,
    )
```

- [ ] **Step 4: Update `hotel_options_service.py` to use Pexels for cover photo**

In `generate_doc()` in `src/library/ui/services/hotel_options_service.py`, replace:
```python
    destination_photo = _enricher.fetch_destination_photo(destination, api_key)
```

With:
```python
    pexels_key = os.getenv("PEXELS_API_KEY", "")
    destination_photo = (
        _enricher.fetch_destination_photo_pexels(destination, pexels_key)
        if pexels_key else None
    )
    if not destination_photo:
        destination_photo = _enricher.fetch_destination_photo(destination, api_key)
```

Also add `import os` to the top of `hotel_options_service.py` if not already present.

- [ ] **Step 5: Add PEXELS_API_KEY to .env**

Add this line to `.env`:
```
PEXELS_API_KEY=<your-pexels-api-key>
```

- [ ] **Step 6: Verify import chain works**

```bash
cd /Users/mjain/work/projects/travel/BVBMGuide && python -c "from src.hotel_options.enricher import fetch_destination_photo_pexels; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/hotel_options/enricher.py src/library/ui/services/hotel_options_service.py src/common/brand_voice.py
git commit -m "feat(hotel-redesign): add Pexels cover photo + positioning/insight/tags AI enrichment"
```

---

### Task 4: New design system — constants, margins, and DOCX primitives

**Files:**
- Modify: `src/hotel_options/generator.py` (design constants block + new helper functions)

**Interfaces:**
- Produces: Updated constants: `_GREEN`, `_FOREST_GREEN_HEX`, `_INSIGHT_BG`, `_CHIP_BG`, `_MARGIN`
- Produces: New helpers: `_recommendation_badge()`, `_chips_row()`, `_insight_box()`, `_area_label()`

- [ ] **Step 1: Update design constants block in `generator.py`**

Replace the entire constants block (lines 14–28) with:

```python
# ── Design constants ──────────────────────────────────────────────────────────
_CHARCOAL       = RGBColor(0x2D, 0x2D, 0x2D)
_GREY           = RGBColor(0x66, 0x66, 0x66)
_LIGHT_GREY_RGB = RGBColor(0xCC, 0xCC, 0xCC)
_GREEN          = RGBColor(0x2D, 0x6A, 0x4F)   # Forest Green — savings, badge, accent
_WHITE          = RGBColor(0xFF, 0xFF, 0xFF)
_AMBER          = RGBColor(0xC7, 0x78, 0x00)    # Keep for backward compat

_FONT = "Arial"

_LIGHT_GREY     = "F5F5F5"   # Section shading, subtle backgrounds
_ROW_ALT        = "FAFAFA"   # Alternating table rows
_RULE_COLOR     = "E0E0E0"   # Thin horizontal rules
_INSIGHT_BG     = "F8F9FA"   # Insight box background
_CHIP_BG        = "EEEEEE"   # Perfect For chip background
_FOREST_GREEN   = "2D6A4F"   # Forest Green hex (for shd elements)
_GREEN_LIGHT    = "D8F3DC"   # Light green for savings badge background

_MARGIN = Inches(1.0)        # Increased from 0.75 for more breathing room
```

- [ ] **Step 2: Update `_set_margins()` and `_configure_styles()`**

`_set_margins()` already uses `_MARGIN` — it will pick up the new value automatically.

In `_configure_styles()`, update spacing values for more white space:

```python
def _configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name  = _FONT
    normal.font.size  = Pt(11)
    normal.font.color.rgb = _CHARCOAL
    normal.paragraph_format.space_after      = Pt(10)   # was 8
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    normal.paragraph_format.line_spacing      = 1.2     # was 1.15

    title = doc.styles["Title"]
    title.font.name  = _FONT
    title.font.size  = Pt(26)
    title.font.bold  = True
    title.font.color.rgb = _CHARCOAL
    title.paragraph_format.alignment   = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(14)        # was 10

    h1 = doc.styles["Heading 1"]
    h1.font.name  = _FONT
    h1.font.size  = Pt(18)                             # was 16
    h1.font.bold  = True
    h1.font.color.rgb = _CHARCOAL
    h1.paragraph_format.space_before = Pt(0)
    h1.paragraph_format.space_after  = Pt(6)           # was 4

    h2 = doc.styles["Heading 2"]
    h2.font.name  = _FONT
    h2.font.size  = Pt(15)                             # was 14
    h2.font.bold  = True
    h2.font.color.rgb = _CHARCOAL
    h2.paragraph_format.space_before = Pt(6)           # was 4
    h2.paragraph_format.space_after  = Pt(8)           # was 6

    h3 = doc.styles["Heading 3"]
    h3.font.name   = _FONT
    h3.font.size   = Pt(12)
    h3.font.bold   = False
    h3.font.italic = True
    h3.font.color.rgb = _GREY
    h3.paragraph_format.alignment   = WD_ALIGN_PARAGRAPH.CENTER
    h3.paragraph_format.space_after = Pt(10)           # was 8
```

- [ ] **Step 3: Add new DOCX primitive — `_recommendation_badge()`**

Add this function after `_thin_rule()`:

```python
def _recommendation_badge(doc: Document, text: str = "OUR RECOMMENDATION") -> None:
    """A small forest-green shaded box with white bold text — the hotel ribbon badge."""
    table = doc.add_table(rows=1, cols=1)
    table.autofit = True
    _no_borders(table)
    cell = table.rows[0].cells[0]
    _shade_cell(cell, _FOREST_GREEN)

    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for side in ("top", "bottom"):
        m = OxmlElement(f"w:{side}")
        m.set(qn("w:w"), "40")
        m.set(qn("w:type"), "dxa")
        tcMar.append(m)
    for side in ("left", "right"):
        m = OxmlElement(f"w:{side}")
        m.set(qn("w:w"), "100")
        m.set(qn("w:type"), "dxa")
        tcMar.append(m)
    tcPr.append(tcMar)

    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(p, 0, 0)
    _body_run(p, f"  {text}  ", bold=True, size=8.5, color=_WHITE)
```

- [ ] **Step 4: Add new DOCX primitive — `_chips_row()`**

```python
def _chips_row(doc: Document, labels: list[str]) -> None:
    """Render a row of pill-shaped chips (e.g. Perfect For tags)."""
    if not labels:
        return
    table = doc.add_table(rows=1, cols=len(labels))
    table.autofit = True
    _no_borders(table)
    for i, label in enumerate(labels):
        cell = table.rows[0].cells[i]
        _shade_cell(cell, _CHIP_BG)
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), "4")
            b.set(qn("w:color"), _RULE_COLOR)
            tcBorders.append(b)
        tcPr.append(tcBorders)
        tcMar = OxmlElement("w:tcMar")
        for side in ("left", "right"):
            m = OxmlElement(f"w:{side}")
            m.set(qn("w:w"), "80")
            m.set(qn("w:type"), "dxa")
            tcMar.append(m)
        tcPr.append(tcMar)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 3, 3)
        _body_run(p, label, size=8.5, color=_CHARCOAL)
```

- [ ] **Step 5: Add new DOCX primitive — `_insight_box()`**

```python
def _insight_box(doc: Document, text: str) -> None:
    """Shaded box with a forest-green left accent border and advisory text."""
    if not text:
        return
    table = doc.add_table(rows=1, cols=1)
    _no_borders(table)
    cell = table.rows[0].cells[0]
    _shade_cell(cell, _INSIGHT_BG)

    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "16")     # 4pt thick left accent
    left.set(qn("w:color"), _FOREST_GREEN)
    tcBorders.append(left)
    tcPr.append(tcBorders)

    tcMar = OxmlElement("w:tcMar")
    for side, val in (("top", "60"), ("bottom", "60"), ("left", "120"), ("right", "80")):
        m = OxmlElement(f"w:{side}")
        m.set(qn("w:w"), val)
        m.set(qn("w:type"), "dxa")
        tcMar.append(m)
    tcPr.append(tcMar)

    p = cell.paragraphs[0]
    _spacing(p, 0, 4)
    _body_run(p, "BON VOYAGE INSIGHT", bold=True, size=8.5, color=_GREEN)

    p2 = cell.add_paragraph()
    _spacing(p2, 2, 0)
    _body_run(p2, text, size=10, color=_CHARCOAL)
```

- [ ] **Step 6: Add `_area_label()` helper**

```python
def _area_label(doc: Document, text: str) -> None:
    """Small uppercase grey label — used for destination/area above a hotel hero."""
    p = doc.add_paragraph()
    _spacing(p, 0, 4)
    _body_run(p, text.upper(), size=9, color=_GREY)
```

- [ ] **Step 7: Verify file parses cleanly**

```bash
cd /Users/mjain/work/projects/travel/BVBMGuide && python -c "import src.hotel_options.generator; print('OK')"
```

Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): update design system — forest green palette, wider margins, new primitives"
```

---

### Task 5: Redesign cover page

**Files:**
- Modify: `src/hotel_options/generator.py` — `_build_cover_page()`, `_add_trip_snapshot()`, `_add_advisor_note()`

- [ ] **Step 1: Update `_add_trip_snapshot()` — remove blue rule, increase spacing**

Replace the function body (keep the signature unchanged):

```python
def _add_trip_snapshot(doc: Document, destination: str, requirements: str,
                       stay_requirements: str = "") -> None:
    import re as _re
    req_lines  = [r.strip() for r in _re.split(r'[\n,]+', requirements) if r.strip()]
    travellers = next((l for l in req_lines if _re.search(r'\d+\s+adult', l, _re.I)), "")

    rows: list[tuple[str, str]] = [("Destination", destination)]
    if travellers:
        rows.append(("Travellers", travellers))
    if stay_requirements:
        rows.append(("Stay Requirements", stay_requirements))

    _thin_rule(doc, before=16, after=8)

    p = doc.add_paragraph()
    _spacing(p, 0, 6)
    _body_run(p, "TRIP SNAPSHOT", bold=True, size=9, color=_GREY)

    table = doc.add_table(rows=len(rows), cols=2)
    _no_borders(table)

    for i, (label, value) in enumerate(rows):
        lc = table.rows[i].cells[0]
        vc = table.rows[i].cells[1]
        lp = lc.paragraphs[0]
        _spacing(lp, 4, 4)
        _body_run(lp, label, bold=True, size=10, color=_GREY)
        vp = vc.paragraphs[0]
        _spacing(vp, 4, 4)
        _body_run(vp, value, size=10, color=_CHARCOAL)
```

- [ ] **Step 2: Update `_add_advisor_note()` — lighter branding rule**

```python
def _add_advisor_note(doc: Document, destination: str) -> None:
    p = doc.add_paragraph()
    _spacing(p, 20, 6)
    _georgia(p, "A NOTE FROM BON VOYAGE BY MARINA", size=12, bold=True)

    note = (
        f"Thank you for giving us the opportunity to assist with your "
        f"{destination} journey. "
        f"The options in this document have been carefully reviewed and shortlisted "
        f"based on your preferences, location requirements, flexibility, and overall value. "
        f"We hope this guide helps you choose the stay that is right for you."
    )
    p = doc.add_paragraph()
    _spacing(p, 4, 0)
    _body_run(p, note, size=10.5, color=_CHARCOAL)
```

- [ ] **Step 3: Update `_build_cover_page()` — larger image, cleaner layout, no blue**

Replace the full function body:

```python
def _build_cover_page(doc: Document, destination: str, client_name: str,
                      requirements: str, stay_requirements: str = "",
                      destination_photo: bytes | None = None) -> None:
    def blank(n: int = 1) -> None:
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    # 1. Hero destination image — full width, panoramic
    if destination_photo:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 0)
        p.add_run().add_picture(io.BytesIO(destination_photo), width=Inches(6.5))
    else:
        blank(5)

    blank(3)

    # 2. Title — Georgia 28pt Bold Centered
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 10)
    _georgia(p, f"{destination.upper()} ACCOMMODATION RECOMMENDATIONS",
             size=28, bold=True)

    # 3. Subtitle — Georgia 12pt Italic Centered
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 24)
    _georgia(p, "Curated by Bon Voyage By Marina", size=12, italic=True, color=_GREY)

    # 4. Personalization
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 6)
    _georgia(p, "Prepared Exclusively For", size=13, color=_GREY)

    if client_name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 0)
        _georgia(p, client_name.upper(), size=15, bold=True)

    # 5. Trip Snapshot
    _add_trip_snapshot(doc, destination, requirements, stay_requirements)

    # 6. Advisor Note — starts on its own page
    _page_break(doc)
    _add_advisor_note(doc, destination)

    # 7. Bottom branding — light grey rule, no navy
    blank(1)
    _thin_rule(doc, before=6, after=8, color=_RULE_COLOR)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 12, 6)
    _body_run(p, "Bon Voyage By Marina", bold=True, size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 4, 4)
    _body_run(p, "Bespoke Travel Planning • Premium Stays • Seamless Experiences",
              italic=True, size=11, color=_GREY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 4, 4)
    _body_run(p, "\U0001f4de +91 86000 15316 | \U0001f4f8 @bonvoyagebymarina | \U0001f310 www.bonvoyagebymarina.com",
              size=11, color=_CHARCOAL)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 4, 4)
    _body_run(p, "✈️ ", size=11, color=_CHARCOAL)
    _body_run(p, "Crafting unforgettable journeys, one trip at a time.",
              italic=True, size=11, color=_CHARCOAL)
```

- [ ] **Step 4: Smoke test — generate a document from the UI and open it**

Start the server:
```bash
cd /Users/mjain/work/projects/travel/BVBMGuide && python -m src.library
```
Upload any test XLSX file. Download the DOCX. Open it and verify:
- Cover hero image is full width
- Larger title
- No blue anywhere on page 1 or 2
- More breathing room throughout

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): redesign cover page — full-width hero, cleaner layout, no blue"
```

---

### Task 6: Redesign executive summary — dashboard with highlight cards

**Files:**
- Modify: `src/hotel_options/generator.py` — `_build_executive_summary()`, `_build_exec_summary_by_hotel()`, `_build_exec_summary_by_plan()`

- [ ] **Step 1: Add `_identify_highlights()` helper**

Add this function before `_build_executive_summary()`:

```python
def _identify_highlights(
    plans: list[Plan],
    grouped_by_sections: bool,
) -> tuple[str | None, str | None, str | None, float, float, int]:
    """
    Returns: (recommended_name, best_value_name, premium_name,
              total_savings, largest_discount_pct, total_hotel_count)
    Names are hotel names (grouped) or plan labels (plan-based).
    """
    if grouped_by_sections:
        all_hotels = [(h, h.name) for p in plans for h in p.hotels]
    else:
        all_hotels = [(h, p.label) for p in plans for h in p.hotels]

    recommended_name = None
    for h, label in all_hotels:
        if h.recommended:
            recommended_name = label
            break
    if not recommended_name and plans:
        recommended_name = all_hotels[0][1] if all_hotels else None

    best_value_name = None
    best_pct = -1.0
    for h, label in all_hotels:
        if h.discount_pct > best_pct:
            best_pct = h.discount_pct
            best_value_name = label

    premium_name = None
    max_price = -1.0
    for h, label in all_hotels:
        if h.online_price > max_price:
            max_price = h.online_price
            premium_name = label

    total_savings = sum(h.customer_discount for h, _ in all_hotels if h.customer_discount > 0)
    largest_discount = max((h.discount_pct for h, _ in all_hotels), default=0.0)
    total_count = len(all_hotels)

    return recommended_name, best_value_name, premium_name, total_savings, largest_discount, total_count
```

- [ ] **Step 2: Add `_render_highlight_cards()` helper**

```python
def _render_highlight_cards(
    doc: Document,
    plans: list[Plan],
    grouped_by_sections: bool,
    recommended_name: str | None,
    best_value_name: str | None,
    premium_name: str | None,
) -> None:
    """Render the three-card YOUR OPTIONS AT A GLANCE dashboard."""
    p = doc.add_paragraph()
    _spacing(p, 6, 4)
    _body_run(p, "YOUR OPTIONS AT A GLANCE", bold=True, size=11, color=_CHARCOAL)

    def _find_hotel(label: str | None) -> HotelRow | None:
        if label is None:
            return None
        for plan in plans:
            for h in plan.hotels:
                if h.name == label or plan.label == label:
                    return h
        return None

    rec_hotel   = _find_hotel(recommended_name)
    value_hotel = _find_hotel(best_value_name)
    prem_hotel  = _find_hotel(premium_name)

    def _price_for(h: HotelRow | None) -> str:
        if h is None:
            return "—"
        price = h.discounted_price if h.discounted_price > 0 else h.online_price
        return format_indian_number(price)

    def _reason_for(role: str, h: HotelRow | None) -> str:
        if h is None:
            return ""
        if role == "rec":
            return "Our top pick for this itinerary"
        if role == "value":
            return f"{h.discount_pct:.1f}% off best online prices" if h.discount_pct > 0 else "Strong value option"
        if role == "premium":
            return f"From {format_indian_number(h.online_price)} online"
        return ""

    cards = [
        ("⭐  OUR RECOMMENDATION", recommended_name or "—", _price_for(rec_hotel),   _reason_for("rec",   rec_hotel),   "F0FFF4", _FOREST_GREEN),
        ("💰  BEST VALUE",         best_value_name or "—",  _price_for(value_hotel), _reason_for("value", value_hotel), "FFFFFF", _RULE_COLOR),
        ("🏆  PREMIUM EXPERIENCE", premium_name or "—",     _price_for(prem_hotel),  _reason_for("premium", prem_hotel), "FFFFFF", _RULE_COLOR),
    ]

    table = doc.add_table(rows=1, cols=3)
    table.autofit = False
    _no_borders(table)
    col_w = Inches(2.1)
    for ci in range(3):
        table.rows[0].cells[ci].width = col_w

    for ci, (role_label, name, price, reason, bg, border_color) in enumerate(cards):
        cell = table.rows[0].cells[ci]
        _shade_cell(cell, bg)

        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), "4")
            b.set(qn("w:color"), border_color)
            tcBorders.append(b)
        tcPr.append(tcBorders)

        tcMar = OxmlElement("w:tcMar")
        for side, val in (("top", "80"), ("bottom", "80"), ("left", "100"), ("right", "80")):
            m = OxmlElement(f"w:{side}")
            m.set(qn("w:w"), val)
            m.set(qn("w:type"), "dxa")
            tcMar.append(m)
        tcPr.append(tcMar)

        p = cell.paragraphs[0]
        _spacing(p, 0, 4)
        _body_run(p, role_label, bold=True, size=8.5, color=_GREY)

        p2 = cell.add_paragraph()
        _spacing(p2, 2, 2)
        _body_run(p2, name, bold=True, size=11, color=_CHARCOAL)

        p3 = cell.add_paragraph()
        _spacing(p3, 0, 2)
        _body_run(p3, price, bold=True, size=13, color=_GREEN if ci == 0 else _CHARCOAL)

        p4 = cell.add_paragraph()
        _spacing(p4, 0, 0)
        _body_run(p4, reason, size=8.5, color=_GREY)
```

- [ ] **Step 3: Add `_render_stats_row()` helper**

```python
def _render_stats_row(
    doc: Document, total_savings: float, largest_discount: float, total_count: int
) -> None:
    """Three-cell stats banner below the highlight cards."""
    _spacing(doc.add_paragraph(), 4, 0)

    stats = [
        ("TOTAL SAVINGS AVAILABLE", format_indian_number(total_savings) if total_savings > 0 else "—"),
        ("LARGEST DISCOUNT",        f"{largest_discount:.1f}%" if largest_discount > 0 else "—"),
        ("HOTELS COMPARED",         str(total_count)),
    ]
    table = doc.add_table(rows=2, cols=3)
    table.autofit = False
    _no_borders(table)
    for ci in range(3):
        for row in table.rows:
            row.cells[ci].width = Inches(2.1)

    _shade_cell(table.rows[0].cells[0], _LIGHT_GREY)
    _shade_cell(table.rows[0].cells[1], _LIGHT_GREY)
    _shade_cell(table.rows[0].cells[2], _LIGHT_GREY)

    for ci, (label, value) in enumerate(stats):
        lp = table.rows[0].cells[ci].paragraphs[0]
        _spacing(lp, 6, 2)
        lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _body_run(lp, label, bold=True, size=8, color=_GREY)

        vp = table.rows[1].cells[ci].paragraphs[0]
        _spacing(vp, 2, 6)
        vp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _body_run(vp, value, bold=True, size=14, color=_CHARCOAL)
```

- [ ] **Step 4: Update `_build_executive_summary()` to use new dashboard**

Replace the full function:

```python
def _build_executive_summary(doc: Document, plans: list[Plan],
                              enriched_map: dict[str, EnrichedHotel],
                              grouped_by_sections: bool = False) -> None:
    if not plans:
        return

    _heading(doc, "Executive Summary", level=1)
    p = doc.add_paragraph()
    _spacing(p, 0, 14)
    _body_run(p, "All accommodation options compared at a glance.", color=_GREY)

    rec, best_val, premium, total_savings, largest_disc, total_count = _identify_highlights(
        plans, grouped_by_sections
    )

    _render_highlight_cards(doc, plans, grouped_by_sections, rec, best_val, premium)
    _spacing(doc.add_paragraph(), 8, 0)
    _render_stats_row(doc, total_savings, largest_disc, total_count)
    _thin_rule(doc, before=16, after=12)

    p = doc.add_paragraph()
    _spacing(p, 0, 8)
    _body_run(p, "FULL COMPARISON", bold=True, size=10, color=_CHARCOAL)

    if grouped_by_sections:
        _build_exec_summary_by_hotel(doc, plans)
    else:
        _build_exec_summary_by_plan(doc, plans)
    _thin_borders(doc.tables[-1])
```

- [ ] **Step 5: Update comparison table header — replace navy with light grey**

In `_build_exec_summary_by_hotel()`, find the header row shading lines:
```python
        _shade_cell(cell, _HDR_BG)
```
Replace ALL occurrences in both `_build_exec_summary_by_hotel` and `_build_exec_summary_by_plan` with:
```python
        _shade_cell(cell, _LIGHT_GREY)
```
And change the header text color from `_WHITE` to `_CHARCOAL`:
```python
        _body_run(p, label, bold=True, size=9, color=_CHARCOAL)
```

Also remove the `_HDR_BG` constant (it's no longer used anywhere — confirm with `grep -n "_HDR_BG" src/hotel_options/generator.py`).

- [ ] **Step 6: Add `HotelRow` to the import at the top of generator.py**

The `_render_highlight_cards` function uses `HotelRow` — make sure it's imported:
```python
from src.hotel_options.models import Plan, EnrichedHotel, HotelRow
```

- [ ] **Step 7: Smoke test**

Start server, generate a document, check that:
- Executive Summary has the three cards at the top
- Stats row shows below
- Comparison table below that with light grey header (no blue)

- [ ] **Step 8: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): executive summary dashboard — highlight cards, stats row, updated table"
```

---

### Task 7: Redesign hotel card layout — two-column with hero image

**Files:**
- Modify: `src/hotel_options/generator.py` — `_add_hotel_card()`, `_add_key_facts()`

- [ ] **Step 1: Rewrite `_add_key_facts()` as a two-column table**

Replace the existing `_add_key_facts()`:

```python
def _add_key_facts_column(cell, enriched: EnrichedHotel) -> None:
    """Fill the LEFT column of the hotel detail table with key metadata."""
    facts: list[tuple[str, str]] = []
    if enriched.address:
        facts.append(("📍 Location", enriched.address))
    if enriched.category:
        facts.append(("🏨 Category", enriched.category))
    if enriched.rating:
        facts.append(("⭐ Rating",
                       f"{enriched.rating}/5 ({enriched.rating_count:,} reviews)"))
    if enriched.dates:
        facts.append(("📅 Check-in / Out", enriched.dates))
    if enriched.cancellation:
        facts.append(("🔄 Cancellation", enriched.cancellation))
    if enriched.meal_type:
        facts.append(("🍳 Breakfast", enriched.meal_type))
    if enriched.phone:
        facts.append(("📞 Phone", enriched.phone))

    first = True
    for label, value in facts:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        _spacing(p, 1, 3)
        _body_run(p, f"{label}  ", size=9.5, color=_GREY)
        _body_run(p, value, size=9.5, color=_CHARCOAL)
```

- [ ] **Step 2: Rewrite `_add_hotel_card()` with new layout**

Replace the entire `_add_hotel_card()` function:

```python
def _add_hotel_card(doc: Document, enriched: EnrichedHotel, recommended: bool = False,
                    area_label: str = "") -> None:
    """Full hotel card — hero image, positioning statement, two-column details + insights, pricing."""

    # Area / destination label
    if area_label:
        _area_label(doc, area_label)

    # Hero image — full width
    if enriched.photo_bytes:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 0, 0)
        p.add_run().add_picture(io.BytesIO(enriched.photo_bytes), width=Inches(6.5))
    else:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, 8, 6)
        _body_run(p, "[ Image not available ]", size=9, color=_GREY)

    # Recommendation badge (if applicable) — appears just below the image
    if recommended:
        _recommendation_badge(doc)

    # Hotel name
    name_para = doc.add_paragraph()
    _spacing(name_para, 12, 2)
    r = name_para.add_run(enriched.official_name or enriched.address or "Hotel")
    r.bold           = True
    r.font.name      = "Georgia"
    r.font.size      = Pt(18)
    r.font.color.rgb = _CHARCOAL

    # Positioning statement — one line beneath the hotel name
    if enriched.positioning_statement:
        p = doc.add_paragraph()
        _spacing(p, 0, 8)
        _body_run(p, enriched.positioning_statement, italic=True, size=10.5, color=_GREY)

    _thin_rule(doc, before=0, after=10)

    # Two-column detail table: Hotel Details (left) | Bon Voyage Insights (right)
    detail_table = doc.add_table(rows=1, cols=2)
    detail_table.autofit = False
    _no_borders(detail_table)
    detail_table.rows[0].cells[0].width = Inches(3.1)
    detail_table.rows[0].cells[1].width = Inches(3.4)

    left_cell  = detail_table.rows[0].cells[0]
    right_cell = detail_table.rows[0].cells[1]

    # Left: add section label then facts
    lp = left_cell.paragraphs[0]
    _spacing(lp, 0, 6)
    _body_run(lp, "HOTEL DETAILS", bold=True, size=8.5, color=_GREY)
    _add_key_facts_column(left_cell, enriched)

    # Right: Bon Voyage Insight box
    rp = right_cell.paragraphs[0]
    _spacing(rp, 0, 6)
    _body_run(rp, "BON VOYAGE INSIGHTS", bold=True, size=8.5, color=_GREY)

    # Insight box — inline within the right cell
    if enriched.insight_text:
        # Build a nested table inside right_cell for the insight box
        nested = right_cell.add_table(rows=1, cols=1)
        _no_borders(nested)
        ic = nested.rows[0].cells[0]
        _shade_cell(ic, _INSIGHT_BG)

        ic_tcPr = ic._tc.get_or_add_tcPr()
        ic_tcBorders = OxmlElement("w:tcBorders")
        left_b = OxmlElement("w:left")
        left_b.set(qn("w:val"), "single")
        left_b.set(qn("w:sz"), "16")
        left_b.set(qn("w:color"), _FOREST_GREEN)
        ic_tcBorders.append(left_b)
        ic_tcPr.append(ic_tcBorders)

        ic_tcMar = OxmlElement("w:tcMar")
        for side, val in (("top", "60"), ("bottom", "60"), ("left", "100"), ("right", "60")):
            m = OxmlElement(f"w:{side}")
            m.set(qn("w:w"), val)
            m.set(qn("w:type"), "dxa")
            ic_tcMar.append(m)
        ic_tcPr.append(ic_tcMar)

        ip = ic.paragraphs[0]
        _spacing(ip, 0, 4)
        _body_run(ip, "BON VOYAGE INSIGHT", bold=True, size=8, color=_GREEN)
        ip2 = ic.add_paragraph()
        _spacing(ip2, 2, 0)
        _body_run(ip2, enriched.insight_text, size=9.5, color=_CHARCOAL)

    # Perfect For chips
    if enriched.perfect_for:
        rp2 = right_cell.add_paragraph()
        _spacing(rp2, 10, 4)
        _body_run(rp2, "PERFECT FOR", bold=True, size=8.5, color=_GREY)

        chips_tbl = right_cell.add_table(rows=1, cols=len(enriched.perfect_for))
        chips_tbl.autofit = True
        _no_borders(chips_tbl)
        for ci, label in enumerate(enriched.perfect_for):
            cc = chips_tbl.rows[0].cells[ci]
            _shade_cell(cc, _CHIP_BG)
            cc_tcPr = cc._tc.get_or_add_tcPr()
            cc_tcBorders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                b = OxmlElement(f"w:{side}")
                b.set(qn("w:val"), "single")
                b.set(qn("w:sz"), "4")
                b.set(qn("w:color"), _RULE_COLOR)
                cc_tcBorders.append(b)
            cc_tcPr.append(cc_tcBorders)
            cc_tcMar = OxmlElement("w:tcMar")
            for side, val in (("left", "60"), ("right", "60")):
                m = OxmlElement(f"w:{side}")
                m.set(qn("w:w"), val)
                m.set(qn("w:type"), "dxa")
                cc_tcMar.append(m)
            cc_tcPr.append(cc_tcMar)
            cp2 = cc.paragraphs[0]
            cp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _spacing(cp2, 3, 3)
            _body_run(cp2, label, size=8.5, color=_CHARCOAL)

    # Things To Know
    if enriched.things_to_know:
        rp3 = right_cell.add_paragraph()
        _spacing(rp3, 10, 4)
        _body_run(rp3, "THINGS TO KNOW", bold=True, size=8.5, color=_GREY)
        for bullet in enriched.things_to_know:
            rp4 = right_cell.add_paragraph()
            _spacing(rp4, 1, 2)
            _body_run(rp4, f"  •  {bullet}", size=9.5, color=_CHARCOAL)

    _thin_rule(doc, before=14, after=10)

    # About the Hotel — description
    p = doc.add_paragraph()
    _spacing(p, 0, 4)
    _body_run(p, "ABOUT THE HOTEL", bold=True, size=9, color=_GREY)

    if enriched.description:
        p2 = doc.add_paragraph()
        _spacing(p2, 4, 0)
        _body_run(p2, enriched.description, size=11, color=_CHARCOAL)
```

- [ ] **Step 3: Update `build_document()` to pass `area_label` to `_add_hotel_card()`**

In `build_document()`, in the `grouped_by_sections` branch, find:
```python
                    _add_hotel_card(doc, enriched, recommended=hotel.recommended)
```
Replace with:
```python
                    _add_hotel_card(doc, enriched, recommended=hotel.recommended,
                                    area_label=plan.label)
```

In the plan-based branch, `_add_hotel_card(doc, enriched)` stays unchanged (no area label for plan-based).

- [ ] **Step 4: Smoke test**

Generate a DOCX and verify:
- Full-width hero image
- Green recommendation badge below image (if applicable)
- Hotel name in Georgia 18pt
- Positioning statement in italic grey
- Two-column layout: facts left, insights right
- Insight box with green left border
- Perfect For chips
- Things To Know bullets
- "ABOUT THE HOTEL" section

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): new hotel card layout — hero image, two-column, insight box, chips"
```

---

### Task 8: Redesign pricing card with large typography

**Files:**
- Modify: `src/hotel_options/generator.py` — `_add_pricing_block()`, `_add_hotel_pricing_block()`

- [ ] **Step 1: Replace `_add_pricing_block()` (plan-based pricing)**

```python
def _add_pricing_block(doc: Document, plan: Plan) -> None:
    """Large-typography pricing card for plan-based layout."""
    pr = plan.pricing
    _render_pricing_card(
        doc,
        online_price=pr.total_online_price,
        our_price=pr.discounted_price,
        savings=pr.customer_discount,
        pct=pr.discount_pct,
        meal_type=None,
        cancellation=None,
    )
```

- [ ] **Step 2: Replace `_add_hotel_pricing_block()` (per-hotel pricing)**

```python
def _add_hotel_pricing_block(doc: Document, hotel) -> None:
    """Large-typography pricing card for grouped-by-sections layout."""
    our_price = hotel.discounted_price if hotel.discounted_price > 0 else hotel.online_price
    _render_pricing_card(
        doc,
        online_price=hotel.online_price,
        our_price=our_price,
        savings=hotel.customer_discount,
        pct=hotel.discount_pct,
        meal_type=hotel.meal_type,
        cancellation=hotel.cancellation,
    )
```

- [ ] **Step 3: Add `_render_pricing_card()` — the shared implementation**

Add this function before `_add_pricing_block()`:

```python
def _render_pricing_card(
    doc: Document,
    online_price: float,
    our_price: float,
    savings: float,
    pct: float,
    meal_type: str | None,
    cancellation: str | None,
) -> None:
    """Shared large-typography pricing card used by both plan and per-hotel layouts."""
    _spacing(doc.add_paragraph(), 6, 0)

    # Pricing table: 3 rows, label + value columns
    table = doc.add_table(rows=3, cols=2)
    table.autofit = False
    _no_borders(table)
    table.rows[0].cells[0].width = Inches(2.5)
    table.rows[0].cells[1].width = Inches(4.0)

    has_savings = savings > 0
    best_savings_badge = has_savings and pct >= 10

    rows_data = [
        ("ONLINE PRICE", format_indian_number(online_price), False, _GREY, _GREY, 11),
        ("OUR PRICE",    format_indian_number(our_price),    True,  _GREY, _CHARCOAL, 18),
        ("YOU SAVE",
         f"{format_indian_number(savings)} ({pct:.1f}% off)" if has_savings else "—",
         True, _GREY, _GREEN if has_savings else _GREY, 13),
    ]

    for i, (label, value, bold, lbl_color, val_color, val_size) in enumerate(rows_data):
        lp = table.rows[i].cells[0].paragraphs[0]
        _spacing(lp, 4, 4)
        _body_run(lp, label, bold=True, size=9, color=lbl_color)
        vp = table.rows[i].cells[1].paragraphs[0]
        _spacing(vp, 4, 4)
        _body_run(vp, value, bold=bold, size=val_size, color=val_color)

        # BEST SAVINGS badge inline with the savings row
        if i == 2 and best_savings_badge:
            _body_run(vp, "  BEST SAVINGS", bold=True, size=8.5, color=_GREEN)

    # Badge row for breakfast/cancellation
    badges: list[str] = []
    if meal_type and any(kw in (meal_type or "").lower() for kw in ("breakfast", "b&b", "full board", "half board")):
        badges.append("🍳 Breakfast Included")
    if cancellation and "free" in (cancellation or "").lower():
        badges.append("✓ Free Cancellation")

    if badges:
        _spacing(doc.add_paragraph(), 4, 0)
        p = doc.add_paragraph()
        _spacing(p, 0, 0)
        _body_run(p, "  •  ".join(badges), bold=True, size=9, color=_GREEN)
```

- [ ] **Step 4: Smoke test**

Generate a document. Check:
- "OUR PRICE" appears large (18pt) and bold
- "YOU SAVE" appears in forest green
- "BEST SAVINGS" badge appears when discount ≥ 10%
- Breakfast/cancellation badges show when applicable

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): large-typography pricing card with best-savings badge"
```

---

### Task 9: Add per-page footer

**Files:**
- Modify: `src/hotel_options/generator.py` — add `_add_footer()` + `_field_code_run()`, update `build_document()`

- [ ] **Step 1: Add field-code helper**

Add this function near the other low-level helpers in `generator.py`:

```python
def _field_code_run(para, field_name: str) -> None:
    """Append a Word field code run (PAGE or NUMPAGES) to a paragraph."""
    run = para.add_run()
    run.font.name  = _FONT
    run.font.size  = Pt(8)
    run.font.color.rgb = _GREY

    fldChar_begin = OxmlElement("w:fldChar")
    fldChar_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fldChar_begin)

    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = f" {field_name} "
    run._r.append(instrText)

    fldChar_end = OxmlElement("w:fldChar")
    fldChar_end.set(qn("w:fldCharType"), "end")
    run._r.append(fldChar_end)
```

- [ ] **Step 2: Add `_add_footer()` function**

```python
def _add_footer(doc: Document, generated_date: str) -> None:
    """Add a three-part footer: BVBM name | Page X of Y | Generated DATE."""
    section = doc.sections[0]
    footer  = section.footer
    footer.is_linked_to_previous = False

    # Clear default empty paragraph if present
    for p in footer.paragraphs:
        p.clear()

    # Thin top rule
    fp = footer.paragraphs[0]
    _spacing(fp, 0, 0)
    pPr = fp._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top_b = OxmlElement("w:top")
    top_b.set(qn("w:val"), "single")
    top_b.set(qn("w:sz"), "4")
    top_b.set(qn("w:color"), _RULE_COLOR)
    top_b.set(qn("w:space"), "4")
    pBdr.append(top_b)
    pPr.append(pBdr)

    # Footer content table: 3 columns
    tbl = footer.add_table(rows=1, cols=3)
    _no_borders(tbl)
    tbl.rows[0].cells[0].width = Inches(2.5)
    tbl.rows[0].cells[1].width = Inches(1.5)
    tbl.rows[0].cells[2].width = Inches(2.5)

    lp = tbl.rows[0].cells[0].paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _spacing(lp, 4, 0)
    _body_run(lp, "Bon Voyage By Marina", bold=True, size=8, color=_GREY)

    cp = tbl.rows[0].cells[1].paragraphs[0]
    cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(cp, 4, 0)
    _body_run(cp, "Page ", size=8, color=_GREY)
    _field_code_run(cp, "PAGE")
    _body_run(cp, " of ", size=8, color=_GREY)
    _field_code_run(cp, "NUMPAGES")

    rp = tbl.rows[0].cells[2].paragraphs[0]
    rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _spacing(rp, 4, 0)
    _body_run(rp, f"Generated {generated_date}", size=8, color=_GREY)
```

- [ ] **Step 3: Update `build_document()` to accept and apply the footer**

Update the signature and body of `build_document()` to pass a date. Add `import datetime` at the top of `generator.py` if not present.

Inside `build_document()`, add after `_configure_styles(doc)`:

```python
    generated_date = datetime.date.today().strftime("%d %b %Y")
    _add_footer(doc, generated_date)
```

- [ ] **Step 4: Smoke test**

Generate a DOCX and open it in Word or Preview. Scroll through pages and verify:
- Footer appears on every page
- Left: "Bon Voyage By Marina"
- Center: "Page X of Y" (field codes update when Word renders)
- Right: "Generated DD Mon YYYY"

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): add per-page footer with BVBM name, page numbers, and date"
```

---

### Task 10: Redesign thank you page + final cleanup

**Files:**
- Modify: `src/hotel_options/generator.py` — `_build_thank_you_page()`

- [ ] **Step 1: Rewrite `_build_thank_you_page()`**

Replace the full function:

```python
def _build_thank_you_page(doc: Document, destination: str,
                          destination_photo: bytes | None = None) -> None:
    def blank(n: int = 1) -> None:
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    blank(8)

    _thin_rule(doc, before=0, after=20, color=_RULE_COLOR)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p, 0, 16)
    r = p.add_run("Thank You")
    r.bold           = True
    r.font.name      = "Georgia"
    r.font.size      = Pt(28)
    r.font.color.rgb = _CHARCOAL

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p2, 0, 6)
    _body_run(p2, (
        f"We are grateful for the opportunity to help plan your {destination} stay. "
        f"We hope these options give you confidence and clarity as you finalise your travel plans."
    ), size=11, color=_CHARCOAL)

    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p3, 0, 20)
    _body_run(p3, "Should you wish to explore other options, upgrades, or arrangements, we would love to help.",
              size=11, color=_GREY)

    _thin_rule(doc, before=12, after=16, color=_RULE_COLOR)

    p4 = doc.add_paragraph()
    p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p4, 0, 4)
    _body_run(p4, "Warm regards,", size=11, color=_CHARCOAL)

    p5 = doc.add_paragraph()
    p5.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p5, 2, 2)
    _body_run(p5, "Bon Voyage By Marina", bold=True, size=12, color=_CHARCOAL)

    p6 = doc.add_paragraph()
    p6.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p6, 2, 2)
    _body_run(p6, "Bespoke Travel Planning • Premium Stays • Seamless Experiences",
              italic=True, size=10, color=_GREY)

    p7 = doc.add_paragraph()
    p7.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(p7, 4, 0)
    _body_run(p7, "+91 86000 15316  |  @bonvoyagebymarina  |  www.bonvoyagebymarina.com",
              size=10, color=_CHARCOAL)
```

- [ ] **Step 2: Remove unused `destination_photo` parameter reference (it's kept for signature stability)**

The `destination_photo` parameter in `_build_thank_you_page()` is no longer used. Leave it in the signature for backward compatibility (the call site in `build_document()` already passes it).

- [ ] **Step 3: Verify no references to `_HDR_BG` remain**

```bash
grep -n "_HDR_BG" /Users/mjain/work/projects/travel/BVBMGuide/src/hotel_options/generator.py
```

Expected: no output. If any remain, replace them with `_RULE_COLOR`.

- [ ] **Step 4: Final smoke test — full end-to-end**

```bash
cd /Users/mjain/work/projects/travel/BVBMGuide && python -m src.library
```

Upload a test XLSX. Download and open the DOCX. Walk through every page and verify:

**Cover:** Full-width Pexels destination photo, large Georgia title, no blue anywhere  
**Advisor Note:** Clean, generous spacing, light grey rule at bottom  
**Executive Summary:** Three highlight cards + stats row + light-grey-header comparison table  
**Each Hotel Page:** Full-width hero image → green recommendation badge (if applicable) → Georgia hotel name → italic positioning statement → two columns (facts | insight box + chips + bullets) → "ABOUT THE HOTEL" description → large-typography pricing card  
**Thank You:** Minimal, centered, elegant — no sales content  
**Every Page:** Footer with BVBM name, page numbers, date

- [ ] **Step 5: Commit**

```bash
git add src/hotel_options/generator.py
git commit -m "feat(hotel-redesign): clean thank you page + remove navy blue remnants"
```

---

## Reminder

**TBD — Icon replacement:** Replace emoji icons (📍 ⭐ 🍳 📞 etc.) with elegant monochrome Unicode symbols or a symbol font. Deferred pending decision on approach. Remind before closing the branch.
