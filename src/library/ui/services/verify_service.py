"""AIG verification service — two-layer pipeline (rule engine + GPT AI pass)."""

from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass, field, asdict

from docx import Document
from openai import OpenAI


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    check_id: str
    layer: str          # "rule" | "ai"
    severity: str       # "RED" | "YELLOW"
    section: str
    description: str
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifyResult:
    findings: list[Finding]
    narratives: dict
    meta: dict

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "narratives": self.narratives,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# DOCX text extraction
# ---------------------------------------------------------------------------

def extract_paragraphs(docx_bytes: bytes) -> list[dict]:
    """Return list of {style, text} dicts from DOCX, skipping empty paragraphs."""
    doc = Document(io.BytesIO(docx_bytes))
    paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append({"style": para.style.name, "text": text})
    return paragraphs


def paragraphs_to_text(paragraphs: list[dict]) -> str:
    return "\n".join(p["text"] for p in paragraphs)


# ---------------------------------------------------------------------------
# Rule engine (R1–R10)
# ---------------------------------------------------------------------------

_AI_ARTIFACT_PATTERNS = [
    r"^here(?:'s| is) day \d",                              # start-of-line only
    r"sure[!,]?\s+here(?:'s| is)",
    r"i have generated",
    r"i['']ve generated",
    r"\bas an ai,\b",                                        # "as an AI, I ..." not "act as an AI"
    r"\bas an ai assistant\b",
    r"i['']ll (?:provide|create|generate|write|now write)",
    r"here(?:'s| is) the (?:complete|full|detailed|updated|revised)",
    r"^note:\s+this (?:guide|section|day|itinerary)",
    r"```",
    r"^in conclusion,",
]

_PLACEHOLDER_PATTERNS = [
    (r"\[hotel name\]", "hotel name placeholder"),
    (r"\[restaurant name\]", "restaurant name placeholder"),
    (r"\[insert [^\]]+\]", "INSERT placeholder"),
    (r"\[tbd\]", "TBD placeholder"),
    (r"\btbd\b", "TBD"),
    (r"\bxxxxx+\b", "XXXX placeholder"),
    (r"\[(?:city|destination|attraction|place) name\]", "destination placeholder"),
]

_MANDATORY_SECTIONS = [
    "Client Information",
    "Important Places Around Your Stay",
    "Souvenir Shopping Guide",
    "Must-Try Local Dishes",
    "Getting Around",
    "Cultural Etiquette",
    "Tailored Packing List",
    "Mobile Connectivity",
    "Safety & Emergency Contacts",
    "Health & Vaccination",
    "Thank You",
]

_WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Mon,", "Tue,", "Wed,", "Thu,", "Fri,", "Sat,", "Sun,",
]


def _r1_ai_artifacts(text: str, findings: list[Finding]) -> None:
    for pattern in _AI_ARTIFACT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 60)
            findings.append(Finding(
                check_id="R1",
                layer="rule",
                severity="RED",
                section="Entire document",
                description=f"AI meta-commentary or artifact text detected in document",
                evidence=text[start:end].strip(),
            ))
            return  # one R1 finding is enough


def _r2_placeholders(text: str, findings: list[Finding]) -> None:
    for pattern, label in _PLACEHOLDER_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            findings.append(Finding(
                check_id="R2",
                layer="rule",
                severity="RED",
                section="Entire document",
                description=f"Unfilled placeholder text found: {label}",
                evidence=m.group(),
            ))
            return


def _r3_mandatory_sections(text: str, findings: list[Finding]) -> None:
    for section in _MANDATORY_SECTIONS:
        if not re.search(re.escape(section), text, re.IGNORECASE):
            findings.append(Finding(
                check_id="R3",
                layer="rule",
                severity="RED",
                section="Document structure",
                description=f"Mandatory section missing: '{section}'",
                evidence="",
            ))


