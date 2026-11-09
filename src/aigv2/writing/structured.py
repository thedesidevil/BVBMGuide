"""Deterministic structured data for the reference sections (no LLM, nothing invented)."""
from src.aigv2.textnorm import fold
import re
from collections import Counter
from typing import Optional

from pydantic import BaseModel, Field

from src.aigv2.library import norm_name

PACKING_GROUPS = ("Clothing", "Footwear", "Beach & Island Days", "Sun & Day Trips", "Temple Visits", "Electronics",
                  "Health & Comfort", "Travel Documents", "For your little one")
CHILD_GROUP = "For your little one"

PHRASE_CAP, DO_CAP, SOUVENIR_CAP, NUMBER_CAP, DISH_CAP = 12, 8, 8, 4, 12
TRANSPORT_CAP, STEP_CAP, MONEY_TIPS_PER_GROUP = 8, 6, 4


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


class Para(BaseModel):
    heading: str
    body: str


class SimInfo(BaseModel):
    provider: str
    plan: str = ""
    options: str = ""


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _dicts(items) -> list[dict]:
    return [x for x in items or [] if isinstance(x, dict)]


def extract_apps(items) -> list[App]:
    out, seen = [], set()
    for a in _dicts(items):
        n = _s(a.get("name"))
        if n and fold(n) not in seen:
            seen.add(fold(n))
            out.append(App(name=n, purpose=_s(a.get("purpose"))))
    return out


# Library entries known to be mistranslated at ingest ("tempat" means place, "nyak" is not a word for yes).
KNOWN_BAD_PHRASES = {("tempat", "please"), ("nyak", "yes")}


def extract_phrases(items) -> list[Phrase]:
    out, seen = [], set()
    for p in _dicts(items):
        loc, eng = _s(p.get("local")), _s(p.get("english"))
        if (loc.casefold(), eng.casefold()) in KNOWN_BAD_PHRASES:
            continue
        if loc and eng and fold(loc) not in seen:
            seen.add(fold(loc))
            out.append(Phrase(local=loc, english=eng))
    return out[:PHRASE_CAP]


_STOP = frozenset("a an the and or of in on at to for with by from is are be as it its this that your you can may "
                  "not no but if into about".split())


