import json
import re
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from src.aigv2.library import diet_fits, norm_name
from src.aigv2.models import Marker
from src.aigv2.money import FxUnavailable, city_currency
from src.aigv2.writing import structured as st
from src.aigv2.writing.structured import App, Contact, Dish, EmergencyNumber, Phrase, Souvenir  # noqa: F401
from src.aigv2.writing.voice import SECTION_EXAMPLES, VOICE_RULE, first_person_problems

SECTION_KEYS = ("packing", "connectivity", "health", "getting_around", "dishes", "souvenirs", "etiquette",
                "safety", "money")
COUNTRY_KEYS = {"dishes", "souvenirs", "etiquette", "money", "connectivity", "safety"}
_DOMESTIC_OMIT = {"money", "connectivity", "health"}

_BOTH = lambda name: [("city", name), ("country", name)]
_LIB = {
    "dishes": [("city", "local_dishes")],
    "souvenirs": [("city", "souvenirs")],
    "etiquette": _BOTH("phrases") + [("country", "tipping"), ("country", "dos_donts")],
    "safety": _BOTH("safety_tips") + _BOTH("emergency_contacts") + [("country", "scams"), ("country", "embassies")],
    "connectivity": _BOTH("connectivity_tips") + [("country", "apps")],
    "getting_around": _BOTH("transport_options"),
    "health": _BOTH("health_tips") + [("country", "insurance")],
    "money": [("country", "money")],
    "packing": [],
}
_FOCUS = {
    "packing": "a tailored packing list for this season, these activities and these travellers; also cover plug type, "
               "travel insurance, visa documents and a weather/season line when the facts provide them",
    "connectivity": "mobile connectivity advice, including recommended apps",
    "health": "health and vaccination guidance",
    "getting_around": "how to get around, including transit cards and rail passes (how to use them, what they cover)",
    "dishes": "must-try local dishes, each with where to try it",
    "souvenirs": "a souvenir shopping guide",
    "etiquette": "cultural etiquette and local phrases, including tipping and dos and don'ts",
    "safety": "safety and emergency contacts, including common scams and the Indian embassy or consulate",
    "money": "money and payments: cards, ATMs, cash-only notes and forex cards (never state exchange rates)",
}
_SYSTEM = (
    "You are luna, the writer for Bon Voyage by Marina travel guides. Respond with a single JSON object "
    "{\"items\": [{\"heading\": str, \"body\": str, \"where_to_try\": [str]}]}. Write in American English, "
    "never salesy, with no emojis. " + VOICE_RULE + " " + SECTION_EXAMPLES + " Never write theme-park strategy tips unless the facts contain "
    "them. where_to_try is only used for dishes and may be empty."
)
_PROVIDERS = ("Airalo", "Holafly", "Tata AIG", "BookMyForex", "Niyo", "Viettel", "Dialog", "T-Mobile", "Vodafone",
              "Airtel", "Jio")
_CODES = {"USD", "EUR", "GBP", "INR", "JPY", "THB", "AED", "CHF", "TRY"}
_CODE_RE = "|".join(sorted(_CODES))
_PRICE = re.compile(rf"\d\s*(?:[€$£₹¥₺฿]|(?:{_CODE_RE}|Rs)\b)|(?:[€$£₹¥₺฿]|\b(?:{_CODE_RE}|Rs)\b\.?)\s*\d")
_PROVIDER = re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(p) for p in _PROVIDERS) + r")(?![A-Za-z])", re.I)
_SIM_BRAND = re.compile(r"\b[A-Z][A-Za-z0-9]+\s+e?SIM\b")
_THEME = re.compile(r"rope drop|fast ?pass|lightning lane|express pass|single rider", re.I)
_EMBASSY = re.compile(r"embass|consulate", re.I)


class SectionItem(BaseModel):
    heading: str
    body: str
    verify: bool = False