def _r4_r10_day_numbers(text: str, findings: list[Finding]) -> None:
    # Extract all day numbers from headings like "Day 1:", "Day 2 –", "Day 3 |"
    day_nums = [int(m.group(1)) for m in re.finditer(r"^Day (\d+)\s*[:|\-–]", text, re.MULTILINE)]
    if not day_nums:
        return
    unique_nums = sorted(set(day_nums))
    # Check for duplicates
    if len(day_nums) != len(unique_nums):
        from collections import Counter
        dupes = [n for n, c in Counter(day_nums).items() if c > 1]
        findings.append(Finding(
            check_id="R10",
            layer="rule",
            severity="RED",
            section="Day headings",
            description=f"Duplicate day number(s) found: Day {', '.join(str(d) for d in sorted(dupes))}",
            evidence=f"Day numbers found: {day_nums[:20]}",
        ))
    # Check for gaps (ignoring Day 0 as a pre-trip day)
    start = min(unique_nums)
    expected = list(range(start, max(unique_nums) + 1))
    missing = [n for n in expected if n not in unique_nums]
    if missing:
        findings.append(Finding(
            check_id="R4",
            layer="rule",
            severity="RED",
            section="Day-wise itinerary",
            description=f"Day number gap(s) detected: Day {', '.join(str(n) for n in missing)} missing",
            evidence=f"Day numbers present: {unique_nums}",
        ))


_WEEKDAY_RE = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon,|Tue,|Wed,|Thu,|Fri,|Sat,|Sun,)\b",
    re.IGNORECASE,
)


def _r5_day_heading_format(text: str, findings: list[Finding]) -> None:
    missing_weekday = []
    for m in re.finditer(r"^(Day \d+\s*[:|\-–].+)$", text, re.MULTILINE):
        heading = m.group(1)
        if not _WEEKDAY_RE.search(heading):
            missing_weekday.append(heading[:80])
    if missing_weekday:
        findings.append(Finding(
            check_id="R5",
            layer="rule",
            severity="YELLOW",
            section="Day headings",
            description=f"{len(missing_weekday)} day heading(s) are missing the day of week (e.g. 'Monday,')",
            evidence=missing_weekday[0],
        ))


def _count_maps_hyperlinks(docx_bytes: bytes) -> int:
    """Count Google Maps URLs stored as hyperlink relationships in the DOCX XML.

    python-docx paragraph.text never includes hyperlink URLs — they live in the
    OPC relationship store (part.rels), so plain-text scanning always returns 0.
    """
    doc = Document(io.BytesIO(docx_bytes))
    _MAPS_RE = re.compile(r"maps\.google\.com|maps\.app\.goo\.gl|goo\.gl/maps", re.IGNORECASE)
    count = sum(1 for r in doc.part.rels.values() if _MAPS_RE.search(r.target_ref))
    # Also check header/footer parts
    for part in doc.part.package.iter_parts():
        try:
            count += sum(1 for r in part.rels.values() if _MAPS_RE.search(r.target_ref))
        except Exception:
            pass
    return count


def _r6_maps_links(text: str, findings: list[Finding], maps_count: int = 0) -> None:
    count = maps_count or len(re.findall(r"maps\.google\.com|maps\.app\.goo\.gl|goo\.gl/maps", text, re.IGNORECASE))
    if count == 0:
        findings.append(Finding(
            check_id="R6",
            layer="rule",
            severity="YELLOW",
            section="Entire document",
            description="No Google Maps links found. Hotels, restaurants, and attractions should each have a Maps link.",
            evidence="",
        ))
    elif count < 5:
        findings.append(Finding(
            check_id="R6",
            layer="rule",
            severity="YELLOW",
            section="Entire document",
            description=f"Very few Maps links found ({count} total). Expected links on hotels, restaurants, and attractions.",
            evidence=f"Only {count} Maps link(s) in entire document",
        ))


def _r7_restaurant_count(text: str, findings: list[Finding]) -> None:
    # Split by day headings
    day_blocks = re.split(r"(?=^Day \d+\s*[:|\-–])", text, flags=re.MULTILINE)
    for block in day_blocks:
        day_match = re.match(r"^(Day \d+)", block)
        if not day_match:
            continue
        day_label = day_match.group(1)
        # Skip cruise/transit days
        if re.search(r"at sea|cruise day|in transit", block, re.IGNORECASE):
            continue
        # Count 🍴 restaurant entries
        restaurant_count = len(re.findall(r"🍴", block))
        # Only flag if day has some content but too few restaurants
        if 0 < restaurant_count < 3:
            findings.append(Finding(
                check_id="R7",
                layer="rule",
                severity="YELLOW",
                section=day_label,
                description=f"{day_label} has only {restaurant_count} restaurant recommendation(s); minimum 3 expected",
                evidence=f"Found {restaurant_count} 🍴 entries",
            ))


