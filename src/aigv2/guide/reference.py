"""Structured reference-section components (packing, money, apps, dishes, ...). Nothing here invents text."""
import re
from typing import Optional

from src.aigv2.guide import model as g
from src.aigv2.guide.dedupe import distinct, souvenir_items, split_top_level
from src.aigv2.library import norm_name
from src.aigv2.render.sections_render import search_url
from src.aigv2.writing.sections import SectionContent, SectionItem
from src.aigv2.writing.structured import CHILD_GROUP

_BOAT_HEAD = re.compile(r"boat|ferry|crossing|motion|sea", re.I)
_PAED = re.compile(r"paediatrician|pediatrician", re.I)
_PHRASE_ITEM = re.compile(r"phrases", re.I)
_APPS_ITEM = re.compile(r"\bapps\b", re.I)
_NUMBERS_ITEM = re.compile(r"emergency numbers?", re.I)
_CONSULAR_ITEM = re.compile(r"consul|embass", re.I)
_MARKET = re.compile(r"tipping|market|bargain", re.I)
_EYEBROW = {"tourist_police": "TOURIST POLICE", "consulate": "INDIAN CONSULATE", "embassy": "EMBASSY"}
_CONTACT_RANK = {"tourist_police": 0, "consulate": 1, "embassy": 2}
CONTACT_CAP = 3
_NOT_ETIQUETTE = re.compile(r"\barrive\b[^.]*\b(?:airport|before the flight)\b|\bcheck-?in\b", re.I)
_DIAL = re.compile(r"^\+(\d{1,4})(?=[\s\-()]|$)")


def _is_boat(i: SectionItem) -> bool:
    return bool(_BOAT_HEAD.search(i.heading) or _PAED.search(i.body))


def paras(items: list[SectionItem]) -> list[g.TitledPara]:
    return [g.TitledPara(heading=i.heading, body=i.body) for i in items]


_META = re.compile(r"\bprovider handles transport only\b|\bwithout (?:a )?guide\b|\bincluded in your package\b|"
                   r"\bhotel[- ]bookings?\b|\bbooking via the hotel\b|\bbook(?:ed)? transport via (?:the )?hotel\b|"
                   r"\bswitch things around\b|\bvoucher\b|\blocal partner arranges\b|\bservice (?:is )?provided by\b|"
                   r"\bbooked (?:through|with|via)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")
_FILL = {"the", "a", "an", "and", "of", "to", "in", "at", "for", "with", "use", "only", "your", "you", "is", "are"}
_STEM = {"authorised": "authorized", "authorised": "authorized"}


def _sent_key(sentence: str) -> frozenset:
    ws = re.findall(r"[^\W_]+", sentence.casefold())
    return frozenset(w[:-1] if len(w) > 4 and w.endswith("s") else w for w in ws if w not in _FILL)


def dedupe_sentences(items: list[SectionItem], *, meta: bool = True) -> list[SectionItem]:
    """Sentence-level dedupe across a section's paragraphs: a sentence whose key words are all inside an already
    kept sentence (or that repeats one) is dropped, operator/voucher meta sentences are filtered out, and a paragraph
    left with nothing is removed. No text is rewritten."""
    sents = [[x.strip() for x in _SENT.split(it.body.strip()) if x.strip()] for it in items]
    keys = [[_sent_key(x) for x in ss] for ss in sents]
    flat = [(i, j, k) for i, ks in enumerate(keys) for j, k in enumerate(ks)]
    out: list[SectionItem] = []
    for i, it in enumerate(items):
        kept = []
        for j, sent in enumerate(sents[i]):
            if meta and _META.search(sent):
                continue
            k = keys[i][j]
            if k and any((i2, j2) != (i, j) and k <= k2 and (k < k2 or (i2, j2) < (i, j))
                         and not (meta and _META.search(sents[i2][j2])) and (len(k) >= 3 or k == k2)
                         for i2, j2, k2 in flat):
                continue
            kept.append(sent)
        if kept:
            out.append(it.model_copy(update={"body": " ".join(kept)}))
    return out


