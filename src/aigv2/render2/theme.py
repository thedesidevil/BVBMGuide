"""Design tokens for the render2 Word renderer (Direction 7 v5 Harbour)."""
from pathlib import Path

ROYAL = "3A6CB5"
CRIMSON = "D92027"
NAVY = "0C1F3E"
INK = "12294B"
POWDER = "AEC7E7"
FROST = "F4F6FA"
SLATE = "4A525E"
TAUPE = "C4B3A1"
TAUPE_TINT = "F3EFEA"
AMBER = "DEA350"
GOLD_INK = "8F5A16"
HARBOUR_FILL = "EDF3FB"
HARBOUR_EDGE = "BCD0EA"
CARD_EDGE = "BCD0EA"  # stronger than before so white cards separate from the white page
WHITE = "FFFFFF"
CREAM = "FAF7F1"  # the original start colour of the locked page gradient (very light beige)
PAGE_BG = CREAM  # solid: Google Docs drops gradients

HEAD = "Cormorant Garamond"
HEAD_FALLBACK = "Garamond"
BODYF = "Georgia"

# Page background: white -> frost at 18% -> pale harbour blue.
GRAD = ('<v:background id="_x0000_s1025" o:bwmode="white"><v:fill type="gradient" color="white" color2="#EEF3FA" '
        'angle="180" colors="0 white;18000f #F4F6FA;65536f #EEF3FA"/></v:background>')

ASSETS = Path(__file__).parent / "assets"


def asset(name: str) -> Path:
    return ASSETS / name


def _lum(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two 6-hex colours."""
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Every (text, background) pair the design uses; all must be >= 4.5:1.
_LIGHT = (WHITE, FROST, HARBOUR_FILL, TAUPE_TINT, CREAM)
PAIRS: list[tuple[str, str]] = (
    [(fg, bg) for fg in (INK, NAVY, SLATE, GOLD_INK) for bg in _LIGHT]
    + [(ROYAL, bg) for bg in _LIGHT]
    + [(WHITE, ROYAL), (WHITE, NAVY), (POWDER, NAVY), (AMBER, NAVY)]
    + [(CRIMSON, WHITE), (CRIMSON, FROST), (CRIMSON, CREAM)]
)

# Crimson text is only legal on these grounds (on HARBOUR_FILL it is 4.49:1).
CRIMSON_ALLOWED_BG = (WHITE, FROST, CREAM)
