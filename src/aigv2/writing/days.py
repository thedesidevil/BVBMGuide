import json
import re
from typing import Optional

from pydantic import BaseModel, Field

from src.aigv2.library import norm_name

DAY_FACTS_KEYS = ("date", "city", "attractions", "restaurants", "travellers", "occasion")

_FACT_PATTERNS = [
    re.compile(r"\d\s*(?:min|mins|minutes?|hr|hrs|hours?)\b", re.I),
    re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)", re.I),
    re.compile(r"[€$£₹¥₺฿]"),
    re.compile(r"\bkm\b|\bmiles?\b", re.I),
    re.compile(r"%|\bpercent\b", re.I),
]

_SYSTEM = (
    "You are luna, the writer for Bon Voyage by Marina travel guides. Respond with a single JSON object only. "
    "Write in warm, first-person 'we' voice, in American English, never salesy, with no emojis. "
    "You may use ONLY the facts given. Do not invent or state times, durations, distances, prices, percentages or "
    "opening hours inside title, intro, description or free_time_idea. Use every attraction and restaurant name exactly "
    "as given and add no others. If you supply entry_fee, dress_code, tips, best_time or duration for an attraction "
    "they are unverified and will be flagged for a human, so leave them null unless you are confident. "
    "JSON shape: {\"title\": str, \"intro\": str, \"attractions\": [{\"name\": str, \"description\": str, "
    "\"entry_fee\": str|null, \"dress_code\": str|null, \"tips\": str|null, \"best_time\": str|null, "
    "\"duration\": str|null}], \"restaurants\": [{\"name\": str, \"ambience\": str, \"best_for\": str}], "
    "\"free_time_idea\": str|null}."
)


class AttractionText(BaseModel):
    name: str
    description: str
    entry_fee: Optional[str] = None
    dress_code: Optional[str] = None
    tips: Optional[str] = None
    best_time: Optional[str] = None
    duration: Optional[str] = None


class RestaurantText(BaseModel):
    name: str
    ambience: str
    best_for: str


class DayText(BaseModel):
    title: str
    intro: str
    attractions: list[AttractionText] = Field(default_factory=list)
    restaurants: list[RestaurantText] = Field(default_factory=list)
    free_time_idea: Optional[str] = None


def prose_fact_problems(label: str, text: Optional[str]) -> list[str]:
    if not text:
        return []
    return [f"{label} contains a time, price, distance or percentage: '{m.group(0)}'"
            for p in _FACT_PATTERNS for m in [p.search(text)] if m]


def _check_facts(day_facts: dict) -> None:
    missing = [k for k in DAY_FACTS_KEYS if k not in day_facts]
    if missing:
        raise ValueError(f"day_facts missing keys: {', '.join(missing)}")


def _names(items: list) -> list[str]:
    return [norm_name(i["name"]) for i in items]


def _validator(day_facts: dict):
    want_a, want_r = sorted(_names(day_facts["attractions"])), sorted(_names(day_facts["restaurants"]))

    def validate(day: DayText) -> list[str]:
        problems = []
        if sorted(norm_name(a.name) for a in day.attractions) != want_a:
            problems.append("attraction names must equal the input names exactly, with no additions or omissions")
        if sorted(norm_name(r.name) for r in day.restaurants) != want_r:
            problems.append("restaurant names must equal the input names exactly, with no additions or omissions")
        problems += prose_fact_problems("title", day.title)
        problems += prose_fact_problems("intro", day.intro)
        problems += prose_fact_problems("free_time_idea", day.free_time_idea)
        for a in day.attractions:
            problems += prose_fact_problems(f"description of {a.name}", a.description)
        for r in day.restaurants:
            problems += prose_fact_problems(f"ambience of {r.name}", r.ambience)
            problems += prose_fact_problems(f"best_for of {r.name}", r.best_for)
        return problems

    return validate


def write_day(day_facts: dict, llm) -> DayText:
    _check_facts(day_facts)
    prompt = "Verified facts for this day (JSON):\n" + json.dumps(day_facts, default=str, ensure_ascii=False)
    day = llm.run_json("write_days", _SYSTEM, prompt, DayText, validate=_validator(day_facts))
    canon_a = {norm_name(i["name"]): i["name"] for i in day_facts["attractions"]}
    canon_r = {norm_name(i["name"]): i["name"] for i in day_facts["restaurants"]}
    for a in day.attractions:
        a.name = canon_a[norm_name(a.name)]
    for r in day.restaurants:
        r.name = canon_r[norm_name(r.name)]
    return day
