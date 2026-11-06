"""Accent-insensitive text folding, for MATCHING ONLY (comparisons, cache keys, lookup fallbacks).

Never use the result as display text: the guide keeps names as written ('Zürich', 'Café').
"""
import re
import unicodedata

# Letters NFKD does not decompose.
_EXTRA = str.maketrans({
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ł": "l", "þ": "th", "ð": "d", "ı": "i",
    "ĸ": "k", "ŋ": "n", "ħ": "h",
    "’": "'", "‘": "'", "‚": "'", "‛": "'", "ʼ": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
})
_WS = re.compile(r"\s+")


def fold(s: str) -> str:
    """casefold + accents removed + typographic punctuation normalised + whitespace collapsed."""
    if not s:
        return ""
    d = unicodedata.normalize("NFKD", s.casefold())
    d = "".join(ch for ch in d if not unicodedata.combining(ch)).translate(_EXTRA)
    return _WS.sub(" ", d).strip()


def has_accents(s: str) -> bool:
    """True when the text has letters that folding rewrites (accents, ß, ø ...), not just quotes or dashes."""
    return bool(s) and any(ch.isalpha() and ord(ch) > 127 for ch in s)


def strip_accents(s: str) -> str:
    """Accents removed but case and spacing kept (for a lookup-query fallback)."""
    d = unicodedata.normalize("NFKD", s)
    d = "".join(ch for ch in d if not unicodedata.combining(ch))
    return d.translate(str.maketrans({"ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O",
                                      "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "þ": "th", "Þ": "Th",
                                      "ð": "d", "Ð": "D", "ı": "i", "’": "'", "‘": "'"}))


def fold_key(s: str) -> str:
    """Cache-key form: fold, with whitespace around '|' separators removed."""
    return "|".join(fold(p) for p in s.split("|"))