_TIME_RANGE_RE = re.compile(
    r"\b(\d{1,2}:\d{2})\s*(AM|PM)?\s*[–\-]\s*(\d{1,2}:\d{2})\s*(AM|PM)\b",
    re.IGNORECASE,
)
_MIDNIGHT_START_RE = re.compile(r"\b12:\d{2}\s*AM\s*[–\-]", re.IGNORECASE)
_SAME_TIME_RE = re.compile(
    r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\s*[–\-]\s*(\d{1,2}:\d{2}\s*(?:AM|PM))\b",
    re.IGNORECASE,
)
def _venue_name_before(text: str, pos: int) -> str:
    """Return the nearest venue-name line before `pos`.

    Venue names are standalone proper-noun lines: start with a capital letter,
    no leading emoji/symbol (any char > U+2000), no colon in the first 30 chars
    (which would indicate a label like "Best For: ..."), and not a description
    sentence starting with an article.
    """
    window = text[max(0, pos - 400):pos]
    lines = [l.strip() for l in window.splitlines()]
    for line in reversed(lines):
        if not line:
            continue
        if ord(line[0]) > 0x2000:          # emoji / special symbol prefix → skip
            continue
        if not line[0].isupper():           # must start with a capital letter
            continue
        if ":" in line[:30]:               # label line like "Best For: ..."
            continue
        if re.match(r"^(A |An |The )", line):  # description sentence starting with article
            continue
        if line.endswith(".") or line.endswith("!"):  # prose sentence
            continue
        return line
    return ""


def _r8_time_format(text: str, findings: list[Finding]) -> None:
    # Check 1: first time missing AM/PM when second has it ("12:00 – 11:00 PM")
    for m in _TIME_RANGE_RE.finditer(text):
        if not m.group(2):  # first time has no AM/PM
            full_match = m.group()
            venue = _venue_name_before(text, m.start())
            desc = f"Incomplete time format: '{full_match}' — opening time is missing AM/PM"
            if venue:
                desc = f"{venue}: {desc}"
            findings.append(Finding(
                check_id="R8",
                layer="rule",
                severity="RED",
                section="Opening hours",
                description=desc,
                evidence=full_match,
            ))
            break  # one finding of this type is enough

    # Check 2: midnight start like "12:30 AM – 10:30 PM" — almost always a typo for 12:30 PM
    for m in _MIDNIGHT_START_RE.finditer(text):
        venue = _venue_name_before(text, m.start())
        snippet = text[max(0, m.start() - 10):m.end() + 30].strip()
        desc = f"Opening time starts at midnight — almost certainly a typo for PM"
        if venue:
            desc = f"{venue}: opening time '{m.group().strip()}' starts at midnight — almost certainly a typo for PM"
        findings.append(Finding(
            check_id="R8",
            layer="rule",
            severity="RED",
            section="Opening hours",
            description=desc,
            evidence=snippet,
        ))
        break

    # Check 3: identical start and end time ("11:30 PM – 11:30 PM") — zero-duration or typo
    for m in _SAME_TIME_RE.finditer(text):
        t1 = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        t2 = re.sub(r"\s+", " ", m.group(2)).strip().upper()
        if t1 == t2:
            venue = _venue_name_before(text, m.start())
            desc = f"Opening hours '{m.group().strip()}' have identical start and end time — likely a typo (e.g. 11:30 AM – 11:30 PM intended)"
            if venue:
                desc = f"{venue}: opening hours '{m.group().strip()}' have identical start and end time — likely a typo (e.g. 11:30 AM – 11:30 PM intended)"
            findings.append(Finding(
                check_id="R8",
                layer="rule",
                severity="RED",
                section="Opening hours",
                description=desc,
                evidence=m.group(),
            ))
            break


_ENC_RE = re.compile(r'[�-￾﻿]')


def _r9_encoding(text: str, findings: list[Finding]) -> None:
    # � = Unicode replacement char (garbled byte during conversion)
    # - = Word/Symbol private-use glyphs (Wingdings etc.) that survive DOCX extraction
    # ￾/﻿ = reversed/regular BOM mid-document (encoding artefact)
    m = _ENC_RE.search(text)
    if m:
        start = max(0, m.start() - 30)
        snippet = text[start:m.end() + 30].strip()
        findings.append(Finding(
            check_id="R9",
            layer="rule",
            severity="YELLOW",
            section="Entire document",
            description="Broken or non-standard character encoding detected — clean up before sending to client",
            evidence=snippet or "Non-standard characters found",
        ))