class SectionGroup(BaseModel):
    title: str
    items: list[SectionItem] = Field(default_factory=list)


class SectionContent(BaseModel):
    key: str
    items: list[SectionItem] = Field(default_factory=list)
    groups: list[SectionGroup] = Field(default_factory=list)
    apps: list[App] = Field(default_factory=list)
    phrases: list[Phrase] = Field(default_factory=list)
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    numbers: list[EmergencyNumber] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    dishes: list[Dish] = Field(default_factory=list)
    souvenirs: list[Souvenir] = Field(default_factory=list)
    from_library: bool = True
    by_country: dict[str, list[SectionItem]] = Field(default_factory=dict)
    markers: list[Marker] = Field(default_factory=list)


class _ItemOut(BaseModel):
    heading: str
    body: str
    where_to_try: list[str] = Field(default_factory=list)


class _GroupOut(BaseModel):
    title: str
    items: list[str] = Field(default_factory=list)


_JSON_IN_BODY = re.compile(r'"groups"\s*:|\{\s*"title"\s*:')


def _lift_groups(items: list[_ItemOut]):
    """Salvage groups JSON that the model put inside an item body: (groups, remaining items) or None."""
    dec = json.JSONDecoder()
    for n, it in enumerate(items):
        for m in re.finditer(r"\{", it.body):
            try:
                obj, _ = dec.raw_decode(it.body[m.start():])
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("groups"), list):
                try:
                    groups = [_GroupOut(**g) for g in obj["groups"]]
                except (TypeError, ValueError):
                    continue
                lead = it.body[:m.start()].strip()
                rest = items[:n] + ([_ItemOut(heading=it.heading, body=lead)] if lead else []) + items[n + 1:]
                return groups, rest
    return None


class _SectionOut(BaseModel):
    items: list[_ItemOut] = Field(default_factory=list)
    groups: list[_GroupOut] = Field(default_factory=list)

    @model_validator(mode="after")
    def _salvage_groups(self):
        if not self.groups:
            lifted = _lift_groups(self.items)
            if lifted:
                self.groups, self.items = lifted
        return self


def needs_verify(text: str) -> bool:
    return bool(_PRICE.search(text) or _PROVIDER.search(text) or _SIM_BRAND.search(text))


def _listify(v) -> list:
    if v is None or v == "" or v == []:
        return []
    return v if isinstance(v, list) else [v]


def _slice_country(country_data: dict, country: str) -> dict:
    for k, v in (country_data or {}).items():
        if isinstance(v, dict) and norm_name(k) == norm_name(country):
            return v
    return {}


def _countries(city_data: list[dict], country_data: dict) -> list[str]:
    out = list(dict.fromkeys(c["country"] for c in city_data if c.get("country")))
    return out or list(country_data or {}) or [""]


def _library_named(key: str, cities: list[dict], cdatas: list[dict], *,
                   nationalities: frozenset[str] = frozenset()) -> dict[str, list]:
    named: dict[str, list] = {}
    for scope, name in _LIB[key]:
        out = named.setdefault(name, [])
        if scope == "city":
            for c in cities:
                out += _listify(c.get(name))
        else:
            for cd in cdatas:
                items = _listify(cd.get(name))
                if name == "embassies":  # Indian by default; foreign missions only for that passport
                    items = [e for e in items if _embassy_wanted(e, nationalities)]
                out += items
    return named


def _library_items(key: str, cities: list[dict], cdatas: list[dict], *,
                   nationalities: frozenset[str] = frozenset()) -> list:
    return [x for v in _library_named(key, cities, cdatas, nationalities=nationalities).values() for x in v]