def _content_words(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[^\W_]+", fold(text)) if w not in _STOP)


def near_duplicate(a: str, b: str, threshold: float = 0.6) -> bool:
    """Token Jaccard similarity of the content words (stop words removed) >= threshold."""
    x, y = _content_words(a), _content_words(b)
    if not x or not y:
        return fold(a) == fold(b)
    return len(x & y) / len(x | y) >= threshold


def dedupe_similar(tips: list[str]) -> list[str]:
    """Drop near-duplicates, keeping the first position but the shorter wording."""
    out: list[str] = []
    for t in tips:
        for i, o in enumerate(out):
            if near_duplicate(t, o):
                if len(t) < len(o):
                    out[i] = t
                break
        else:
            out.append(t)
    return out


_DONT = re.compile(r"^\s*(?:don['’]t|do not|never|avoid|no)\b", re.I)


def extract_dos_donts(items) -> tuple[list[str], list[str]]:
    dos, donts = [], []
    for t in _dicts(items):
        tip = _s(t.get("tip"))
        if tip:
            (donts if _DONT.match(tip) else dos).append(tip)
    return dedupe_similar(dos)[:DO_CAP], dedupe_similar(donts)[:DO_CAP]


_NUMBER_KINDS = [("Police", re.compile(r"police", re.I)), ("Ambulance", re.compile(r"ambulance|medical", re.I)),
                 ("Fire", re.compile(r"\bfire\b", re.I)),
                 ("Search & Rescue", re.compile(r"rescue|basarnas|\bsar\b", re.I))]


_GENERAL = {"112", "911", "999"}
_NON_EMERGENCY = re.compile(r"non[- ]?emergency|nhs", re.I)


def _short(num: str) -> Optional[str]:
    """A dial-able emergency number: 2 to 4 digits (17, 144, 3624); a long local line is not one."""
    digits = _digits(num)
    if 2 <= len(digits) <= 4 and re.fullmatch(r"[\d\s]+", num.strip()):
        return digits
    return num.strip() if num.strip().startswith("+") else None  # internationally formatted lines are kept as written


def extract_numbers(items) -> list[EmergencyNumber]:
    """Police / ambulance / fire from the library's emergency contacts. A country's own short number (17, 15, 18 in
    France) is preferred over the shared 112; 112 is listed once as the all-purpose line."""
    votes: dict[str, Counter] = {k: Counter() for k, _ in _NUMBER_KINDS}
    labels: dict[tuple[str, str], str] = {}
    general = False
    for e in _dicts(items):
        svc, num = _s(e.get("service")), _s(e.get("number"))
        d = _short(num) if num else None
        if not svc or not d or re.search(r"tourist", svc, re.I) or _NON_EMERGENCY.search(svc):
            continue
        if d == "112":
            general = True
        for kind, pat in _NUMBER_KINDS:
            if pat.search(svc):
                votes[kind][d] += 1
                labels.setdefault((kind, d), svc)
                break
    out, used = [], set()
    for kind, _ in _NUMBER_KINDS:
        own = [(n, d) for d, n in votes[kind].items() if d not in _GENERAL]
        if own:
            d = max(own, key=lambda x: x[0])[1]
            out.append(EmergencyNumber(service=kind, number=d))
            used.add(d)
    if general:
        out.append(EmergencyNumber(service="Emergency (all services)", number="112"))
    return out[:NUMBER_CAP]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def extract_contacts(emergency, embassies) -> list[Contact]:
    out = _extract_contacts(emergency, embassies)
    seen, uniq = {}, []
    for c in out:  # the same mission/line often arrives from several source guides
        key = _digits(c.phone) if c.phone else (c.kind, fold(c.name))
        if c.phone and c.kind == "tourist_police":
            key = ("tp", key)
        if key not in seen:
            seen[key] = len(uniq)
            uniq.append(c)
        elif c.kind == "consulate" and uniq[seen[key]].kind == "embassy":
            uniq[seen[key]] = c  # a consulate sharing an embassy's line is the accurate name
    return uniq


def _extract_contacts(emergency, embassies) -> list[Contact]:
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


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", norm_name(text))


def _same_dish(dish: str, entry: str) -> bool:
    a, b = _words(dish), _words(entry)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 2:
        return False
    return any(long_[i:i + len(short)] == short for i in range(len(long_) - len(short) + 1))


def extract_dishes(items, restaurants: list[dict]) -> list[Dish]:
    """restaurants: library restaurant dicts already restricted to the allowed (diet-fitting) set."""
    out, seen = [], set()
    allowed = {norm_name(r["name"]): r["name"] for r in restaurants if r.get("name")}
    for d in _dicts(items):
        name = _s(d.get("name"))
        if not name or fold(name) in seen:
            continue
        seen.add(fold(name))
        where = []
        for r in restaurants:
            must = r.get("must_try_dishes")
            entries = must if isinstance(must, list) else [must] if isinstance(must, str) else []
            if any(_same_dish(name, e) for e in entries if isinstance(e, str)) and r["name"] not in where:
                where.append(r["name"])
        own = d.get("where_to_try")  # the library dish's own list, kept only for allowed restaurants
        for w in re.split(r"\s*[,;]\s*", own) if isinstance(own, str) else [x for x in own or [] if isinstance(x, str)]:
            hit = allowed.get(norm_name(w))
            if hit and hit not in where:
                where.append(hit)
        out.append(Dish(name=name, description=_s(d.get("description")), where_to_try=where))
    # keep the dishes that say where to try them first (stable), then the order given
    return sorted(out, key=lambda d: not d.where_to_try)[:DISH_CAP]


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


_MONEY_GROUPS = [("Currency exchange", re.compile(r"exchange|forex|money changer|changer", re.I)),
                 ("ATMs", re.compile(r"\batms?\b|cash machine", re.I)),
                 ("Cards", re.compile(r"\bcards?\b|contactless", re.I)),
                 ("Cash", re.compile(r"\bcash\b|small notes|small change", re.I)),
                 ("Tipping", re.compile(r"\btips?\b|tipping", re.I))]
MONEY_ORDER = ["Cards", "Cash", "ATMs", "Currency exchange", "Tipping", "Good to know"]


def _sentence(t: str) -> str:
    t = t.strip()
    return t if t[-1:] in ".!?" else t + "."


def _drop_contained(tips: list[str]) -> list[str]:
    """Drop a tip whose normalised text is contained in another (keeping the longer) or near-duplicates."""
    out: list[str] = []
    for t in tips:
        n = norm_name(t)
        for i, o in enumerate(out):
            m = norm_name(o)
            if n in m or m in n or near_duplicate(t, o):
                if len(t) > len(o) and (n in m or m in n):
                    out[i] = t
                elif len(t) < len(o) and not (n in m or m in n):
                    out[i] = t
                break
        else:
            out.append(t)
    return out


def extract_money(items) -> list[Para]:
    """Library money tips grouped into titled paragraphs by keyword; nothing is rewritten."""
    tips = _drop_contained([x for x in (_s(t.get("tip")) for t in _dicts(items)) if x])
    groups: dict[str, list[str]] = {}
    for t in tips:
        title = next((g for g, pat in _MONEY_GROUPS if pat.search(t)), "Good to know")
        groups.setdefault(title, []).append(t)
    return [Para(heading=g, body=" ".join(_sentence(t) for t in groups[g][:MONEY_TIPS_PER_GROUP]))
            for g in MONEY_ORDER if g in groups]


def _mode_words(mode: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[^\W_]+", mode.casefold()) if w not in ("and", "or", "the"))


def extract_transport(items) -> list[Para]:
    """One paragraph per mode; modes whose words are contained in another's (Grab / Grab and Gojek) are merged."""
    merged: list[dict] = []
    for o in _dicts(items):
        mode = _s(o.get("mode"))
        words = _mode_words(mode)
        if not words:
            continue
        # a route-specific mode ('Train to Zurich') never absorbs a generic one ('Train'): its text would be another route's
        m = next((x for x in merged if (words <= x["w"] or x["w"] <= words)
                  and (words == x["w"] or ("to" in words) == ("to" in x["w"]))), None)
        if m is None:
            m = {"mode": mode, "w": words, "desc": "", "how": ""}
            merged.append(m)
        elif len(words) > len(m["w"]):
            m["mode"], m["w"] = mode, words
        for k, f in (("desc", "description"), ("how", "how_to_use")):
            v = _s(o.get(f))
            if len(v) > len(m[k]):
                m[k] = v
    out = []
    for m in merged:
        body = " ".join(_sentence(x) for x in (m["desc"], m["how"]) if x)
        if body:
            out.append(Para(heading=m["mode"], body=body))
    return out[:TRANSPORT_CAP]


_IMPERATIVE = re.compile(r"^(activate|test|check|make sure|ensure|confirm|turn|switch|connect|install|download|keep|"
                         r"carry|show|bring|buy|pick|ask|use|set|scan|register|insert|restart|save|top)\b", re.I)


def extract_sim(items) -> tuple[list[SimInfo], list[str]]:
    """(SIM facts, imperative airport steps) from the library connectivity tips."""
    tips = [t for t in _dicts(items) if _s(t.get("provider"))]
    first = next((t for t in tips if _s(t.get("kind")).casefold() == "sim"), None)
    if not first:
        return [], []
    prov = _s(first.get("provider"))
    kinds = {_s(t.get("kind")).casefold() for t in tips if _s(t.get("provider")).casefold() == prov.casefold()}
    options = "SIM or eSIM" if {"sim", "esim"} <= kinds else "SIM"
    plan = re.sub(r"^\s*suggested data plan\s*:\s*", "", _s(first.get("price_text")), flags=re.I)
    steps: list[str] = []
    for t in tips:
        if _s(t.get("provider")).casefold() != prov.casefold():
            continue
        for sent in re.split(r"(?<=[.!?])\s+", _s(t.get("notes"))):
            sent = sent.strip().rstrip(".")
            if sent and _IMPERATIVE.match(sent) and sent.casefold() not in {x.casefold() for x in steps}:
                steps.append(sent[0].upper() + sent[1:])
    return [SimInfo(provider=prov, plan=plan, options=options)], steps[:STEP_CAP]


def extract(key: str, named: dict[str, list], restaurants: list[dict]) -> dict:
    """Typed SectionContent fields for `key` from the (already filtered) named library lists."""
    if key == "connectivity":
        sims, steps = extract_sim(named.get("connectivity_tips"))
        return {"apps": extract_apps(named.get("apps")), "sims": sims, "steps": steps}
    if key == "money":
        return {"money": extract_money((named.get("money") or []) + (named.get("tipping") or []))}
    if key == "getting_around":
        return {"transport": extract_transport(named.get("transport_options"))}
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
