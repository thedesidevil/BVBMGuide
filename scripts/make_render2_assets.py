"""Regenerate the cropped render2 logo PNGs from the owner's logo folder.

The committed PNGs in src/aigv2/render2/assets/ are the product; this script
documents how they were produced. Usage:
    python3 scripts/make_render2_assets.py [LOGO_PNG_FOLDER]
The source file names below are the owner's; adjust SOURCES if they differ.
"""
import sys
from pathlib import Path

from PIL import Image

DEFAULT_SRC = Path("/Users/mjain/work/projects/travel/BVBMWebsite/01 BVBM Final Logo Assets/RGB File (For Digital)/PNG")
OUT = Path(__file__).resolve().parent.parent / "src" / "aigv2" / "render2" / "assets"

# output name -> (source file stem substring, max width px)
SOURCES = {
    "logo_v1.png": ("Vertical Lockup Logo 1", 1100),
    "logo_v2.png": ("Vertical Lockup Logo 2", 1100),
    "logo_h1.png": ("Horizontal Lockup Logo 1", 1600),
    "icon1.png": ("Icon 1", 600),
}


def crop_and_scale(src: Path, max_w: int) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    box = im.getchannel("A").getbbox()
    if box:
        im = im.crop(box)
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    return im


def main(folder: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(folder.glob("*.png"))
    for out_name, (needle, max_w) in SOURCES.items():
        match = next((f for f in files if needle.lower() in f.stem.lower()), None)
        if match is None:
            print("missing source for", out_name, "(looked for %r)" % needle)
            continue
        crop_and_scale(match, max_w).save(OUT / out_name, optimize=True)
        print("wrote", OUT / out_name)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC)