# (regex, nationality key) markers of a foreign mission in a library embassy entry
_FOREIGN_MARKERS = [
    (r"(?<![a-z])u\.s(?![a-z])", "us"), (r"\bus embassy", "us"), (r"united states", "us"), (r"american", "us"),
    (r"british", "uk"), (r"\buk embassy", "uk"), (r"canadian", "canada"), (r"australian", "australia"),
    (r"german embassy", "germany"), (r"french embassy", "france"), (r"japanese embassy", "japan"),
    (r"chinese embassy", "china"),
]
_CITIZEN_PHRASES = {
    "us": ["us citizen", "u.s. citizen", "us passport", "u.s. passport", "american citizen", "american passport",
           "united states citizen", "holds a us passport", "traveling on a us passport"],
    "uk": ["uk citizen", "british citizen", "british passport", "uk passport"],
}


def client_nationalities(trip) -> set[str]:
    text = " ".join(t for t in (getattr(trip, "additional_notes", ""), getattr(trip, "occasion", ""))
                    if isinstance(t, str)).casefold()
    return {k for k, phrases in _CITIZEN_PHRASES.items() if any(p in text for p in phrases)}


def _embassy_wanted(entry, nationalities) -> bool:
    if isinstance(entry, dict):
        text = " ".join(v for v in entry.values() if isinstance(v, str))
    else:
        text = str(entry)
    text = text.casefold()
    if "india" in text:
        return True
    found = {k for pat, k in _FOREIGN_MARKERS if re.search(pat, text)}
    return not found or found <= set(nationalities)


def _restaurant_names(cities: list[dict], diet) -> dict[str, str]:
    return {norm_name(r["name"]): r["name"] for c in cities for r in c.get("restaurants", [])
            if isinstance(r, dict) and r.get("name") and diet_fits(r, diet)}


def _trip_context(trip) -> str:
    dates = sorted(d.date for d in trip.days)
    cities = list(dict.fromkeys(h.city for h in trip.hotels))
    span = f"{dates[0]:%B %d} to {dates[-1]:%B %d, %Y}" if dates else "unknown dates"
    return (f"Trip: {', '.join(cities)}; {span}; scope {trip.trip_scope}; {trip.travellers.adults} adults, "
            f"children ages {trip.travellers.kids_ages or 'none'}; occasion {trip.occasion or 'none'}; "
            f"activities: {', '.join(i.name for d in trip.days for i in d.items if i.kind in ('attraction', 'activity'))[:600]}")


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def _validator(key: str, material: str, library: bool, restaurants: dict[str, str],
               allowed_hospitals: Optional[list[str]] = None, child: bool = False):
    known = _numbers(material)

    def validate(out: _SectionOut) -> list[str]:
        problems = []
        if not out.items and not (key == "packing" and out.groups):
            problems.append("items must not be empty")
        if key == "packing" and out.groups:
            problems += st.group_problems([g.title for g in out.groups], child)
            for g in out.groups:
                blob = g.title + " " + " ".join(g.items)
                problems += first_person_problems(f"group '{g.title}'", blob)
                if needs_verify(blob):
                    problems.append(f"group '{g.title}' contains prices or provider names")
                if library and not _numbers(blob) <= known:
                    problems.append(f"group '{g.title}' contains numbers that are not in the library facts")
        for it in out.items:
            blob = it.heading + " " + it.body
            if _JSON_IN_BODY.search(it.body):
                problems.append(f"'{it.heading}' body contains JSON; put groups in the top-level \"groups\" field and write plain text in bodies")
            problems += first_person_problems(f"'{it.heading}'", blob)
            if _THEME.search(blob) and not _THEME.search(material):
                problems.append(f"'{it.heading}' contains theme-park strategy not in the facts")
            if library and not _numbers(blob) <= known:
                problems.append(f"'{it.heading}' contains numbers that are not in the library facts")
            if allowed_hospitals is not None:
                extra = _unlisted_hospitals(blob, allowed_hospitals)
                if extra:
                    problems.append(f"'{it.heading}' names hospitals that Important Places does not list: {extra}")
            if key == "dishes":
                bad = [w for w in it.where_to_try if norm_name(w) not in restaurants]
                if bad:
                    problems.append(f"where_to_try names not in the library restaurants: {bad}")
        return problems

    return validate