def _titled(items: list[SectionItem]) -> list:
    return [g.TitledParas(items=paras(items))] if items else []


def known_places(data) -> dict[str, str]:
    """norm name -> maps url for every resolved place in the trip data."""
    out: dict[str, str] = {}
    for d in data.days:
        for p in d.places.values():
            if p and p.maps_url:
                out.setdefault(norm_name(p.name), p.maps_url)
        for mp in d.meals:
            for c in mp.restaurants:
                if c.place.maps_url:
                    out.setdefault(norm_name(c.place.name), c.place.maps_url)
                    lname = c.lib.get("name") if isinstance(c.lib, dict) else None
                    if lname:
                        out.setdefault(norm_name(str(lname)), c.place.maps_url)
    return out


def _city(data) -> str:
    return data.days[0].city if data.days else ""


def _link(name: str, data, places: dict[str, str]) -> g.Link:
    return g.Link(text=name, url=places.get(norm_name(name)) or search_url(name, _city(data)))


def _packing(c: SectionContent, data) -> list:
    groups = [g.ChecklistGroup(title=x.title, items=[i.heading for i in x.items])
              for x in c.groups if x.title != CHILD_GROUP and x.items]
    out: list = [g.ChecklistGroups(groups=groups)] if groups else []
    for x in c.groups:
        if x.title == CHILD_GROUP and x.items:
            out.append(g.TipPanel(title=CHILD_GROUP, items=[i.heading for i in x.items], columns=2, checks=True))
    return out if c.groups else out + _titled(c.items)  # items only summarise the groups: fallback when none


def _money(c: SectionContent, data) -> list:
    fx = next((i for i in c.items if i.heading.startswith("Currency") and not i.verify
               and "Indicative rate" in i.body), None)
    body = dedupe_sentences([i for i in c.items if i is not fx])
    lib = _clean_paras(c.money)
    if not fx:
        return [g.TitledParas(items=lib)] if lib else _titled(c.items)
    facts = []
    if ":" in fx.heading:
        facts.append(g.Fact(label="Currency", value=fx.heading.split(":", 1)[1].strip()))
    i = fx.body.index("Indicative rate")
    rate = fx.body[:i].strip()
    facts.append(g.Fact(label="Indicative rate", value=rate.rstrip(" .") or fx.body))
    out: list = [g.FactRowBlock(facts=facts)] + ([g.TitledParas(items=lib)] if lib else _titled(body))
    note = "Indicative rate; check before you travel."
    out.append(g.NotePanel(title="PLEASE NOTE", text=note))
    return out


def _connectivity(c: SectionContent, data) -> list:
    out: list = []
    if c.sims:
        s = c.sims[0]
        facts = [g.Fact(label="Recommended provider", value=s.provider)]
        if s.plan:
            facts.append(g.Fact(label="Suggested data plan", value=s.plan))
        if s.options:
            facts.append(g.Fact(label="Options", value=s.options))
        out.append(g.FactRowBlock(facts=facts))
    out += _titled(dedupe_sentences([i for i in c.items if not (c.apps and _APPS_ITEM.search(i.heading))]))
    if c.steps:
        out.append(g.TipPanel(title="Before you leave the airport", items=c.steps, columns=2, checks=True))
    if c.apps:
        out.append(g.AppGrid(apps=[g.App(name=a.name, use=a.purpose) for a in c.apps]))
    return out


def _clean_paras(ps: list) -> list:
    items = dedupe_sentences([SectionItem(heading=p.heading, body=p.body) for p in ps])
    seen_head, out = set(), []
    for i in items:  # two paragraphs left with the same heading text are one
        if norm_name(i.heading) in seen_head:
            continue
        seen_head.add(norm_name(i.heading))
        out.append(g.TitledPara(heading=i.heading, body=i.body))
    return out


def _getting_around(c: SectionContent, data) -> list:
    out = _clean_paras(c.transport)
    return [g.TitledParas(items=out)] if out else []


