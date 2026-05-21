"""Named paragraph styles for AIG documents."""

from docx import Document
from docx.shared import Pt, RGBColor

# (name, size_pt, bold, (r, g, b))
AIG_STYLES: list[tuple[str, int, bool, tuple[int, int, int]]] = [
    ("AIG Title",            28, True,  (44,  62,  80)),
    ("AIG Subtitle",         14, False, (127, 140, 141)),
    ("AIG Day Heading",      16, True,  (26,  82,  118)),
    ("AIG Section Heading",  14, True,  (26,  82,  118)),
    ("AIG Subsection",       12, True,  (46,  134, 193)),
    ("AIG Body",             11, False, (33,  33,  33)),
    ("AIG Restaurant Name",  11, True,  (26,  82,  118)),
    ("AIG Detail",           10, False, (85,  85,  85)),
    ("AIG Bullet",           11, False, (33,  33,  33)),
    ("AIG Overnight",        11, True,  (30,  132, 73)),
    ("AIG Note",             10, False, (230, 126, 34)),
]


def ensure_styles(doc: Document) -> None:
    """Add all AIG named styles to doc if not already present."""
    existing = {s.name for s in doc.styles}
    for name, pt, bold, (r, g, b) in AIG_STYLES:
        if name not in existing:
            style = doc.styles.add_style(name, 1)  # 1 = WD_STYLE_TYPE.PARAGRAPH
        else:
            style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(pt)
        style.font.bold = bold
        style.font.color.rgb = RGBColor(r, g, b)