def _rate_text(code: str, rate: float) -> str:
    if rate < 0.1:
        inv = 1 / rate
        digits = len(str(int(inv)))
        inv = round(inv, 2 - digits)
        return f"₹1 ≈ {int(inv):,} {code}"
    if rate >= 1:
        return f"1 {code} = ₹{rate:,.2f}"
    txt = f"{rate:.3g}"
    return f"1 {code} = ₹{txt}{'0' * (2 - len(txt.split('.')[1]))}"


_CHILD_RULE = ("Rule for motion sickness: a traveller is under 12, so ask your paediatrician before giving any "
               "motion-sickness medicine to a young child; non-drug options: ginger, a seat at the back or middle of "
               "the boat, fresh air, light meals; adults may carry tablets. Do not say to pack tablets for the child.")


def _child_rule(key: str, trip) -> str:
    if key in ("packing", "health") and any(a < 12 for a in trip.travellers.kids_ages):
        return "\n" + _CHILD_RULE
    return ""


def _fx_item(country: str, shard: dict, fx, today: date) -> Optional[SectionItem]:
    code = city_currency(country, shard)
    if code == "INR":
        return None
    if not code:
        return SectionItem(heading="Currency", body="Please confirm the local currency and today's exchange rate before you travel.", verify=True)
    label = f"Currency: {code}"
    try:
        rate = fx.rate(code, today) if fx else None
    except FxUnavailable:
        rate = None
    if rate is None:
        return SectionItem(heading=label, body="Please check today's exchange rate before you travel.", verify=True)
    return SectionItem(heading=label, body=f"{_rate_text(code, rate)}. Indicative rate (check before you travel).", verify=False)


def _is_indian_mission(it: SectionItem) -> bool:
    t = it.heading + " " + it.body
    return bool(_EMBASSY.search(t)) and "india" in t.casefold()


def _embassy(items: list[SectionItem], places, city: str, international: bool) -> list[SectionItem]:
    if places is None:
        return items
    out, found = [], False
    for it in items:
        if _is_indian_mission(it):
            found = True
            place = places.find(it.heading, city)
            if place is not None and place.match_ok:
                parts = [place.address] + ([f"Phone: {place.phone}"] if place.phone else [])
                it = SectionItem(heading=it.heading, body=". ".join(parts), verify=False)
            else:
                it = SectionItem(heading=it.heading, body=it.body, verify=True)
        out.append(it)
    if international and not found:
        place = places.find("Embassy of India", city)
        if place is not None and place.match_ok:
            body = ". ".join([place.address] + ([f"Phone: {place.phone}"] if place.phone else []))
            out.append(SectionItem(heading=place.name or "Embassy of India", body=body, verify=False))
        else:
            out.append(SectionItem(heading="Embassy of India",
                                   body="Please confirm the address and phone number of the nearest Indian embassy or consulate before you travel.",
                                   verify=True))
    return out


_HOSPITAL_MENTION = re.compile(
    r"(?:[A-Z][\w'’.&-]*\s+){0,4}(?:Hospital|Clinic|Medical\s+(?:Care|Cent(?:er|re))|Rumah\s+Sakit)(?:\s+[A-Z0-9][\w'’.&-]*){0,3}")


def hospital_mentions(text: str) -> list[str]:
    return [m.group(0).strip() for m in _HOSPITAL_MENTION.finditer(text or "")]


def _unlisted_hospitals(text: str, allowed: list[str]) -> list[str]:
    ok = [norm_name(a) for a in allowed]
    return [m for m in hospital_mentions(text) if not any(norm_name(m) in a or a in norm_name(m) for a in ok)]


