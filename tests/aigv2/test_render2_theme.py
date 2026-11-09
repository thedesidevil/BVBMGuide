import io
import struct
import uuid
import zipfile

import pytest
from docx import Document
from lxml import etree
from PIL import Image

from src.aigv2.render2 import fonts, theme

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def test_all_text_pairs_pass_contrast():
    bad = [(a, b, theme.contrast(a, b)) for a, b in theme.PAIRS if theme.contrast(a, b) < 4.5]
    assert not bad


def test_contrast_function_known_values():
    assert theme.contrast("000000", "FFFFFF") == pytest.approx(21.0)
    assert theme.contrast("3A6CB5", "3A6CB5") == pytest.approx(1.0)


@pytest.mark.parametrize("name", ["logo_v1.png", "logo_v2.png", "logo_h1.png", "icon1.png",
                                  "diamond_gold.png", "ornament.png", "dot.png"])
def test_logo_assets_are_cropped(name):
    p = theme.asset(name)
    assert p.exists()
    im = Image.open(p)
    assert "A" in im.mode
    assert im.width <= 1700
    if name == "ornament.png":  # a thin rule: only the horizontal extent is tight
        l, _t, r, _b = im.getchannel("A").getbbox()
        assert l <= 2 and im.width - r <= 2
        return
    l, t, r, b = im.getchannel("A").getbbox()
    assert l <= 2 and t <= 2 and im.width - r <= 2 and im.height - b <= 2


def make_ttf(fs_type=0):
    os2 = struct.pack(">HhHH", 4, 500, 400, 5) + struct.pack(">H", fs_type) + b"\0" * 80
    body = bytes(range(256)) * 2
    off_os2 = 12 + 16 * 2 + len(body)
    head = struct.pack(">IHHHH", 0x00010000, 2, 32, 1, 0)
    d = struct.pack(">4sIII", b"OS/2", 0, off_os2, len(os2)) + struct.pack(">4sIII", b"glyf", 0, 12 + 32, len(body))
    # tables sorted by tag: 'OS/2' < 'glyf'
    return head + d + body + os2


def docx_bytes():
    d = Document()
    d.add_paragraph("hi")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def write_ttf(tmp_path, fs_type=0, name="CormorantGaramond-Regular.ttf"):
    p = tmp_path / name
    p.write_bytes(make_ttf(fs_type))
    return p


def test_embed_fonts_adds_parts(tmp_path):
    ttf = write_ttf(tmp_path)
    out = fonts.embed_fonts(docx_bytes(), [ttf])
    z = zipfile.ZipFile(io.BytesIO(out))
    assert "word/fonts/font1.odttf" in z.namelist()
    assert b'Extension="odttf"' in z.read("[Content_Types].xml")
    ft = etree.fromstring(z.read("word/fontTable.xml"))
    emb = ft.find(".//{%s}embedRegular" % W)
    assert emb is not None
    rid = emb.get("{%s}id" % R)
    rels = etree.fromstring(z.read("word/_rels/fontTable.xml.rels"))
    rel = [r for r in rels if r.get("Id") == rid][0]
    assert rel.get("Target") == "fonts/font1.odttf" and rel.get("Type").endswith("/font")
    assert etree.fromstring(z.read("word/settings.xml")).find("{%s}embedTrueTypeFonts" % W) is not None
    Document(io.BytesIO(out))


def test_embed_roundtrip_deobfuscates(tmp_path):
    ttf = write_ttf(tmp_path)
    out = fonts.embed_fonts(docx_bytes(), [ttf])
    z = zipfile.ZipFile(io.BytesIO(out))
    ft = etree.fromstring(z.read("word/fontTable.xml"))
    key = ft.find(".//{%s}embedRegular" % W).get("{%s}fontKey" % W)
    key_bytes = uuid.UUID(key.strip("{}")).bytes[::-1]
    ob = z.read("word/fonts/font1.odttf")
    head = bytes(b ^ key_bytes[i % 16] for i, b in enumerate(ob[:32]))
    assert head + ob[32:] == ttf.read_bytes()
    assert ob != ttf.read_bytes()


def test_embed_skips_restricted_font(tmp_path):
    ttf = write_ttf(tmp_path, fs_type=2)
    assert not fonts.font_is_embeddable(ttf)
    data = docx_bytes()
    assert fonts.embed_fonts(data, [ttf]) == data


def test_embed_noop_without_fonts():
    data = docx_bytes()
    assert fonts.embed_fonts(data, []) == data


def test_find_cormorant_returns_existing_paths_only():
    for p in fonts.find_cormorant():
        assert p.exists()


def test_crimson_allowed_backgrounds():
    for bg in theme.CRIMSON_ALLOWED_BG:
        assert theme.contrast(theme.CRIMSON, bg) >= 4.5
    # documented: crimson text on the harbour fill fails, so it must not be used
    assert theme.contrast(theme.CRIMSON, theme.HARBOUR_FILL) < 4.5
    assert (theme.CRIMSON, theme.HARBOUR_FILL) not in theme.PAIRS


def test_find_cormorant_merges_folders(tmp_path, monkeypatch):
    home, assets = tmp_path / "home", tmp_path / "assets"
    (home / "Library" / "Fonts").mkdir(parents=True)
    (assets / "fonts").mkdir(parents=True)
    for n in fonts._FILES[:2]:
        (home / "Library" / "Fonts" / n).write_bytes(b"x")
    for n in fonts._FILES[1:]:
        (assets / "fonts" / n).write_bytes(b"x")
    monkeypatch.setattr(fonts.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(fonts, "ASSETS", assets)
    got = fonts.find_cormorant()
    assert [p.name for p in got] == list(fonts._FILES)
    assert got[1].parent == home / "Library" / "Fonts"
    assert got[3].parent == assets / "fonts"


def test_find_cormorant_without_home(monkeypatch):
    def boom(cls):
        raise RuntimeError("no home")
    monkeypatch.setattr(fonts.Path, "home", classmethod(boom))
    assert isinstance(fonts.find_cormorant(), list)


_SETTINGS_ORDER = ["writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
                   "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
                   "printFractionalCharacterWidth", "printFormsData", "embedTrueTypeFonts",
                   "embedSystemFonts", "saveSubsetFonts"]


def test_settings_order_after_embedding(tmp_path):
    out = fonts.embed_fonts(docx_bytes(), [write_ttf(tmp_path)])
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(out)).read("word/settings.xml"))
    names = [etree.QName(c).localname for c in root]
    assert "embedTrueTypeFonts" in names and "saveSubsetFonts" in names
    known = [n for n in names if n in _SETTINGS_ORDER]
    assert known == sorted(known, key=_SETTINGS_ORDER.index)
    assert names.index("embedTrueTypeFonts") < names.index("saveSubsetFonts")


def test_existing_font_keeps_alt_name_before_embeds(tmp_path):
    data = docx_bytes()
    zin = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in zin.namelist():
            b = zin.read(n)
            if n == "word/fontTable.xml":
                root = etree.fromstring(b)
                f = etree.SubElement(root, "{%s}font" % W)
                f.set("{%s}name" % W, "Cormorant Garamond")
                etree.SubElement(f, "{%s}altName" % W).set("{%s}val" % W, "Garamond")
                b = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            z.writestr(n, b)
    out = fonts.embed_fonts(buf.getvalue(), [write_ttf(tmp_path)])
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(out)).read("word/fontTable.xml"))
    fl = [f for f in root if f.get("{%s}name" % W) == "Cormorant Garamond"]
    assert len(fl) == 1
    kids = [etree.QName(c).localname for c in fl[0]]
    assert kids.index("altName") < kids.index("embedRegular")
