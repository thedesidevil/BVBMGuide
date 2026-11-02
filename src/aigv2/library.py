import json
import re
import unicodedata
from pathlib import Path

from src.aigv2.models import Diet

_ALIASES = {"nyc": ["New York", "New York City"]}
_INDIAN = (
    "indian", "gujarati", "south indian", "north indian", "rajasthani", "punjabi",
    "kerala", "udupi", "chettinad", "bengali", "maharashtrian",
)
_JP_KR = ("japanese", "korean")
_PURE_VEG = (
    "pure veg", "pure-veg", "vegetarian only", "vegetarian-only", "100% vegetarian",
    "fully vegetarian", "all vegetarian", "pure vegetarian",
)


_NEG = re.compile(r"(?:\bnot |\bno |\bnon-|\bnon )$")


class LibraryDataError(Exception):
    pass


def norm_name(s: str) -> str:
    return " ".join(s.casefold().split())


def _fold(s: str) -> str:
    """norm_name plus accent folding (NFKD, combining marks dropped)."""
    d = unicodedata.normalize("NFKD", s)
    return norm_name("".join(ch for ch in d if not unicodedata.combining(ch)))


_COUNTRY_ALIASES = [
    ("turkey", "turkiye"),
    ("usa", "us", "united states", "united states of america"),
    ("uk", "united kingdom", "great britain", "england", "scotland"),
    ("uae", "united arab emirates"),
]


def _country_aliases(name: str) -> list[str]:
    f = _fold(name)
    for group in _COUNTRY_ALIASES:
        if f in group:
            return list(group)
    return []


def _has(text: str, term: str) -> bool:
    pattern = r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
    return any(not _NEG.search(text[: m.start()]) for m in re.finditer(pattern, text))


def _cuisines(r: dict) -> list[str]:
    c = r.get("cuisine_type") or []
    if isinstance(c, str):
        c = [c]
    return [norm_name(x) for x in c if isinstance(x, str)]


def _text(r: dict, keys: tuple[str, ...]) -> str:
    parts: list[str] = []
    for k in keys:
        v = r.get(k)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(x for x in v if isinstance(x, str))
    return norm_name(" | ".join(parts))


def is_indian(restaurant: dict) -> bool:
    return any(_has(c, t) for c in _cuisines(restaurant) for t in _INDIAN)


def _kind(restriction: str) -> str | None:
    if "vegan" in restriction:
        return "vegan"
    if "vegetarian" in restriction or restriction == "veg":
        return "vegetarian"
    return None


def _vegan_fits(r: dict) -> bool:
    blob = " | ".join([norm_name(r.get("name") or ""), *_cuisines(r), _text(r, ("highlights", "must_try_dishes", "notes"))])
    return _has(blob, "vegan")


def _veg_fits(r: dict, pure: bool) -> bool:
    cuisines = _cuisines(r)
    if pure:
        blob = " | ".join([norm_name(r.get("name") or ""), *cuisines, _text(r, ("highlights",))])
        return r.get("vegetarian_friendly") is True and any(_has(blob, p) for p in _PURE_VEG)
    veg_cuisine = any(_has(c, w) for c in cuisines for w in ("vegetarian", "vegan"))
    if any(_has(c, j) for c in cuisines for j in _JP_KR):
        proof = _text(r, ("highlights", "must_try_dishes", "notes"))
        return veg_cuisine or (r.get("vegetarian_friendly") is True and (_has(proof, "vegetarian") or _has(proof, "vegan")))
    return r.get("vegetarian_friendly") is True or veg_cuisine or is_indian(r)


def _terms(restriction: str) -> list[str]:
    core = restriction
    for p in ("nothing ", "no ", "avoid "):
        if core.startswith(p):
            core = core[len(p):]
    for s in (" allergy", " allergies", " free", "-free"):
        if core.endswith(s):
            core = core[: -len(s)]
    core = core.strip()
    terms = [restriction, f"no {core}", f"{core}-free", f"{core} free"]
    if core == "pork":
        terms.append("halal")
    return terms


def diet_fits(restaurant: dict, diet: Diet) -> bool:
    restrictions = [norm_name(x) for x in diet.restrictions + diet.allergies if x.strip()]
    if not restrictions and not diet.pure_veg:
        return True
    if diet.pure_veg and not _veg_fits(restaurant, True):
        return False
    blob = _text(restaurant, ("highlights", "must_try_dishes", "notes"))
    for rs in restrictions:
        kind = _kind(rs)
        if kind == "vegan":
            if not _vegan_fits(restaurant):
                return False
        elif kind == "vegetarian":
            if not diet.pure_veg and not _veg_fits(restaurant, False):
                return False
        elif not any(_has(blob, t) for t in _terms(rs)):
            return False
    return True


_GENERIC = {"the", "of", "and", "de", "temple", "beach", "park", "market", "view", "point", "village", "bay",
            "club", "resort", "hotel", "street", "road", "garden", "forest", "mountain", "lake", "island",
            "museum", "palace", "waterfall", "cave"}


def _landmark_words(text: str) -> list[str]:
    """Words of the part before the first comma, folded, punctuation stripped."""
    head = text.split(",")[0]
    return re.findall(r"[a-z0-9]+", _fold(head).replace("'", ""))


