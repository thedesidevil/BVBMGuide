# AIG Verification Feature — Design Spec

**Date:** 2026-06-14
**Status:** Approved for implementation

---

## Overview

A new "Verify AIG" tab on the existing Library QC web UI. Users upload a generated AIG (DOCX), the system runs a two-layer verification pipeline, and returns a scored checklist with pass/fail per item plus AI narrative commentary per section.

The feature works **only from the uploaded DOCX** — no cross-referencing with library data or itinerary source files.

---

## Role-Based Access

The existing Google OAuth system is extended with a two-tier role model:

| Role | Access |
|---|---|
| Admin | All existing tabs (City View, Sweep, Ingest, History, Audit) + Verify AIG |
| Authorized user | Verify AIG only |

**Environment variables:**
```
GOOGLE_ALLOWED_EMAILS=alice@domain.com,bob@domain.com   # who can log in (existing)
GOOGLE_ALLOWED_DOMAIN=domain.com                        # alternative domain-wide allow (existing)
ADMIN_EMAILS=alice@domain.com                           # who gets admin tabs (new)
```

**Backend changes:**
- `google_auth.py` — add `is_admin(email: str) -> bool` (checks against `ADMIN_EMAILS` env var)
- `/api/me` — extend response to include `is_admin: bool`
- All existing API routes (city, country, review, sweep, audit, ingest) — add `require_admin` FastAPI dependency
- New `/api/verify/` endpoint — no admin requirement, any authenticated user

**Frontend changes:**
- `App.tsx` — add `isAdmin: boolean` state, populated from `/api/me`
- `Layout.tsx` — existing tabs rendered only when `isAdmin`; Verify tab always rendered
- Non-admins: no sidebar; `mode` defaults to `"verify"` on load (admins default to `"city"`)

---

## Architecture

```
Upload DOCX
    │
    ├─ Layer 1: Rule Engine (free, instant, deterministic)
    │       Regex + heuristics → List[Finding]
    │
    ├─ Layer 2: AI Pass (single GPT-4o-mini call)
    │       Full extracted text + QC checklist in system prompt
    │       Structured JSON output (schema-enforced) → List[Finding] + Narratives
    │
    └─ Merge → unified response
```

**New files:**
- `src/library/ui/api/verify.py` — FastAPI router, `POST /api/verify/`
- `src/library/ui/services/verify_service.py` — pipeline orchestration
- `ui-frontend/src/components/VerifyTab.tsx` — upload + results UI

**Modified files:**
- `src/library/ui/google_auth.py` — add `is_admin()`, extend `/api/me`
- `src/library/ui/__init__.py` — register verify router; add `require_admin` to existing routers
- `ui-frontend/src/App.tsx` — add `"verify"` mode, `isAdmin` state
- `ui-frontend/src/components/Layout.tsx` — conditional tab rendering

---

## Verification Pipeline

### DOCX Text Extraction

Use `python-docx` to extract paragraphs in order, preserving style names (heading vs body). Output is a flat list of `{style, text}` objects passed to both layers.

### Layer 1 — Rule Engine (R1–R10)

All checks are deterministic; no AI required.

| ID | Check | Severity |
|---|---|---|
| R1 | AI artifact phrases detected: `"Here is Day"`, `"Sure! Here's"`, `"I have generated"`, `"As an AI"`, triple-backtick fences, `"In conclusion,"` | RED |
| R2 | Placeholder text detected: `[HOTEL NAME]`, `TBD`, `TODO`, `INSERT`, `XXXX` | RED |
| R3 | All 13 rendered sections present by heading text (Cover → Thank You, as produced by the assembler; TOC is excluded because the assembler does not currently render one) | RED |
| R4 | Day count matches itinerary span — highest day number equals expected trip length | RED |
| R5 | Every day heading matches format `Day N: Weekday, Month D – Title` | YELLOW |
| R6 | Maps links present in key sections — Client Info hotels, each day's restaurants and attractions, Important Places, Souvenir Guide | YELLOW |
| R7 | Each day has at least 3 restaurant entries | YELLOW |
| R8 | Time format completeness — flag ranges missing AM/PM on one side (e.g. `"12:00 – 11:00 PM"`) | YELLOW |
| R9 | Broken or non-standard character encoding detected | YELLOW |
| R10 | Day dates are sequential with no unexplained gaps | RED |