def hospital_facts(important) -> list[dict]:
    """The Important Places hospital entries (nearest hospital Google found per stay) as plain facts."""
    out = []
    for e in important or []:
        h = getattr(e, "hospital", None)
        if h is None:
            continue
        out.append({"city": e.city, "near_hotel": e.hotel, "name": h.place.name, "address": h.place.address,
                    "opening_hours": h.hours_text, "drive_minutes": h.drive_min})
    return out


def _one(key: str, cities: list[dict], cdatas: list[dict], trip, llm, important=None):
    named = _library_named(key, cities, cdatas, nationalities=frozenset(client_nationalities(trip)))
    lib = [x for v in named.values() for x in v]
    hospitals = hospital_facts(important) if key == "safety" and important is not None else None
    allowed = [h["name"] for h in hospitals] if hospitals is not None else None
    if allowed is not None:  # library facts may not name a hospital other than the ones Important Places lists
        def listed(x):
            return not _unlisted_hospitals(json.dumps(x, ensure_ascii=False, default=str), allowed)
        lib = [x for x in lib if listed(x)]
        named = {k: [x for x in v if listed(x)] for k, v in named.items()}
    library = bool(lib)
    material = json.dumps(lib, ensure_ascii=False, default=str)
    restaurants = _restaurant_names(cities, trip.diet)
    extra = ""
    if key == "packing":
        extra = "\nCountry facts: " + json.dumps(cdatas, ensure_ascii=False, default=str)
    if key == "dishes":
        extra += "\nLibrary restaurants allowed in where_to_try: " + json.dumps(sorted(restaurants.values()), ensure_ascii=False)
    if hospitals is not None:
        extra += ("\nAuthoritative hospitals (the same ones listed under Important Places; hours and drive times as given): "
                  + json.dumps(hospitals, ensure_ascii=False, default=str)
                  + "\nName only these hospitals or clinics, and no others. Do not name any other hospital, clinic or "
                    "medical centre. If the list is empty, name no hospital.")
    mode = ("Format ONLY the library facts below into client-ready items. Add no facts, numbers, names or prices."
            if library else
            "No library facts exist. Write helpful general guidance, without exact prices, fees, times or provider names.")
    extra += _child_rule(key, trip)
    child = any(a < 12 for a in trip.travellers.kids_ages)
    if key == "packing":
        extra += _PACKING_GROUPS_RULE + (_CHILD_GROUP_RULE if child else " Do not include a 'For your little one' group.")
    prompt = (f"Section: {key}. Write {_FOCUS[key]}.\n{mode}\n{_trip_context(trip)}{extra}\n"
              f"Library facts (JSON): {material}")
    out = llm.run_json("write_sections", _SYSTEM, prompt, _SectionOut,
                       validate=_validator(key, material + extra, library, restaurants, allowed, child))
    flag_ai = not library and key != "packing"
    items = []
    for it in out.items:
        body = it.body
        if key == "dishes" and it.where_to_try:
            body += " Where to try: " + ", ".join(restaurants[norm_name(w)] for w in it.where_to_try) + "."
        items.append(SectionItem(heading=it.heading, body=body,
                                 verify=flag_ai or needs_verify(it.heading + " " + body)))
    fields: dict = {}
    if key == "packing" and out.groups:
        groups = st.order_groups(out.groups)
        fields["groups"] = [SectionGroup(title=g.title, items=[SectionItem(heading=i.strip(), body="")
                                                                for i in g.items if i.strip()][:8]) for g in groups]
        items = [SectionItem(heading=g.title, body=", ".join(i.heading for i in g.items)) for g in fields["groups"]]
    else:
        fields = st.extract(key, named, [r for c in cities for r in c.get("restaurants", [])
                                         if isinstance(r, dict) and r.get("name") and r["name"] in restaurants.values()])
    return items, library, fields