def _landmark_match(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    if a == b:
        return len(a) > 1 or a[0] not in _GENERIC
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 2:
        return False
    n = len(short)
    if not any(long_[i:i + n] == short for i in range(len(long_) - n + 1)):
        return False
    return any(w not in _GENERIC for w in short)


class Library:
    def __init__(self, db_path: Path):
        self.root = Path(db_path)
        self._files = {p.stem.casefold(): p for p in self.root.glob("*.json") if not p.name.startswith("_")}
        self._coverage = self._load(self.root / "_index.json").get("_folder_coverage", {})
        self._landmarks: dict[str, list[list[list[str]]]] | None = None

    @staticmethod
    def _load(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise LibraryDataError(path) from e
        if not isinstance(data, dict):
            raise LibraryDataError(path)
        return data

    def _names(self, city: str) -> list[str]:
        c = city.strip()
        out = list(_ALIASES.get(c.casefold(), [c]))
        for n in list(out):
            alt = n[:-5] if n.casefold().endswith(" city") else f"{n} City"
            if alt not in out:
                out.append(alt)
        return out

    def _folders(self, names: list[str]) -> list[str]:
        want = {n.casefold() for n in names}
        return [f for f, cities in self._coverage.items() if want & {c.casefold() for c in cities}]

    def _region_names(self, folders: list[str], city: str) -> list[str]:
        out = []
        for f in folders:
            if re.search(r" and |&|\+", f.casefold()):
                continue
            words = norm_name(f).split()
            for c in self._coverage.get(f, []):
                cw = norm_name(c).split()
                if cw and norm_name(c) != norm_name(city) and words[: len(cw)] == cw:
                    out.append(c)
        return out

    def _shards(self, names: list[str]) -> list[dict]:
        seen, shards = set(), []
        for n in names:
            p = self._files.get(n.casefold())
            if p and p not in seen:
                seen.add(p)
                shards.append(self._load(p))
        return shards

    def city(self, city: str) -> dict:
        names = self._names(city)
        names += self._region_names(self._folders(names), city)
        merged: dict = {}
        seen: dict[str, set] = {}
        for shard in self._shards(names):
            for key, val in shard.items():
                if not isinstance(val, list):
                    merged.setdefault(key, val)
                    continue
                bucket = merged.setdefault(key, [])
                keys = seen.setdefault(key, set())
                for item in val:
                    k = norm_name(item["name"]) if isinstance(item, dict) and isinstance(item.get("name"), str) else json.dumps(item, sort_keys=True)
                    if k not in keys:
                        keys.add(k)
                        bucket.append(item)
        return merged

    def country(self, country: str) -> dict:
        d = self.root / "_country"
        if not d.is_dir():
            return {}
        want = norm_name(country)
        folders = self._folders(self._names(country))
        by_stem = {_fold(p.stem): p for p in d.glob("*.json")}
        cands = [want, *(norm_name(f) for f in folders)]
        cands += [a for c in list(cands) for a in _country_aliases(c)]
        for cand in cands:
            cand = _fold(cand)
            if cand in by_stem:
                return self._load(by_stem[cand])
        return {}

    def restaurants(self, city: str) -> list[dict]:
        return self.city(city).get("restaurants", [])

    def restaurants_near(self, locality: str) -> list[dict]:
        found = self.area_for(locality)
        return found[1] if found else []

    def area_for(self, anchor: str, city: str | None = None) -> tuple[str, list[dict]] | None:
        """Restaurant file for an anchor: an exact shard name, else the area shard whose restaurants list the
        anchor as a nearby landmark (never the anchor's own city shard)."""
        a_fold = _fold(anchor.strip())
        if not a_fold:
            return None
        by_fold = {_fold(p.stem): p for p in self._files.values()}
        p = by_fold.get(a_fold)
        if p:
            return p.stem, self._load(p).get("restaurants", [])
        words = _landmark_words(anchor)
        if not words:
            return None
        skip = {_fold(n) for n in self._names(city)} if city else set()
        best: tuple[int, str] | None = None
        for stem, entries in self._landmark_index().items():
            if _fold(stem) in skip:
                continue
            hits = sum(1 for lm in entries if any(_landmark_match(words, w) for w in lm))
            if hits and (best is None or hits > best[0] or (hits == best[0] and stem < best[1])):
                best = (hits, stem)
        if best is None:
            return None
        return best[1], self._load(self._files[best[1].casefold()]).get("restaurants", [])

    def _landmark_index(self) -> dict[str, list[list[list[str]]]]:
        if self._landmarks is None:
            idx: dict[str, list[list[list[str]]]] = {}
            for p in self._files.values():
                rs = self._load(p).get("restaurants", [])
                entries = []
                for r in rs if isinstance(rs, list) else []:
                    lms = r.get("nearby_landmarks") if isinstance(r, dict) else None
                    if isinstance(lms, str):
                        lms = [lms]
                    ws = [_landmark_words(x) for x in lms or [] if isinstance(x, str)]
                    ws = [w for w in ws if w]
                    if ws:
                        entries.append(ws)
                if entries:
                    idx[p.stem] = entries
            self._landmarks = idx
        return self._landmarks

    def has_data(self, city: str) -> bool:
        return bool(self.restaurants(city))

    def coverage(self) -> dict[str, list[str]]:
        return {f: list(c) for f, c in self._coverage.items() if isinstance(c, list)}