### Layer 2 — AI Pass (A1–A20)

Single `POST` to GPT-4o-mini with `response_format: json_schema`. The system prompt contains the full QC checklist with definitions and examples. The model returns **only RED and YELLOW findings** — it omits checks that pass. The frontend infers PASSED for any AI check (A1–A20) not present in the findings list. This keeps the response compact and reduces output tokens.

Every finding **must** include an `evidence` field: a verbatim quote from the document. This is enforced by the JSON schema (`required: ["evidence"]`). A finding whose evidence does not appear in the document can be dismissed immediately.

| ID | Check | Severity |
|---|---|---|
| A1 | Restaurants on any day violate stated dietary preferences | RED |
| A2 | Safety & Emergency Contacts has real country-specific numbers, not generic `112` only | RED |
| A3 | Any day's content appears to be for the wrong destination (copy-paste error) | RED |
| A4 | Guide title is creative and destination-specific | YELLOW |
| A5 | Packing list is specific to the trip's season and activities | YELLOW |
| A6 | Restaurant entries include full opening hours with times (not just day range) | YELLOW |
| A7 | Lunch recommendations are near the day's attractions; dinner recommendations are near the hotel | YELLOW |
| A8 | Must-Try Dishes section has entries for each destination city in the itinerary | YELLOW |
| A9 | Getting Around has transport options for each city visited | YELLOW |
| A10 | Cultural Etiquette section is destination-specific, not generic boilerplate | YELLOW |
| A11 | Thank You page uses client names, not template text | YELLOW |
| A12 | Overall coherence — no missing days, broken narrative, or duplicate content blocks | YELLOW |
| A13 | Opening hours are logically valid — end time is not before start time in the same AM/PM period (e.g. `11 PM – 10 PM`) | RED |
| A14 | Dinner-recommended venues have hours that include evening service (after ~7 PM) | RED |
| A15 | Time-of-day recommendations (sunset, golden hour, evening walks) are seasonally and geographically accurate for the destination and travel month | RED |
| A16 | Stated travel times between named locations are plausible given the actual geography | RED |
| A17 | Transport pass coverage claims are accurate (e.g. Nozomi trains flagged as JR Pass-covered when they require a supplement) | RED |
| A18 | Important Places section covers essential services for each hotel: grocery store, pharmacy, hospital — each with hours and Maps link | RED |
| A19 | Venues recommended for a meal slot are appropriate for that meal type — coffee cafés or dessert-only venues flagged if listed as dinner recommendations | YELLOW |
| A20 | Distance/proximity references are anchored to the logically preceding attraction in that day's sequence | YELLOW |

---

## API Contract

### Request
```
POST /api/verify/
Content-Type: multipart/form-data
Authorization: session cookie (handled by middleware)

file: <.docx binary>
```

File validation: reject non-DOCX (check content-type and magic bytes). No size limit needed — 100-page AIGs are typically 1–5 MB, well under API Gateway's 10 MB limit.

### Response
```json
{
  "findings": [
    {
      "check_id": "A14",
      "layer": "ai",
      "severity": "RED",
      "section": "Day 4 – Dinner",
      "description": "Mame & Shiba Café closes at 5:30 PM but is listed as a dinner recommendation",
      "evidence": "🍴 Mame & Shiba Café  ⏰ Opening Hours: 11:30 AM – 5:30 PM"
    }
  ],
  "narratives": {
    "overall": "Strong guide overall — 2 RED issues need fixing before send.",
    "days": "Days 1–4 are well-structured. Day 3 has a dinner timing conflict...",
    "restaurants": "Most recommendations are appropriate. Two dinner venues close before 6 PM...",
    "static_sections": "Packing list is season-specific. Safety section has country-specific numbers..."
  },
  "meta": {
    "red_count": 3,
    "yellow_count": 9,
    "passed_count": 18,
    "model": "gpt-4o-mini"
  }
}
```