def run_rule_engine(paragraphs: list[dict], maps_count: int = 0) -> list[Finding]:
    """Run all deterministic rule checks. Returns only failing checks."""
    text = paragraphs_to_text(paragraphs)
    findings: list[Finding] = []
    _r1_ai_artifacts(text, findings)
    _r2_placeholders(text, findings)
    _r3_mandatory_sections(text, findings)
    _r4_r10_day_numbers(text, findings)
    _r5_day_heading_format(text, findings)
    _r6_maps_links(text, findings, maps_count=maps_count)
    _r7_restaurant_count(text, findings)
    _r8_time_format(text, findings)
    _r9_encoding(text, findings)
    return findings


# ---------------------------------------------------------------------------
# AI pass (GPT structured output)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a professional quality control reviewer for "Bon Voyage by Marina", a luxury travel agency. \
You review All Inclusive Guides (AIGs) given to clients for real vacations. Mistakes harm clients and damage the agency's reputation.

You will receive the full text of an AIG. Review it against the checks below.
Return ONLY findings where an issue is present — do not list passing checks.
Every finding MUST include an "evidence" field: a verbatim quote from the document (max 300 chars) \
that supports the finding. If you cannot find direct supporting text, do not include the finding.

--- CHECKS ---

[A1] DIETARY VIOLATIONS — severity: RED
Are any food recommendations incompatible with the dietary preferences stated in the Client Information section?
A vegetarian client CAN dine at a restaurant that also serves non-vegetarian food, as long as the venue offers vegetarian options. Only flag if: (a) the restaurant is described as exclusively non-vegetarian with no vegetarian options, or (b) a specific non-vegetarian dish is directly recommended to a vegetarian/vegan/halal client.
Other examples of genuine violations: shellfish dish recommended to a client with a shellfish allergy; pork dish recommended to a halal client; non-halal restaurant with no halal options for a halal client.
Do NOT flag a restaurant merely because it is a multi-cuisine or mixed-menu restaurant.
Evidence: Quote the dietary preference and the specific offending recommendation.

[A2] EMERGENCY CONTACTS — severity: RED
Does Safety & Emergency Contacts have real, destination-specific numbers? \
A generic "Emergency: 112" with no country context fails. "Police: 110 (Japan)" passes.
Evidence: Quote the safety section.

[A3] WRONG DESTINATION CONTENT — severity: RED
Does any day's content describe a different destination? Flag copy-paste errors from other AIGs.
Evidence: Quote the mismatched text.

[A4] GUIDE TITLE — severity: YELLOW
Is the title creative and destination-specific? "All Inclusive Guide – Japan" fails. \
"Sakura Adventures: Journey Through Japan" passes.
Evidence: Quote the title.

[A5] PACKING LIST — severity: YELLOW
Is the packing list specific to this trip's season, destination, and activities — not a generic traveller list?
Evidence: Quote sample packing items.

[A6] FULL OPENING HOURS — severity: YELLOW
Do restaurant and place entries include specific opening times (not just "Mon–Sun" with no times)?
Evidence: Quote an entry with incomplete hours.

[A7] MEAL PROXIMITY — severity: YELLOW
Are lunch places near the day's attractions, and dinner places near the hotel? \
Flag clear mismatches (e.g., "45 min from hotel" for a dinner recommendation).
Evidence: Quote the proximity claim.

[A8] MUST-TRY DISHES COVERAGE — severity: YELLOW
Does the Must-Try Local Dishes section cover every destination city in the itinerary?
Evidence: Quote the section heading or note which city is absent.

[A9] GETTING AROUND COVERAGE — severity: YELLOW
Does Getting Around have transport options for each city visited?
Evidence: Quote the section or note the missing city.

[A10] CULTURAL ETIQUETTE — severity: YELLOW
Is the Cultural Etiquette section specific to the destinations, or generic boilerplate?
Evidence: Quote a sample from the section.

[A11] THANK YOU PERSONALIZATION — severity: YELLOW
Does the Thank You page use the client's actual name(s) from Client Information, or is it template text?
Evidence: Quote the Thank You text.

[A12] OVERALL COHERENCE — severity: YELLOW
Are there coherence issues: missing day narratives, broken sentences, duplicate paragraphs, or disjointed flow?
Evidence: Quote the problematic text.

[A13] HOURS LOGIC — severity: RED
Flag time ranges where the end time is BEFORE the start time within the same AM/PM period. \
E.g., "11 PM – 10 PM", "3:00 PM – 1:00 PM", "9:00 AM – 7:00 AM". \
Note: midnight starts (12:xx AM) and identical start/end times are already caught by separate rule checks — do NOT duplicate those findings here. Only flag end-before-start in the same AM/PM period.
Check EVERY venue's hours string — do not stop at the first issue.
Evidence: Quote the exact hours string.

