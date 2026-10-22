# AIG v2 acceptance log

Status: **not yet run** — engine tasks 1–22 are built and unit-tested with fakes (466 tests); live runs need the Google setup (`google-cloud-setup.md`) and the user's real test inputs under `input/for-aigv2/` (gitignored; the trip-to-file mapping is kept there, not in the repo).

## How to run one trip

```bash
python -m src.aigv2 template intake.docx          # fill in per trip
python -m src.aigv2 start --intake intake.docx <attachments...>   # prints run id + numbered questions
python -m src.aigv2 build RUN_ID --answers answers.json           # JSON {question_id: answer}
python -m src.aigv2 qc EDITED.docx --run RUN_ID                   # re-QC after human edits (--run required)
python -m src.aigv2 regenerate RUN_ID --day 2 --section safety
```

Each command prints the AI/Google cost split and writes `cost.json` (history in `cost_history.json`). Budget: first full run (build + one QC) ≤ $1.

## Pre-conditions (user)
- [ ] Google Places API (New) + Routes API enabled, billing on, key restricted, $20 budget alert (see google-cloud-setup.md).
- [ ] Latest AIGs ingested into the library (`python -m src.library ingest`, then plain `build` — no `--force`). Lisbon and Nusa Lembongan currently have no restaurants (expect gap markers).
- [ ] `.env`: `AI_MODEL=gpt-6.1-sol`, `AI_MODEL_FAST=gpt-6-luna`, `AI_API_KEY`, `AI_BASE_URL`, `GOOGLE_MAPS_API_KEY`.

## Acceptance trips
| Trip | Why | Questions asked | Markers by type | QC findings | Cost (AI / Google / total) | Wall time | Result |
|---|---|---|---|---|---|---|---|
| Trip A (Europe) — primary | best library coverage; multi-city, trains, zips, photo | | | | | | |
| Trip B (Bali) | service voucher, boats, midnight arrival, Nusa Lembongan 0 restaurants | | | | | | |
| Trip C (Lisbon) | many timed experience bookings; Lisbon 0 restaurants → gap markers | | | | | | |
| Trip D (Istanbul) — after library data | | | | | | | |

## Re-QC of shipped guides (must catch the known errors)
| Guide | Known errors QC should catch | Caught? |
|---|---|---|
| Trip C (Lisbon) | 3 restaurants closed Sun 18 Oct; Matiz Lisboa twice on Day 1; planner commentary; 8 `utm_source=chatgpt.com` links | |
| Trip A (Europe) | impossible hours ("11:30 PM – 8:30 PM"); a 13-min walk; "Here are clear, step-by-step directions…" chatter; Day 2 header not a heading | |
| Trip B (Bali) | Important Places block headed with the wrong hotel | |
| Our own output (planted) | wrong weekday; 25-min walk; repeated restaurant; removed link | |

## Google Docs round trip (user)
- [ ] Upload `guide.docx` to Google Docs; confirm fonts, cards, links, TOC links, footer, markers survive.
- [ ] Download as .docx → save as `tests/aigv2/fixtures/google_roundtrip.docx`; run `pytest tests/aigv2/test_qc_rules.py -v` → PASS.
- [ ] Approve the generated cover (Task 17, ruling R6).

## Notes for decisions
- Luna writing quality vs "switch day writing to sol?" (§11b): _to fill after runs_.
- Google unit prices unconfirmed (see setup doc).
- Known QC limits: attraction travel legs not verified; `qc` needs `--run`.
- Domestic trips carry a `⚠ CHECK:` marker: altitude / remote area / sea travel not assessed.