_PACKING_GROUPS_RULE = (
    "\nAlso return the packing list as \"groups\": [{\"title\": str, \"items\": [str]}] using only these titles, in this "
    "order, only when relevant: Clothing, Footwear, Beach & Island Days (only if the itinerary has water, boat or beach "
    "activities), Sun & Day Trips, Temple Visits (only if temples or religious sites appear), Electronics, Health & "
    "Comfort, Travel Documents. Each group has 3 to 8 short items, single phrases and not sentences, in the imperative or as "
    "noun phrases. Plug type and insurance facts from the library may go under Electronics and Travel Documents. "
    "items may then be empty.")
_CHILD_GROUP_RULE = " A traveller is under 12, so add a final group titled \"For your little one\"."

_REMOTE_GUIDANCE = [
    ("Altitude", "At high altitude, ascend gradually, drink plenty of water, rest on arrival and avoid alcohol on the first day. "
                 "If anyone develops a severe headache, breathlessness or confusion, descend and seek medical help."),
    ("Mountain roads", "Mountain roads can be narrow and affected by weather or landslides. Travel in daylight with an "
                       "experienced local driver and allow generous buffer time."),
    ("Low network", "Mobile coverage can be patchy or absent in remote areas. Download offline maps, keep key phone numbers "
                    "and bookings saved offline, and tell your hotel your route."),
]


def _merge_fields(parts: list[dict]) -> dict:
    merged: dict = {}
    for p in parts:
        for k, v in p.items():
            merged[k] = merged.get(k, []) + [x for x in v if x not in merged.get(k, [])]
    if "phrases" in merged:
        merged["phrases"] = merged["phrases"][:st.PHRASE_CAP]
    for k in ("dos", "donts"):
        if k in merged:
            merged[k] = merged[k][:st.DO_CAP]
    if "numbers" in merged:
        merged["numbers"] = merged["numbers"][:st.NUMBER_CAP]
    return merged


def write_section(key: str, city_data: list[dict], country_data: dict, trip, llm, *,
                  places=None, fx=None, today: Optional[date] = None,
                  remote_area: bool = False, high_altitude: bool = False, important=None) -> Optional[SectionContent]:
    if key not in SECTION_KEYS:
        raise ValueError(f"unknown section key: {key}")
    domestic = trip.trip_scope == "domestic"
    if domestic and key in _DOMESTIC_OMIT and not (remote_area or (key == "health" and high_altitude)):
        return None
    today = today or date.today()
    countries = _countries(city_data, country_data) if key in COUNTRY_KEYS else [""]
    grouped = key in COUNTRY_KEYS and len(countries) > 1
    by_country: dict[str, list[SectionItem]] = {}
    all_lib = True
    fields_by_country: list[dict] = []
    for country in countries:
        if key in COUNTRY_KEYS:
            cities = [c for c in city_data if not country or not c.get("country") or c["country"] == country]
            cdatas = [_slice_country(country_data, country)]
        else:
            cities = city_data
            cdatas = [_slice_country(country_data, c) for c in _countries(city_data, country_data)]
        items, library, fields = _one(key, cities, cdatas, trip, llm, important)
        fields_by_country.append(fields)
        all_lib = all_lib and library
        if key == "money" and not domestic:
            fx_item = _fx_item(country, next((c for c in cities if c.get("currency")), {}), fx, today)
            if fx_item:
                items.insert(0, fx_item)
        if key == "safety":
            city = next((c.get("city") for c in cities if c.get("city")), None) or (trip.hotels[0].city if trip.hotels else "")
            items = _embassy(items, places, city, not domestic)
            if domestic:
                extra = [SectionItem(heading="Emergency number", body="Dial 112 for police, fire and ambulance anywhere in India.")]
                if remote_area or high_altitude:
                    extra += [SectionItem(heading=h, body=b) for h, b in _REMOTE_GUIDANCE]
                items = extra + items
        by_country[country] = items
    flat = [i for items in by_country.values() for i in items]
    return SectionContent(key=key, items=flat, from_library=all_lib,
                          by_country=by_country if grouped else {}, **_merge_fields(fields_by_country))
