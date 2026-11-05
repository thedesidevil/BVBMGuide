"""Structured reference-section components (packing, money, apps, dishes, ...). Nothing here invents text."""
import re
from typing import Optional

from src.aigv2.guide import model as g
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
_DIAL = re.compile(r"^\+(\d{1,4})(?=[\s\-()]|$)")


def _is_boat(i: SectionItem) -> bool:
    return bool(_BOAT_HEAD.search(i.heading) or _PAED.search(i.body))


def paras(items: list[SectionItem]) -> list[g.TitledPara]:
    return [g.TitledPara(heading=i.heading, body=i.body) for i in items]


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
    body = [i for i in c.items if i is not fx]
    lib = [g.TitledPara(heading=p.heading, body=p.body) for p in c.money]
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
    out += _titled([i for i in c.items if not (c.apps and _APPS_ITEM.search(i.heading))])
    if c.steps:
        out.append(g.TipPanel(title="Before you leave the airport", items=c.steps, columns=2, checks=True))
    if c.apps:
        out.append(g.AppGrid(apps=[g.App(name=a.name, use=a.purpose) for a in c.apps]))
    return out


def _getting_around(c: SectionContent, data) -> list:
    return [g.TitledParas(items=[g.TitledPara(heading=p.heading, body=p.body) for p in c.transport])]


def _health(c: SectionContent, data) -> list:
    boat = [i for i in c.items if _is_boat(i)]
    rest = [i for i in c.items if i not in boat]
    out = _titled(rest)
    if boat:
        sents = [s.strip() for b in boat for s in re.split(r"(?<=\.) ", b.body) if s.strip()]
        out.append(g.NotePanel(title="BOAT CROSSINGS", items=sents))
    return out


def _dishes(c: SectionContent, data) -> list:
    if not c.dishes:
        return _titled(c.items)
    pl = known_places(data)
    return [g.DishGrid(dishes=[g.Dish(name=d.name, desc=d.description,
                                      where=[_link(n, data, pl) for n in d.where_to_try]) for d in c.dishes])]


def _souvenirs(c: SectionContent, data) -> list:
    if not c.souvenirs:
        return _titled(c.items)
    pl = known_places(data)
    return [g.SouvenirGrid(categories=[g.Souvenir(title=s.title, what=s.what,
                                                  places=[_link(n, data, pl) for n in s.places]) for s in c.souvenirs])]


def _etiquette(c: SectionContent, data) -> list:
    out: list = []
    if c.dos or c.donts:
        out.append(g.DosDonts(do=c.dos, dont=c.donts))
    if c.phrases:
        out.append(g.PhraseTable(phrases=[g.Phrase(local=p.local, english=p.english) for p in c.phrases]))
    if not out:
        return _titled(c.items)
    market = [i for i in c.items if _MARKET.search(i.heading)]
    if market:
        out.append(g.NotePanel(title="MARKETS AND TIPPING", items=[f"{i.heading}: {i.body}" for i in market]))
    def dup(i):  # prose that only repeats the phrase table
        return bool(c.phrases and _PHRASE_ITEM.search(i.heading))
    return out + _titled([i for i in c.items if i not in market and not dup(i)])


def _dial(c: SectionContent, data) -> Optional[str]:
    nums = [n.number for n in c.numbers] + [x.phone for x in c.contacts]
    for s in nums:
        m = _DIAL.match(s.strip())
        if m:
            countries = [k for k in c.by_country if k]
            where = f" for {countries[0]}" if len(countries) == 1 else ""
            return f"International dial code{where}: +{m.group(1)}"
    return None


def _safety(c: SectionContent, data) -> list:
    out: list = []
    if c.numbers:
        out.append(g.EmergencyStrip(numbers=[g.EmergencyNumber(service=n.service, number=n.number) for n in c.numbers],
                                    dial=_dial(c, data)))
    if c.contacts:
        city = _city(data)
        ranked = sorted(c.contacts, key=lambda k: _CONTACT_RANK.get(k.kind, 2))  # stable
        out.append(g.ContactCards(cards=[
            g.Contact(eyebrow=_EYEBROW.get(k.kind, "EMBASSY"), name=g.Link(text=k.name, url=search_url(k.name, city)),
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