Error responses:
- `400` — not a DOCX file, or file unreadable
- `401` — not authenticated
- `500` — AI call failed (include `"error"` message in body)

---

## AI Prompt Design

**System prompt** (static, baked in at deploy time):
- Role: expert travel guide QC reviewer for Bon Voyage by Marina
- Full definitions of checks A1–A20 with examples of passing and failing cases
- Instruction: for every RED/YELLOW finding, include a verbatim `evidence` quote; if no issue found, omit the finding (do not return passing items — the rule engine handles pass display)
- Instruction: narratives should be concise (2–4 sentences per section), actionable, and reference specific days/sections

**User message**: extracted document text (full, untruncated)

**Context sizing**: even a 200-page AIG is ~60K tokens — fits in GPT-4o-mini's 128K context in a single call. No chunking needed.

**Cost per run** (GPT-4o-mini at $0.15/MTok input, $0.60/MTok output):

| Document size | Approx. tokens | Cost |
|---|---|---|
| 30-page AIG | ~15K in, 2K out | ~$0.004 |
| 60-page AIG | ~25K in, 3K out | ~$0.006 |
| 100-page AIG | ~38K in, 4K out | ~$0.008 |

5 verification rounds on a 60-page AIG ≈ $0.03 total.

---

## Frontend UX

### Tab layout

```
Header: [City View] [Sweep] [Ingest] [History] [Audit]  ← admin only
                                                [Verify AIG]  ← all users
```

Non-admins: Verify AIG is the only tab; no sidebar rendered.

### VerifyTab states

**Upload state**
- Drag-and-drop zone + "Choose file" button
- Accepts `.docx` only (client-side validation before upload)
- "Run Verification" button disabled until file selected

**Loading state**
- Spinner replacing the button
- Label: "Verifying… this usually takes 15–30 seconds"
- Upload disabled; no cancel (Lambda call in-flight)

**Results state**

```
┌── Summary ─────────────────────────────────────────┐
│  3 RED  ·  9 YELLOW  ·  18 passed                  │
│  gpt-4o-mini            [Verify Another File]       │
└────────────────────────────────────────────────────┘

┌── Narratives ──────────────────────────────────────┐
│  [Overall] [Days] [Restaurants] [Other Sections]   │
│  ─────────────────────────────────────────────     │
│  <narrative text for selected tab>                 │
└────────────────────────────────────────────────────┘

┌── Findings ────────────────────────────────────────┐
│  🔴 RED ISSUES (3) — expanded                      │
│  ┌──────────────────────────────────────────────┐  │
│  │  A14 · Day 4 – Dinner                        │  │
│  │  Dinner venue closes at 5:30 PM              │  │
│  │  ▼ Evidence                                  │  │
│  │    "🍴 Mame & Shiba Café  ⏰ 11:30–5:30 PM" │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  🟡 YELLOW ISSUES (9) — expanded                   │
│  ...                                               │
│                                                    │
│  ✅ PASSED (18) — collapsed by default             │
└────────────────────────────────────────────────────┘
```

- Evidence is collapsed under `▼ Evidence` toggle per finding
- "Verify Another File" resets to upload state without page reload
- REDs and YELLOWs expanded by default; PASSed section collapsed

---

## Lambda Deployment Notes

- Lambda timeout: increase to **120 seconds** minimum (AI call can take 10–30s for large documents)
- No additional dependencies beyond `python-docx` (already in requirements) and the existing `openai` client
- No S3 needed — DOCX files fit within API Gateway's 10 MB payload limit
- `AI_MODEL=gpt-4o-mini` in Lambda environment (separate from the library AI model if different)

---

## Out of Scope

- Cross-referencing the AIG against the original itinerary PDF
- Suggesting replacement content (verification only, no generation)
- Batch verification of multiple files
- Saving verification history (stateless — no results stored server-side)
