"""Deterministic structured data for the reference sections (no LLM, nothing invented)."""
import re
from typing import Optional

from pydantic import BaseModel, Field

from src.aigv2.library import norm_name

PACKING_GROUPS = ("Clothing", "Footwear", "Beach & Island Days", "Sun & Day Trips", "Temple Visits", "Electronics",
                  "Health & Comfort", "Travel Documents", "For your little one")
CHILD_GROUP = "For your little one"

PHRASE_CAP, DO_CAP, SOUVENIR_CAP, NUMBER_CAP = 12, 8, 8, 4


class App(BaseModel):
    name: str
    purpose: str = ""


class Phrase(BaseModel):
    local: str
    english: str


class EmergencyNumber(BaseModel):
    service: str
    number: str


class Contact(BaseModel):
    name: str
    phone: str = ""
    note: str = ""
    kind: str = ""  # tourist_police | embassy | consulate


class Dish(BaseModel):
    name: str
    description: str = ""
    where_to_try: list[str] = Field(default_factory=list)


class Souvenir(BaseModel):
    title: str
    what: str
    places: list[str] = Field(default_factory=list)


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _dicts(items) -> list[dict]:
    return [x for x in items or [] if isinstance(x, dict)]


def extract_apps(items) -> list[App]:
    out, seen = [], set()
    for a in _dicts(items):
        n = _s(a.get("name"))
        if n and n.casefold() not in seen:
            seen.add(n.casefold())
            out.append(App(name=n, purpose=_s(a.get("purpose"))))
    return out


def extract_phrases(items) -> list[Phrase]:
    out, seen = [], set()
    for p in _dicts(items):
        loc, eng = _s(p.get("local")), _s(p.get("english"))
        if loc and eng and loc.casefold() not in seen:
            seen.add(loc.casefold())
            out.append(Phrase(local=loc, english=eng))
    return out[:PHRASE_CAP]


_DONT = re.compile(r"^\s*(?:don['’]t|do not|never|avoid|no)\b", re.I)


def extract_dos_donts(items) -> tuple[list[str], list[str]]:
    dos, donts, seen = [], [], set()
    for t in _dicts(items):
        tip = _s(t.get("tip"))
        if not tip or tip.casefold() in seen:
            continue
        seen.add(tip.casefold())
        (donts if _DONT.match(tip) else dos).append(tip)
    return dos[:DO_CAP], donts[:DO_CAP]


_NUMBER_KINDS = [("Police", re.compile(r"police", re.I)), ("Ambulance", re.compile(r"ambulance|medical", re.I)),
                 ("Fire", re.compile(r"\bfire\b", re.I)),
                 ("Search & Rescue", re.compile(r"rescue|basarnas|\bsar\b", re.I))]


def extract_numbers(items) -> list[EmergencyNumber]:
    out, taken = [], set()
    for e in _dicts(items):
        svc, num = _s(e.get("service")), _s(e.get("number"))
        if not svc or not num or re.search(r"tourist", svc, re.I):
            continue
        for kind, pat in _NUMBER_KINDS:
            if pat.search(svc) and kind not in taken:
                taken.add(kind)
                out.append(EmergencyNumber(service=svc, number=num))
                break
    return out[:NUMBER_CAP]


def extract_contacts(emergency, embassies) -> list[Contact]:
    out = []
    for e in _dicts(emergency):
        svc = _s(e.get("service"))
        if re.search(r"tourist", svc, re.I) and _s(e.get("number")):
            out.append(Contact(name=svc, phone=_s(e.get("number")), kind="tourist_police"))
    for e in _dicts(embassies):
        name = _s(e.get("name"))
        if not name:
            continue
        note = " — ".join(x for x in (_s(e.get("city")), _s(e.get("after_hours"))) if x)
        out.append(Contact(name=name, phone=_s(e.get("phone")), note=note,
                           kind="consulate" if re.search(r"consulate", name, re.I) else "embassy"))
    return out


def extract_dishes(items, restaurants: list[dict]) -> list[Dish]:
    """restaurants: library restaurant dicts already restricted to the allowed (diet-fitting) set."""
    out, seen = [], set()
    for d in _dicts(items):
        name = _s(d.get("name"))
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        key = norm_name(name)
        where = []
        for r in restaurants:
            must = r.get("must_try_dishes")
            blob = norm_name(" | ".join(must if isinstance(must, list) else [must] if isinstance(must, str) else []))
            if key and key in blob and r["name"] not in where:
                where.append(r["name"])
        out.append(Dish(name=name, description=_s(d.get("description")), where_to_try=where))
    return out


def extract_souvenirs(items) -> list[Souvenir]:
    groups: dict[str, dict] = {}
    for s in _dicts(items):
        item = _s(s.get("item"))
        if not item:
            continue
        g = groups.setdefault(_s(s.get("category")) or "Other", {"what": [], "places": []})
        if item not in g["what"]:
            g["what"].append(item)
        for w in s.get("where_to_buy") or []:
            if _s(w) and _s(w) not in g["places"]:
                g["places"].append(_s(w))
    return [Souvenir(title=t, what=", ".join(g["what"]), places=g["places"])
            for t, g in list(groups.items())[:SOUVENIR_CAP]]


def extract(key: str, named: dict[str, list], restaurants: list[dict]) -> dict:
    """Typed SectionContent fields for `key` from the (already filtered) named library lists."""
    if key == "connectivity":
        return {"apps": extract_apps(named.get("apps"))}
    if key == "etiquette":
        dos, donts = extract_dos_donts(named.get("dos_donts"))
        return {"phrases": extract_phrases(named.get("phrases")), "dos": dos, "donts": donts}
    if key == "safety":
        return {"numbers": extract_numbers(named.get("emergency_contacts")),
                "contacts": extract_contacts(named.get("emergency_contacts"), named.get("embassies"))}
    if key == "dishes":
        return {"dishes": extract_dishes(named.get("local_dishes"), restaurants)}
    if key == "souvenirs":
        return {"souvenirs": extract_souvenirs(named.get("souvenirs"))}
    return {}


def order_groups(groups):
    return sorted(groups, key=lambda g: PACKING_GROUPS.index(g.title))


def group_problems(titles: list[str], child: bool) -> list[str]:
    problems = [f"group title '{t}' is not allowed; use only {list(PACKING_GROUPS)}" for t in titles
                if t not in PACKING_GROUPS]
    if (CHILD_GROUP in titles) != child:
        problems.append(f"'{CHILD_GROUP}' must appear only when a traveller is under 12")
    return problems