[A14] DINNER VENUE HOURS — severity: RED
For every venue under "Dinner Recommendations", do hours extend past 7 PM? \
A dinner venue closing at 5 PM or 5:30 PM is a timing conflict.
Evidence: Quote the venue name and its hours.

[A15] SUNSET / TIME-OF-DAY ACCURACY — severity: RED
Are sunset viewing times, golden hour visits, and similar recommendations accurate for the destination \
and travel month? E.g., suggesting a 6 PM sunset in Amsterdam in July is wrong (sunset ≈ 9:45 PM there).
Evidence: Quote the recommendation and the stated time.

[A16] TRAVEL TIME PLAUSIBILITY — severity: RED
Are stated travel times between named locations realistic given the actual geography?
Evidence: Quote the exact travel time claim.

[A17] TRANSPORT PASS ACCURACY — severity: RED
Are transport pass coverage claims accurate? E.g., Nozomi bullet trains historically require a supplement \
on standard JR Passes — "covered under JR Pass" for Nozomi should be flagged.
Evidence: Quote the pass coverage claim.

[A18] IMPORTANT PLACES COMPLETENESS — severity: RED
For each hotel in the itinerary, does Important Places Around Your Stay include ALL of the following?
- Grocery store (with opening hours)
- Pharmacy — preferably 24-hour; if not, note the hours explicitly so clients know when it closes
- Hospital or emergency clinic capable of handling serious medical situations (not just a GP clinic)
- Distance or travel time from the hotel for each essential service
- A Google Maps link for each essential service (missing links on hospitals/pharmacies is a safety issue)
Flag any hotel stay where one or more of these requirements is absent or insufficient.
Evidence: Quote what is present, and specify exactly what is missing.

[A19] VENUE TYPE FOR MEAL — severity: YELLOW
Are dinner/lunch recommendations appropriate for that meal? A coffee café or dessert shop listed \
as a dinner recommendation is a weak choice even if technically open at dinner time.
Evidence: Quote the venue description and the meal slot it appears under.

[A20] DISTANCE REFERENCE ANCHORING — severity: YELLOW
Are distance/time references anchored to the correct preceding attraction or hotel? \
E.g., "18 min from Attraction B" for a lunch listed before visiting Attraction B in that day's sequence.
Evidence: Quote the distance claim in context.

[A21] ACTIVITY DAY-OF-WEEK VALIDATION — severity: RED
Many attractions are closed on specific weekdays. Cross-reference the day of the week stated in each day heading \
against the opening hours for that day's attractions. Flag any attraction scheduled on a day it is closed, \
or any weekly market/event scheduled on a day it does not operate.
Evidence: Quote the day heading and the conflicting hours or closure note.

[A22] RESERVATION DEPENDENCIES — severity: RED
Some attractions, experiences, and restaurants require advance booking, timed-entry tickets, or reservations. \
If the guide recommends such a venue without telling the client to book in advance, flag it. \
Examples that typically require advance booking: popular museums with timed entry, limited-capacity experiences \
(hot air balloon, glacier walk, cooking class), high-demand restaurants, cable cars with limited slots, \
iconic experiences like Ghibli Museum, TeamLab, Colosseum skip-the-line, etc. \
Use your knowledge of the destination to identify which recommended venues commonly require pre-booking.
Evidence: Quote the venue recommendation and confirm there is no booking note.

[A23] ARRIVAL / DEPARTURE DAY LOGIC — severity: RED
Arrival day: Check whether the planned activities are realistic given the stated or implied arrival time. \
If the client arrives in the afternoon or evening, a packed morning of sightseeing is wrong. \
Departure day: Check whether activities leave sufficient time to reach the airport or station. \
If a flight is at 6 PM and the last activity ends at 4 PM with a 1-hour transfer, that is dangerously tight. \
Flag any arrival or departure day where the activity schedule is incompatible with travel logistics.
Evidence: Quote the arrival/departure information and the conflicting activity schedule.

[A24] SEASONAL ACCURACY — severity: RED
Verify that seasonal experiences, natural phenomena, festivals, and weather-dependent recommendations \
align with the actual travel month stated in the itinerary. \
Examples of failures: tulip fields in Amsterdam in July (peak is April), autumn foliage in Japan in September \
(peak is late October–November), Northern Lights in Iceland in June (midnight sun, no aurora visible), \
cherry blossoms in Japan in July (peak is late March–April), whale watching in a location that is off-season. \
Use your knowledge of seasonal windows to flag recommendations that would disappoint or mislead the client.
Evidence: Quote the recommendation and state why it conflicts with the travel month.

