from src.aigv2.guide import model as m
from src.aigv2.guide.build import build_guide, build_reference_page
from src.aigv2.render.sections_render import search_url
from src.aigv2.writing.sections import SectionContent, SectionGroup, SectionItem
from src.aigv2.writing.structured import App, Contact, Dish, EmergencyNumber, Phrase, Souvenir
from tests.aigv2.test_guide_build import SETTINGS, load


def _it(h, b="", verify=False):
    return SectionItem(heading=h, body=b, verify=verify)


def types(page):
    return [c.type for c in page.components]


def test_packing_groups_and_little_one_panel():
    c = SectionContent(key="packing", groups=[
        SectionGroup(title="Clothing", items=[_it("Linen shirts")]),
        SectionGroup(title="For your little one", items=[_it("Swim nappies"), _it("Hat")]),
        SectionGroup(title="Footwear", items=[_it("Sandals")])])
    p = build_reference_page("packing", c, load())
    assert types(p) == ["ReferenceOpener", "ChecklistGroups", "TipPanel"]
    assert [x.title for x in p.components[1].groups] == ["Clothing", "Footwear"]
    assert p.components[1].groups[0].items == ["Linen shirts"]
    tip = p.components[2]
    assert (tip.title, tip.items, tip.columns, tip.checks) == ("For your little one", ["Swim nappies", "Hat"], 2, True)


def test_money_fact_row_only_with_fx_item():
    fx = _it("Currency: XYZ", "1 XYZ = ₹2.00. Indicative rate (check before you travel).")
    c = SectionContent(key="money", items=[fx, _it("Cards", "Widely accepted.")])
    p = build_reference_page("money", c, load())
    assert types(p) == ["ReferenceOpener", "FactRowBlock", "TitledParas", "NotePanel"]
    assert p.components[1].facts[0] == m.Fact(label="Currency", value="XYZ")
    assert p.components[1].facts[1].value == "1 XYZ = ₹2.00"
    assert p.components[2].items == [m.TitledPara(heading="Cards", body="Widely accepted.")]
    assert p.components[3].title == "PLEASE NOTE"
    plain = SectionContent(key="money", items=[_it("Cards", "x")])
    assert types(build_reference_page("money", plain, load())) == ["ReferenceOpener", "TitledParas"]


def test_connectivity_app_grid():
    c = SectionContent(key="connectivity", items=[_it("eSIM", "Buy one.")], apps=[App(name="AppA", purpose="Rides")])
    p = build_reference_page("connectivity", c, load())
    assert types(p) == ["ReferenceOpener", "TitledParas", "AppGrid"]
    assert p.components[2].apps == [m.App(name="AppA", use="Rides")]


def test_health_boat_item_becomes_note_panel():
    c = SectionContent(key="health", items=[_it("Vaccines", "Check."), _it("Boat crossings", "Seas can be rough. Ask your paediatrician.")])
    p = build_reference_page("health", c, load())
    assert types(p) == ["ReferenceOpener", "TitledParas", "NotePanel"]
    assert p.components[2].title == "BOAT CROSSINGS"
    assert p.components[2].items == ["Seas can be rough.", "Ask your paediatrician."]
    assert [i.heading for i in p.components[1].items] == ["Vaccines"]


def test_getting_around_generic():
    p = build_reference_page("getting_around", SectionContent(key="getting_around", items=[_it("Taxis", "b")]), load())
    assert types(p) == ["ReferenceOpener", "TitledParas"]


def test_dishes_where_links():
    data = load()
    known = next(pl for d in data.days for pl in d.places.values() if pl and pl.maps_url)
    c = SectionContent(key="dishes", dishes=[Dish(name="Dish A", description="Tasty", where_to_try=[known.name, "Unknown Warung"])])
    p = build_reference_page("dishes", c, data)
    assert types(p) == ["ReferenceOpener", "DishGrid"]
    d = p.components[1].dishes[0]
    assert (d.name, d.desc) == ("Dish A", "Tasty")
    assert d.where[0] == m.Link(text=known.name, url=known.maps_url)
    assert d.where[1].url == search_url("Unknown Warung", data.days[0].city)
    nodish = SectionContent(key="dishes", items=[_it("a", "b")])
    assert types(build_reference_page("dishes", nodish, data)) == ["ReferenceOpener", "TitledParas"]


def test_souvenirs():
    data = load()
    c = SectionContent(key="souvenirs", souvenirs=[Souvenir(title="Textiles", what="Woven", places=["Dummy Market"])])
    p = build_reference_page("souvenirs", c, data)
    s = p.components[1].categories[0]
    assert types(p) == ["ReferenceOpener", "SouvenirGrid"] and s.title == "Textiles"
    assert s.places[0].url == search_url("Dummy Market", data.days[0].city)