def _health(c: SectionContent, data) -> list:
    boat = [i for i in c.items if _is_boat(i)]
    rest = [i for i in c.items if i not in boat]
    out = _titled(rest)
    if boat:
        sents = [s.strip() for b in boat for s in re.split(r"(?<=\.) ", b.body) if s.strip()]
        out.append(g.NotePanel(title="BOAT CROSSINGS", items=sents))
    return out


_PORK = re.compile(r"\bpork\b|\bbabi\b|\bbacon\b|\bham\b", re.I)
_DISH_STOP = {"the", "a", "an", "of", "and", "with", "or", "in", "bali", "balinese", "indonesian", "traditional",
              "classic", "style", "local"}
DISH_CAP = 12


def trip_restaurants(data) -> dict[str, str]:
    """norm name -> display name for every restaurant picked in this guide's day meal blocks."""
    out: dict[str, str] = {}
    for d in data.days:
        for mp in d.meals:
            for c in mp.restaurants:
                for n in (c.lib.get("name") if isinstance(c.lib, dict) else None, c.place.name):
                    if n:
                        out.setdefault(norm_name(str(n)), str(c.lib.get("name") or n))
    return out


def _dish_key(name: str) -> frozenset:
    """Canonical key: the words of the dish name plus any bracketed alias, minus filler words."""
    words = re.findall(r"[^\W_]+", norm_name(name))
    return frozenset(w for w in words if w not in _DISH_STOP)


def dedupe_dishes(dishes: list) -> list:
    """Drop a dish whose canonical word set is contained in another kept dish's (Nasi Campur / Nasi Campur Bali;
    Sate Lilit / Balinese Chicken Satay (Sate Lilit)); the more complete entry wins, order is kept."""
    keys = [_dish_key(d.name) for d in dishes]
    keep = [True] * len(dishes)
    for i, ki in enumerate(keys):
        for j, kj in enumerate(keys):
            if i != j and keep[j] and ki and ki <= kj and (ki < kj or j < i):
                keep[i] = False
                break
    return [d for d, k in zip(dishes, keep) if k]


def _dishes(c: SectionContent, data) -> list:
    if not c.dishes:
        return _titled(c.items)
    pl = known_places(data)
    mine = trip_restaurants(data)
    # merge the where-to-try lists of duplicates into the surviving entry
    survivors = dedupe_dishes(c.dishes)
    for s in survivors:
        for d in c.dishes:
            if d is not s and _dish_key(d.name) and _dish_key(d.name) <= _dish_key(s.name):
                s.where_to_try = [*s.where_to_try, *[w for w in d.where_to_try if w not in s.where_to_try]]
    out = []
    for d in survivors[:DISH_CAP]:
        where = [mine[norm_name(n)] for n in d.where_to_try if norm_name(n) in mine]
        desc = d.description
        if _PORK.search(f"{d.name} {desc}") and not re.search(r"contains pork", desc, re.I):
            desc = (desc.rstrip() + ("\n" if desc.strip() else "")) + "Contains pork."
        out.append(g.Dish(name=d.name, desc=desc, where=[_link(n, data, pl) for n in dict.fromkeys(where)]))
    return [g.DishGrid(dishes=out)]


_NO_SOUVENIR = re.compile(r"kopi\s*luwak|luwak|civet", re.I)
_CAT_STOP = {"and", "the", "of", "a", "an", "traditional", "local", "balinese"}
_CAT_SYN = {"decor": "home", "décor": "home", "furnishing": "home", "craft": "handicraft", "handicrafts": "handicraft",
            "crafts": "handicraft", "textiles": "textile", "fabric": "textile", "fashion": "textile",
            "clothing": "textile", "clothes": "textile", "accessories": "accessory", "bags": "accessory"}
SOUVENIR_CATEGORY_CAP = 6


def _cat_words(title: str) -> frozenset:
    ws = [w for w in re.findall(r"[^\W_]+", title.casefold()) if w not in _CAT_STOP]
    return frozenset(_CAT_SYN.get(w, w) for w in ws)


def _fragments(what: str) -> list[str]:
    return [f for f in split_top_level(what) if f.strip() and not _NO_SOUVENIR.search(f)]


