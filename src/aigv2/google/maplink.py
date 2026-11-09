"""Parse and resolve Google Maps place links (no API cost; plain HTTP redirects for short links)."""
import re
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote_plus, urlsplit

import requests

SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl"}
_BAD_KIND = ("paste the Share > Copy link of ONE place (a search or directions link does not name a single place)")
_PIN = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_VIEW = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_CID = re.compile(r"0x[0-9a-fA-F]+:0x[0-9a-fA-F]+")
_UA = "Mozilla/5.0 (compatible; BVBMGuide/1.0)"


class MapLinkError(Exception):
    pass


@dataclass
class MapLink:
    name: str
    lat: Optional[float]
    lng: Optional[float]
    cid: Optional[str]
    url: str


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_maps_host(url: str) -> bool:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host in ("maps.app.goo.gl",) or host == "maps.google.com":
        return True
    if host == "goo.gl":
        return parts.path.startswith("/maps")
    return host in ("google.com", "www.google.com") and parts.path.startswith("/maps")


def is_short(url: str) -> bool:
    host = _host(url)
    return host == "maps.app.goo.gl" or (host == "goo.gl" and urlsplit(url).path.startswith("/maps"))


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^\s*https?://\S+\s*$", text, re.I))


def parse_maps_url(url: str) -> MapLink:
    """Parse a full (already expanded) Google Maps place URL. No network."""
    url = (url or "").strip()
    if not looks_like_url(url):
        raise MapLinkError("that is not a web link")
    if not is_maps_host(url):
        raise MapLinkError("that is not a Google Maps link")
    if is_short(url):
        raise MapLinkError("short link has to be expanded first")
    parts = urlsplit(url)
    m = re.search(r"/maps/place/([^/@?]+)", parts.path)
    q = parse_qs(parts.query)
    cid = None
    if not m:
        if "cid" in q and q["cid"][0].isdigit():
            return MapLink(name="", lat=None, lng=None, cid=q["cid"][0], url=url)
        raise MapLinkError(_BAD_KIND)
    name = " ".join(unquote_plus(m.group(1)).split())
    if not name or re.fullmatch(r"-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?", name):
        raise MapLinkError(_BAD_KIND)
    full = parts.path + ("?" + parts.query if parts.query else "")
    pin = _PIN.search(full)
    view = _VIEW.search(full)
    c = pin or view
    cm = _CID.search(full)
    return MapLink(name=name, lat=float(c.group(1)) if c else None, lng=float(c.group(2)) if c else None,
                   cid=cm.group(0) if cm else cid, url=url)


def default_fetch(url: str) -> str:
    """Follow redirects and return the final URL. Plain GET, no cookies, 10 s timeout."""
    with requests.Session() as s:
        s.cookies.set_policy(_NoCookies())
        r = s.get(url, headers={"User-Agent": _UA}, timeout=10, allow_redirects=True, stream=True)
        final = r.url
        r.close()
        return final


from http.cookiejar import CookiePolicy  # noqa: E402


class _NoCookies(CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *a, **k: False
    netscape = True
    rfc2965 = hide_cookie2 = False


def resolve_maps_link(url: str, fetch: Callable[[str], str] = default_fetch) -> MapLink:
    """Accept a pasted link (short or full) and return what it names. Raises only MapLinkError."""
    url = (url or "").strip()
    if not looks_like_url(url):
        raise MapLinkError("that is not a web link")
    if not is_maps_host(url):
        raise MapLinkError("that is not a Google Maps link")
    final = url
    if is_short(url):
        try:
            final = fetch(url)
        except Exception as e:  # network, timeout, bad redirect
            raise MapLinkError(f"could not open the short link ({type(e).__name__}); paste the full link instead") from e
        if not final or not is_maps_host(final) or is_short(final):
            raise MapLinkError("the short link did not lead to a Google Maps page")
    link = parse_maps_url(final)
    link.url = url
    return link
