"""Souvenir list cleanup: split a joined 'what to buy' string into distinct items."""
import re

MAX_ITEMS = 8
_SYN = {"fabric": "textile", "craft": "handicraft"}
_STOP = {"and", "the", "of", "a", "an", "with", "or", "in"}


def split_top_level(text: str) -> list[str]:
    """Split on ', ' / '; ' / ',' / ';' outside parentheses."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [re.sub(r"\s+", " ", x).strip(" .") for x in out if x.strip(" .")]


def _words(s: str) -> frozenset:
    ws = re.findall(r"[^\W_]+", s.lower())
    ws = [(w[:-1] if len(w) > 3 and w.endswith("s") else w) for w in ws if w not in _STOP]
    return frozenset(_SYN.get(w, w) for w in ws)


def distinct(items: list[str], cap: int = 0) -> list[str]:
    """Drop items whose normalised word set is a subset of (or equal to) another item's; keep first-seen order."""
    sets = [_words(i) for i in items]
    alive = [bool(ws) for ws in sets]
    for n, ws in enumerate(sets):  # pass 1: subset of (or same as an earlier) single item
        if alive[n] and any(m != n and alive[m] and (ws < o or (ws == o and m < n)) for m, o in enumerate(sets)):
            alive[n] = False
    for n in sorted(range(len(items)), key=lambda i: -len(sets[i])):  # pass 2: composites of other kept items
        if alive[n] and len(sets[n]) > 1:
            rest = set().union(*(sets[m] for m in range(len(items)) if m != n and alive[m]), set())
            if sets[n] <= rest:
                alive[n] = False
    keep = [it[0].upper() + it[1:] for it, a in zip(items, alive) if a]
    return keep[:cap] if cap else keep


def souvenir_items(what: str) -> list[str]:
    return distinct(split_top_level(what), MAX_ITEMS)