def test_etiquette_dos_donts_phrases():
    c = SectionContent(key="etiquette", dos=["Smile"], donts=["Shout"], phrases=[Phrase(local="Hi", english="Hello")],
                       items=[_it("Tipping", "Optional."), _it("Greetings", "Bow.")])
    p = build_reference_page("etiquette", c, load())
    assert types(p) == ["ReferenceOpener", "DosDonts", "PhraseTable", "NotePanel", "TitledParas"]
    assert p.components[1].do == ["Smile"] and p.components[2].phrases == [m.Phrase(local="Hi", english="Hello")]
    assert p.components[3].title == "MARKETS AND TIPPING"


def test_safety_strip_and_contacts():
    c = SectionContent(key="safety", numbers=[EmergencyNumber(service="Police", number="110")],
                       contacts=[Contact(name="Tourist Desk", phone="999", note="English", kind="tourist_police"),
                                 Contact(name="Consulate X", phone="+99 1 234", kind="consulate")],
                       items=[_it("Scams", "Beware.")])
    p = build_reference_page("safety", c, load())
    assert types(p) == ["ReferenceOpener", "EmergencyStrip", "ContactCards", "TitledParas"]
    assert p.components[1].numbers == [m.EmergencyNumber(service="Police", number="110")]
    assert p.components[1].dial == "International dial code: +99"
    assert [x.eyebrow for x in p.components[2].cards] == ["TOURIST POLICE", "INDIAN CONSULATE"]
    c2 = c.model_copy(update={"contacts": [Contact(name="Desk", phone="999", kind="embassy")]})
    p2 = build_reference_page("safety", c2, load())
    assert p2.components[1].dial is None and p2.components[2].cards[0].eyebrow == "EMBASSY"


def test_unstructured_section_still_titled_paras():
    for key in ("packing", "money", "health", "dishes", "etiquette", "safety", "connectivity"):
        c = SectionContent(key=key, items=[_it("A", "b")])
        assert types(build_reference_page(key, c, load())) == ["ReferenceOpener", "TitledParas"]


def test_full_guide_roundtrip_with_structured_sections():
    data = load()
    data.sections = {"dishes": SectionContent(key="dishes", items=[_it("D", "d")], dishes=[Dish(name="D", description="d", where_to_try=["W"])]),
                     "safety": SectionContent(key="safety", items=[_it("S", "s")], numbers=[EmergencyNumber(service="Police", number="110")])}
    guide = build_guide(data, SETTINGS)
    assert any(c.type == "DishGrid" for p in guide.pages for c in p.components)
    assert m.Guide.model_validate_json(guide.model_dump_json()) == guide


def _two_country(key, **kw):
    return SectionContent(key=key, items=[_it("a", "b"), _it("c", "d")],
                          by_country={"Alpha": [_it("a", "b")], "Beta": [_it("c", "d")]}, **kw)


def test_two_country_safety_and_etiquette_use_generic_path():
    s = _two_country("safety", numbers=[EmergencyNumber(service="Police", number="+99")],
                     contacts=[Contact(name="Desk", phone="+99 1", kind="embassy")])
    p = build_reference_page("safety", s, load())
    assert types(p) == ["ReferenceOpener", "TitledParas", "TitledParas"]
    assert p.components[1].items[0].heading == "Alpha"
    e = _two_country("etiquette", dos=["x"], donts=["y"], phrases=[Phrase(local="a", english="b")],
                     markers=[])
    assert types(build_reference_page("etiquette", e, load())) == ["ReferenceOpener", "TitledParas", "TitledParas"]


def test_single_country_by_country_keeps_structured_and_dial_suffix():
    s = SectionContent(key="safety", items=[_it("a", "b", verify=True)], by_country={"Alpha": [_it("a", "b", verify=True)]},
                       numbers=[EmergencyNumber(service="Police", number="+1242 919")])
    p = build_reference_page("safety", s, load())
    assert types(p)[:2] == ["ReferenceOpener", "EmergencyStrip"]
    assert p.components[1].dial == "International dial code for Alpha: +1242"
    assert p.components[-1].type == "ReviewMarkerBlock"


def test_health_body_only_matches_paediatrician():
    c = SectionContent(key="health", items=[_it("Staying hydrated", "Avoid motion sickness tablets without advice.")])
    assert types(build_reference_page("health", c, load())) == ["ReferenceOpener", "TitledParas"]
    c = SectionContent(key="health", items=[_it("Boat crossings", "Rough.")])
    assert types(build_reference_page("health", c, load()))[-1] == "NotePanel"
    c = SectionContent(key="health", items=[_it("Little ones", "Ask your paediatrician first.")])
    assert types(build_reference_page("health", c, load()))[-1] == "NotePanel"


def test_dial_no_separator_edge():
    from src.aigv2.guide.reference import _dial
    c = SectionContent(key="safety", numbers=[EmergencyNumber(service="P", number="+1242")])
    assert _dial(c, None) == "International dial code: +1242"
    c = SectionContent(key="safety", numbers=[EmergencyNumber(service="P", number="+12429191234")])
    assert _dial(c, None) is None