[A25] REAL-WORLD EXECUTABILITY — severity: RED
Review each day as if you were personally taking this trip as a client. \
Flag anything that is technically possible but practically unreasonable for a real traveller: \
- Walking 40+ minutes to a dinner venue when alternatives exist nearby \
- Scheduling 6 or more major attractions in a single day with no realistic time buffer \
- Excessive backtracking across a city (visiting north, then south, then north again) \
- An activity sequence where travel time between consecutive venues makes the schedule unworkable \
- Recommending a venue that requires significant effort (long drive, permit, physical difficulty) without flagging it \
This is the check that catches itineraries that look fine on paper but would frustrate a real client.
Evidence: Quote the specific day, activity sequence, or venue that creates the problem.

--- OUTPUT ---
Return JSON only — no prose before or after.
The "description" field must be a specific, actionable sentence naming the exact venue/section/value that failed and why — never a generic statement like "there is an issue here". The "evidence" field must be a verbatim copy-paste from the document, not a paraphrase.

Example of a GOOD finding (specific, names the venue and exact hours):
{
  "check_id": "A14",
  "severity": "RED",
  "section": "Day 5 – Dinner (Kawaguchiko)",
  "description": "Momijitei-Hoto closes at 5:00 PM but is listed as a dinner recommendation — clients will arrive after it has closed.",
  "evidence": "🍴 Momijitei-Hoto  ⏰ Opening Hours: 10:30 AM – 5:00 PM"
}


Full response shape:
{
  "findings": [ ...zero or more finding objects as shown above... ],
  "narratives": {
    "overall": "e.g. Strong guide with 2 RED issues that must be fixed before sending. The most critical are a restaurant timing conflict on Day 3 and missing emergency numbers.",
    "days": "e.g. Day pacing is well structured for a family trip. Day 3 has a dinner venue that closes at 5 PM.",
    "restaurants": "e.g. Vegetarian options are present throughout. Two dinner venues have hours that end before dinner service.",
    "static_sections": "e.g. Packing list is season-specific. Safety section has real country numbers. Cultural etiquette is destination-specific."
  }
}
"""


def run_ai_pass(text: str) -> tuple[list[Finding], dict]:
    """Run GPT verification pass. Returns (findings, narratives)."""
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("AI_BASE_URL") or None
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)

    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )

    raw = response.choices[0].message.content.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI returned invalid JSON: {e}\n\nRaw output:\n{raw[:500]}") from e

    findings = []
    for item in data.get("findings") or []:
        check_id = item.get("check_id", "")
        severity = item.get("severity", "YELLOW")
        if severity not in ("RED", "YELLOW"):
            severity = "YELLOW"
        findings.append(Finding(
            check_id=check_id,
            layer="ai",
            severity=severity,
            section=item.get("section", ""),
            description=item.get("description", ""),
            evidence=item.get("evidence", ""),
        ))

    narratives = data.get("narratives") or {}
    for key in ("overall", "days", "restaurants", "static_sections"):
        narratives.setdefault(key, "")

    return findings, narratives


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify(docx_bytes: bytes) -> VerifyResult:
    """Run full verification pipeline on an AIG DOCX. Returns VerifyResult."""
    paragraphs = extract_paragraphs(docx_bytes)
    text = paragraphs_to_text(paragraphs)
    maps_count = _count_maps_hyperlinks(docx_bytes)

    rule_findings = run_rule_engine(paragraphs, maps_count=maps_count)
    ai_findings, narratives = run_ai_pass(text)

    all_findings = rule_findings + ai_findings
    red_count = sum(1 for f in all_findings if f.severity == "RED")
    yellow_count = sum(1 for f in all_findings if f.severity == "YELLOW")

    # Checks that passed = total checks - findings with issues
    all_check_ids = {
        "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10",
        "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10",
        "A11", "A12", "A13", "A14", "A15", "A16", "A17", "A18", "A19", "A20",
        "A21", "A22", "A23", "A24", "A25",
    }
    failed_ids = {f.check_id for f in all_findings}
    passed_count = len(all_check_ids - failed_ids)

    import os as _os
    model = _os.environ.get("AI_MODEL", "gpt-4o-mini")

    return VerifyResult(
        findings=all_findings,
        narratives=narratives,
        meta={
            "red_count": red_count,
            "yellow_count": yellow_count,
            "passed_count": passed_count,
            "model": model,
        },
    )