def merge_souvenirs(cats: list) -> list[tuple[str, str, list[str]]]:
    """(title, what, places) per merged category. Categories sharing a synonym-folded title word merge (the first
    title is kept), Kopi Luwak lines are dropped, a mixed fragment such as 'Snacks and clothing' moves to the
    category it names (or is cut to its first part), and places are unioned. First-appearance order."""
    merged: list[dict] = []
    for s in cats:
        if _NO_SOUVENIR.search(s.title):
            continue
        merged.append({"title": s.title, "words": set(_cat_words(s.title)), "what": _fragments(s.what),
                       "places": [p for p in s.places if p.strip()]})
    changed = True
    while changed:  # transitive: 'Home decor' + 'Handicrafts' + 'Handicrafts & Home decor' end up as one
        changed = False
        for i, a in enumerate(merged):
            b = next((m for m in merged[i + 1:] if m["words"] & a["words"]), None)
            if b is not None:
                a["words"] |= b["words"]
                a["what"] += b["what"]
                a["places"] += b["places"]
                merged.remove(b)
                changed = True
                break
    for m in merged:
        for frag in list(m["what"]):
            parts = re.split(r"\s+and\s+", frag, maxsplit=1)
            if len(parts) == 2 and _cat_words(parts[1]) and not (_cat_words(parts[1]) & m["words"]):
                m["what"].remove(frag)
                m["what"].append(parts[0].strip())
                other = next((o for o in merged if o is not m and o["words"] & _cat_words(parts[1])), None)
                if other is not None:
                    other["what"].append(parts[1].strip())
    out = []
    for m in merged:
        what = distinct([w for w in m["what"] if w.strip()], 8)
        if what:
            out.append((m["title"], ", ".join(what), list(dict.fromkeys(m["places"]))))
    return out


def _souvenirs(c: SectionContent, data) -> list:
    if not c.souvenirs:
        return _titled(c.items)
    pl = known_places(data)
    def place_names(names):
        keep = set(distinct([n for n in names if n.strip()]))
        return [n for n in names if n.strip() and (n[0].upper() + n[1:]) in keep]
    merged = merge_souvenirs(c.souvenirs)
    return [g.SouvenirGrid(categories=[
        g.Souvenir(title=title, what=", ".join(souvenir_items(what)) or what,
                   places=[_link(n, data, pl) for n in place_names(places)])
        for title, what, places in merged[:SOUVENIR_CATEGORY_CAP]])]


def _etiquette(c: SectionContent, data) -> list:
    out: list = []
    if c.dos or c.donts:
        out.append(g.DosDonts(do=distinct([x for x in c.dos if not _NOT_ETIQUETTE.search(x)]),
                              dont=distinct(c.donts)))
    if c.phrases:
        out.append(g.PhraseTable(phrases=[g.Phrase(local=p.local, english=p.english) for p in c.phrases]))
    if not out:
        return _titled(c.items)
    market = [i for i in c.items if _MARKET.search(i.heading)]
    if market:
        out.append(g.NotePanel(title="MARKETS AND TIPPING", items=[f"{i.heading}: {i.body}" for i in market]))
    def dup(i):  # prose that only repeats the phrase table
        return bool(c.phrases and _PHRASE_ITEM.search(i.heading))
    return out + _titled(dedupe_sentences([i for i in c.items if i not in market and not dup(i)], meta=False))


def _dial(c: SectionContent, data) -> Optional[str]:
    nums = [n.number for n in c.numbers] + [x.phone for x in c.contacts]
    for s in nums:
        m = _DIAL.match(s.strip())
        if m:
            countries = [k for k in c.by_country if k]
            where = f" for {countries[0]}" if len(countries) == 1 else ""
            return f"International dial code{where}: +{m.group(1)}"
    return None


