"""Build src/aigv2/assets/cover_a4.png (2480x3508) with Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "aigv2" / "assets"
LE_JOUR = ROOT.parent / "BVBMWebsite" / "Fonts" / "Main Font - Le Jour Serif.otf"
GEORGIA = Path("/System/Library/Fonts/Supplemental/Georgia.ttf")
NAVY, GOLD, WHITE = (12, 31, 62), (198, 138, 50), (255, 255, 255)
W, H = 2480, 3508


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _centered(draw, y, text, font, fill, spacing=0):
    if spacing:
        widths = [draw.textlength(c, font=font) for c in text]
        x = (W - (sum(widths) + spacing * (len(text) - 1))) / 2
        for c, w in zip(text, widths):
            draw.text((x, y), c, font=font, fill=fill)
            x += w + spacing
    else:
        draw.text(((W - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def _tagline(draw, y):
    # Le Jour Serif has no bullet glyph, so the separators are drawn as dots.
    font = _font(LE_JOUR, 84)
    parts = ["Your Vacation", "Your Story", "Your Way"]
    gap = 90
    widths = [draw.textlength(p, font=font) for p in parts]
    x = (W - (sum(widths) + gap * 2)) / 2
    mid = y + 62 - 30
    for i, (p, w) in enumerate(zip(parts, widths)):
        draw.text((x, y), p, font=font, fill=WHITE)
        x += w
        if i < 2:
            draw.ellipse([x + gap / 2 - 8, mid - 8, x + gap / 2 + 8, mid + 8], fill=GOLD)
            x += gap


def build(out: Path = ASSETS / "cover_a4.png") -> Path:
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([60, 60, W - 61, H - 61], outline=GOLD, width=6)
    logo = Image.open(ASSETS / "logo_white.png").convert("RGBA")
    lw = 1500
    logo = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
    img.paste(logo, ((W - lw) // 2, 1000), logo)
    _tagline(d, 1000 + logo.height + 220)
    _centered(d, 2750, "BON VOYAGE BY MARINA", _font(GEORGIA, 64), GOLD, spacing=14)
    _centered(d, 2900, "+91-86000-15316", _font(GEORGIA, 56), WHITE)
    _centered(d, 3000, "www.bonvoyagebymarina.com", _font(GEORGIA, 56), WHITE)
    img = img.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(out, optimize=True)
    return out


if __name__ == "__main__":
    p = build()
    print(p, p.stat().st_size)