def test_money_library_paras_with_fx():
    from src.aigv2.writing.structured import Para
    fx = _it("Currency: XYZ", "1 XYZ = ₹2.00. Indicative rate (check before you travel).")
    c = SectionContent(key="money", items=[fx, _it("llm", "x")], money=[Para(heading="Cards", body="Widely accepted.")])
    p = build_reference_page("money", c, load())
    assert types(p) == ["ReferenceOpener", "FactRowBlock", "TitledParas", "NotePanel"]
    assert [i.heading for i in p.components[2].items] == ["Cards"]
    only = SectionContent(key="money", items=[_it("llm", "x")], money=[Para(heading="Cards", body="y")])
    assert types(build_reference_page("money", only, load())) == ["ReferenceOpener", "TitledParas"]


def test_connectivity_facts_and_airport_panel():
    from src.aigv2.writing.structured import SimInfo
    c = SectionContent(key="connectivity", items=[_it("eSIM", "Buy.")], sims=[SimInfo(provider="Telkomsel", plan="15 GB", options="SIM or eSIM")],
                       steps=["Test the SIM"], apps=[App(name="A", purpose="r")])
    p = build_reference_page("connectivity", c, load())
    assert types(p) == ["ReferenceOpener", "FactRowBlock", "TitledParas", "TipPanel", "AppGrid"]
    assert [f.label for f in p.components[1].facts] == ["Recommended provider", "Suggested data plan", "Options"]
    assert p.components[3].title == "Before you leave the airport" and p.components[3].items == ["Test the SIM"]


def test_getting_around_library_transport():
    from src.aigv2.writing.structured import Para
    c = SectionContent(key="getting_around", items=[_it("llm", "x")], transport=[Para(heading="Taxi", body="Use meter.")])
    p = build_reference_page("getting_around", c, load())
    assert p.components[1].items == [m.TitledPara(heading="Taxi", body="Use meter.")]


def test_contact_cards_capped_with_priority_and_rest_listed():
    cs = [Contact(name="Embassy A", phone="1", kind="embassy"), Contact(name="Embassy B", phone="2", kind="embassy"),
          Contact(name="Consulate", phone="3", kind="consulate"), Contact(name="Tourist Police", phone="4", kind="tourist_police")]
    p = build_reference_page("safety", SectionContent(key="safety", contacts=cs), load())
    assert [k.name.text for k in p.components[1].cards] == ["Tourist Police", "Consulate", "Embassy A"]
    assert p.components[2].items == [m.TitledPara(heading="Other contacts", body="Embassy B - 2")]


def _texts(page):
    import json
    return json.dumps(page.model_dump(), ensure_ascii=False)


def test_packing_groups_not_repeated_as_prose():
    from src.aigv2.guide.build import build_reference_page
    from src.aigv2.writing.sections import SectionContent, SectionGroup, SectionItem
    titles = ["Clothing", "Footwear", "Electronics"]
    groups = [SectionGroup(title=t, items=[SectionItem(heading=f"{t} thing", body="")]) for t in titles]
    items = [SectionItem(heading=t, body=f"{t} thing") for t in titles]
    page = build_reference_page("packing", SectionContent(key="packing", items=items, groups=groups), None)
    assert not [c for c in page.components if type(c).__name__ == "TitledParas"]
    for t in titles:
        assert _texts(page).count(f'"{t}"') == 1


def test_packing_items_still_used_without_groups():
    from src.aigv2.guide.build import build_reference_page
    from src.aigv2.writing.sections import SectionContent, SectionItem
    page = build_reference_page("packing", SectionContent(key="packing", items=[SectionItem(heading="X", body="y")]), None)
    assert [c for c in page.components if type(c).__name__ == "TitledParas"]


def test_etiquette_safety_connectivity_prose_not_duplicated():
    from src.aigv2.guide.reference import structured_components
    from src.aigv2.writing.sections import SectionContent, SectionItem
    from src.aigv2.writing.structured import App, Contact, EmergencyNumber, Phrase
    I = lambda h: SectionItem(heading=h, body="b")
    def heads(comps):
        return [p.heading for c in comps if type(c).__name__ == "TitledParas" for p in c.items]
    et = SectionContent(key="etiquette", phrases=[Phrase(local="a", english="b")], dos=["x"], donts=["y"],
                        items=[I("Greetings and useful phrases"), I("Temple and everyday etiquette"), I("Local customs")])
    assert heads(structured_components("etiquette", et, None)) == ["Temple and everyday etiquette", "Local customs"]
    sf = SectionContent(key="safety", numbers=[EmergencyNumber(service="Police", number="110")],
                        contacts=[Contact(name="C", phone="1", kind="consulate")],
                        items=[I("Everyday Safety"), I("Emergency Numbers"), I("Indian Consular Assistance")])
    class D: days = []
    assert heads(structured_components("safety", sf, D)) == ["Everyday Safety"]
    cn = SectionContent(key="connectivity", apps=[App(name="Grab", purpose="rides")],
                        items=[I("Mobile data"), I("Useful apps and offline access")])
    assert heads(structured_components("connectivity", cn, None)) == ["Mobile data"]
