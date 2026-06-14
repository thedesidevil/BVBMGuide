"""Named paragraph styles for AIG documents."""

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import Pt, RGBColor

# (name, size_pt, bold) — all black, Arial
AIG_STYLES: list[tuple[str, int, bool]] = [
    ("AIG Title",            28, True),
    ("AIG Subtitle",         14, False),
    ("AIG Day Heading",      17, True),
    ("AIG Day Section",      13, True),
    ("AIG Section Heading",  14, True),
    ("AIG Subsection",       12, True),
    ("AIG Body",             11, False),
    ("AIG Body Bold",        11, True),
    ("AIG Restaurant Name",  11, True),
    ("AIG Detail",           11, False),
    ("AIG Bullet",           11, False),
    ("AIG Overnight",        11, True),
    ("AIG Note",             11, False),
]

_BLACK = RGBColor(0, 0, 0)


def ensure_styles(doc: Document) -> None:
    """Add all AIG named styles to doc if not already present."""
    existing = {s.name for s in doc.styles}
    for name, pt, bold in AIG_STYLES:
        if name not in existing:
            style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        else:
            style = doc.styles[name]
        style.font.name = "Arial"
        style.font.size = Pt(pt)
        style.font.bold = bold
        style.font.color.rgb = _BLACK