def contact_city(name: str) -> str:
    """The city a contact names itself with ('Consulate General of India - Denpasar' -> Denpasar); the query then
    carries that city, never the trip's. Empty when the name has none (the name alone is searched)."""
    m = re.search(r"[\u2013\u2014]\s*([A-Z][\w.'’]*(?: [A-Z][\w.'’]*)*)", name) or re.search(r"\s-\s([A-Z][\w.'’]*(?: [A-Z][\w.'’]*)*)", name)
    return m.group(1).strip() if m else ""


def _safety(c: SectionContent, data) -> list:
    out: list = []
    if c.numbers:
        out.append(g.EmergencyStrip(numbers=[g.EmergencyNumber(service=n.service, number=n.number) for n in c.numbers],
                                    dial=_dial(c, data)))
    if c.contacts:
        ranked = sorted(c.contacts, key=lambda k: _CONTACT_RANK.get(k.kind, 2))  # stable
        out.append(g.ContactCards(cards=[
            g.Contact(eyebrow=_EYEBROW.get(k.kind, "EMBASSY"), name=g.Link(text=k.name, url=search_url(k.name, contact_city(k.name) or (_city(data) if k.kind == "tourist_police" else ""))),
                      phone=k.phone or None, note=k.note or None) for k in ranked[:CONTACT_CAP]]))
        rest = [f"{k.name} - {k.phone}" if k.phone else k.name for k in ranked[CONTACT_CAP:]]
        if rest:
            out.append(g.TitledParas(items=[g.TitledPara(heading="Other contacts", body="; ".join(rest))]))
    def dup(i):  # prose repeating the numbers strip or the embassy/consulate cards
        return bool((c.numbers and _NUMBERS_ITEM.search(i.heading)) or (c.contacts and _CONSULAR_ITEM.search(i.heading)))
    return out + _titled([i for i in c.items if not dup(i)])


_BUILDERS = {"packing": _packing, "money": _money, "connectivity": _connectivity, "health": _health,
             "dishes": _dishes, "souvenirs": _souvenirs, "etiquette": _etiquette, "safety": _safety,
             "getting_around": _getting_around}


def structured_components(key: str, c: SectionContent, data) -> Optional[list]:
    """Components after the opener, or None to use the generic TitledParas path."""
    if len(c.by_country) > 1:
        return None  # per-country structured components are a later task
    fn = _BUILDERS.get(key)
    has = any([c.groups, c.apps, c.phrases, c.dos, c.donts, c.numbers, c.contacts, c.dishes, c.souvenirs, c.sims, c.steps, c.transport])
    if key == "money":
        has = bool(c.money) or any(i.heading.startswith("Currency") and not i.verify and "Indicative rate" in i.body
                                   for i in c.items)
    elif key == "health":
        has = any(_is_boat(i) for i in c.items)
    if not fn or not has:
        return None
    return fn(c, data)


_FACILITY_HEAD = re.compile(r"hospital|pharmac|apotek|clinic|medical\s+(?:care|help|centre|center)|"
                            r"medical help and emergency", re.I)
FACILITY_KEYS = ("health", "safety")
HOSPITALS_NOTE_TITLE = "HOSPITALS AND PHARMACIES"


def hospitals_note_text(page: Optional[int] = None) -> str:
    where = "Important Places Around Your Stays" + (f" (page {page})" if page else "")
    return f"Hospitals and pharmacies near each of your stays are listed under {where}."


def strip_facility_items(items: list[SectionItem]) -> list[SectionItem]:
    """Drop hospital/pharmacy/clinic items (Important Places is the one home for them); sentences that still name a
    facility are cut from the remaining items, and an item left empty is dropped."""
    from src.aigv2.writing.sections import hospital_mentions, pharmacy_mentions
    sent = re.compile(r"(?<=[.!?])\s+|\n+")
    out = []
    for i in items:
        if _FACILITY_HEAD.search(i.heading):
            continue
        parts = [x for x in sent.split(i.body) if x.strip()]
        kept = [x for x in parts if not (hospital_mentions(x) or pharmacy_mentions(x))]
        if len(kept) == len(parts):
            out.append(i)
        elif kept:
            out.append(i.model_copy(update={"body": " ".join(kept)}))
    return out
