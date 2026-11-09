import pytest

from src.aigv2.google.maplink import MapLinkError, parse_maps_url, resolve_maps_link

SHORT = "https://maps.app.goo.gl/TCqyu1dcEGSfi4hu5"
FINAL = ("https://www.google.com/maps/place/Baeren+Hotel,+The+Bear+Inn/@46.663802,7.8606779,17z/data=!3m1!4b1!4m9!3m8"
         "!1s0x478fa387a2b8f0b3:0xa1c991ace62aef11!5m2!4m1!1i2!8m2!3d46.6638!4d7.8607!16s%2Fg%2F1tfkdhfh?entry=ttu")


def test_parse_full():
    m = parse_maps_url(FINAL)
    assert m.name == "Baeren Hotel, The Bear Inn"
    assert (m.lat, m.lng) == (46.6638, 7.8607)  # pin, not viewport
    assert m.cid == "0x478fa387a2b8f0b3:0xa1c991ace62aef11"


def test_viewport_fallback_and_unicode_and_percent():
    m = parse_maps_url("https://www.google.com/maps/place/Caf%C3%A9+Z%C3%BCrich%2C+Bern/@47.1,8.2,15z")
    assert m.name == "Café Zürich, Bern" and (m.lat, m.lng) == (47.1, 8.2) and m.cid is None


def test_short_resolved_by_fake_fetch():
    seen = []

    def fetch(u):
        seen.append(u)
        return FINAL

    m = resolve_maps_link(SHORT, fetch=fetch)
    assert seen == [SHORT] and m.name.startswith("Baeren") and m.url == SHORT


def test_full_link_needs_no_fetch():
    def boom(u):
        raise AssertionError("no network")
    assert resolve_maps_link(FINAL, fetch=boom).name.startswith("Baeren")


@pytest.mark.parametrize("url", [
    "https://www.google.com/maps/dir/Bern/Zurich/@47,8,10z",
    "https://www.google.com/maps/search/hotels+in+bern/@46.9,7.4,13z",
    "https://example.com/maps/place/X",
    "https://www.google.com/maps/place/46.6,7.8/@46.6,7.8,17z",
    "not a url",
])
def test_rejected(url):
    with pytest.raises(MapLinkError):
        parse_maps_url(url)


def test_search_link_message():
    with pytest.raises(MapLinkError, match="ONE place"):
        parse_maps_url("https://www.google.com/maps/search/hotels/@1,2,3z")


def test_network_error_becomes_maplinkerror():
    def fetch(u):
        raise TimeoutError("slow")
    with pytest.raises(MapLinkError, match="short link"):
        resolve_maps_link(SHORT, fetch=fetch)


def test_short_leading_nowhere():
    with pytest.raises(MapLinkError):
        resolve_maps_link(SHORT, fetch=lambda u: "https://consent.google.com/x")


def test_other_hosts_rejected_without_fetch():
    with pytest.raises(MapLinkError, match="Google Maps"):
        resolve_maps_link("https://bit.ly/abc", fetch=lambda u: 1 / 0)


def test_cid_link_has_no_name():
    m = parse_maps_url("https://www.google.com/maps?cid=12345")
    assert m.cid == "12345" and m.name == ""
