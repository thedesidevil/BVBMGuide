"""Cormorant Garamond discovery and ECMA-376 font embedding for render2 documents."""
from __future__ import annotations

import io
import struct
import uuid
import zipfile
from pathlib import Path

from lxml import etree

from .theme import ASSETS, HEAD, HEAD_FALLBACK

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
FONT_REL = R + "/font"
ODTTF_CT = "application/vnd.openxmlformats-officedocument.obfuscatedFont"

_FILES = ("CormorantGaramond-Regular.ttf", "CormorantGaramond-Bold.ttf",
          "CormorantGaramond-Italic.ttf", "CormorantGaramond-BoldItalic.ttf")
_STYLE_TAG = {"Regular": "embedRegular", "Bold": "embedBold",
              "Italic": "embedItalic", "BoldItalic": "embedBoldItalic"}


def _w(tag: str) -> str:
    return "{%s}%s" % (W, tag)


def find_cormorant() -> list[Path]:
    """TTFs found in ~/Library/Fonts, else the bundled assets/fonts folder, else []."""
    for folder in (Path.home() / "Library" / "Fonts", ASSETS / "fonts"):
        found = [folder / n for n in _FILES if (folder / n).is_file()]
        if found:
            return found
    return []


def _fs_type(data: bytes) -> int:
    """OS/2 fsType of a TrueType/OpenType font; 0 when there is no OS/2 table."""
    num = struct.unpack_from(">H", data, 4)[0]
    for i in range(num):
        tag, _chk, off, length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if tag == b"OS/2":
            return struct.unpack_from(">H", data, off + 8)[0]
    return 0


def font_is_embeddable(path: Path) -> bool:
    try:
        fs = _fs_type(Path(path).read_bytes())
    except (OSError, struct.error):
        return False
    if fs & 0x0002:
        return False
    return fs == 0 or bool(fs & (0x0008 | 0x0004))


def _style_of(path: Path) -> str | None:
    stem = Path(path).stem
    suffix = stem.rsplit("-", 1)[-1] if "-" in stem else "Regular"
    return suffix if suffix in _STYLE_TAG else None


def _obfuscate(data: bytes, guid: uuid.UUID) -> bytes:
    key = guid.bytes[::-1]
    head = bytes(b ^ key[i % 16] for i, b in enumerate(data[:32]))
    return head + data[32:]


# Children of w:settings that precede embedTrueTypeFonts in the schema sequence.
_BEFORE_EMBED = ("writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
                 "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
                 "printFractionalCharacterWidth", "printFormsData")


def _patch_settings(blob: bytes) -> bytes:
    root = etree.fromstring(blob)
    if root.find(_w("embedTrueTypeFonts")) is None:
        idx = 0
        for i, ch in enumerate(root):
            if etree.QName(ch).localname in _BEFORE_EMBED:
                idx = i + 1
        root.insert(idx, etree.Element(_w("embedTrueTypeFonts")))
    if root.find(_w("saveSubsetFonts")) is None:
        e = root.find(_w("embedTrueTypeFonts"))
        i = list(root).index(e) + 1
        if i < len(root) and etree.QName(root[i]).localname == "embedSystemFonts":
            i += 1
        root.insert(i, etree.Element(_w("saveSubsetFonts")))
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def embed_fonts(docx_bytes: bytes, ttf_paths: list[Path]) -> bytes:
    fonts = []
    for p in ttf_paths or []:
        style = _style_of(Path(p))
        if style and font_is_embeddable(Path(p)):
            fonts.append((Path(p), style))
    if not fonts:
        return docx_bytes

    zin = zipfile.ZipFile(io.BytesIO(docx_bytes))
    parts = {n: zin.read(n) for n in zin.namelist()}
    order = zin.namelist()
    zin.close()

    # content types
    ct = etree.fromstring(parts["[Content_Types].xml"])
    if not any(d.get("Extension", "").lower() == "odttf" for d in ct.findall("{%s}Default" % CT_NS)):
        d = etree.Element("{%s}Default" % CT_NS)
        d.set("Extension", "odttf")
        d.set("ContentType", ODTTF_CT)
        ct.insert(0, d)
    parts["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)

    # font table
    ft_name = "word/fontTable.xml"
    if ft_name in parts:
        ft = etree.fromstring(parts[ft_name])
    else:
        ft = etree.Element(_w("fonts"), nsmap={"w": W, "r": R})
        order.append(ft_name)
        ct = etree.fromstring(parts["[Content_Types].xml"])
        o = etree.SubElement(ct, "{%s}Override" % CT_NS)
        o.set("PartName", "/" + ft_name)
        o.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml")
        parts["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)
        # document rels must point at it
        drel = etree.fromstring(parts["word/_rels/document.xml.rels"])
        r = etree.SubElement(drel, "{%s}Relationship" % REL_NS)
        r.set("Id", "rIdFontTable")
        r.set("Type", R + "/fontTable")
        r.set("Target", "fontTable.xml")
        parts["word/_rels/document.xml.rels"] = etree.tostring(drel, xml_declaration=True, encoding="UTF-8", standalone=True)
    font = next((f for f in ft.findall(_w("font")) if f.get(_w("name")) == HEAD), None)
    if font is None:
        font = etree.SubElement(ft, _w("font"))
        font.set(_w("name"), HEAD)
        etree.SubElement(font, _w("altName")).set(_w("val"), HEAD_FALLBACK)
        etree.SubElement(font, _w("charset")).set(_w("val"), "00")
        etree.SubElement(font, _w("family")).set(_w("val"), "roman")
        etree.SubElement(font, _w("pitch")).set(_w("val"), "variable")

    # font table rels
    rels_name = "word/_rels/fontTable.xml.rels"
    rels = etree.fromstring(parts[rels_name]) if rels_name in parts else etree.Element(
        "{%s}Relationships" % REL_NS, nsmap={None: REL_NS})
    if rels_name not in parts:
        order.append(rels_name)

    # canonical order of embed elements in the schema
    for n, (path, style) in enumerate(fonts, 1):
        guid = uuid.uuid4()
        part = "word/fonts/font%d.odttf" % n
        parts[part] = _obfuscate(path.read_bytes(), guid)
        order.append(part)
        rid = "rIdFont%d" % n
        rel = etree.SubElement(rels, "{%s}Relationship" % REL_NS)
        rel.set("Id", rid)
        rel.set("Type", FONT_REL)
        rel.set("Target", "fonts/font%d.odttf" % n)
        tag = _STYLE_TAG[style]
        for old in font.findall(_w(tag)):
            font.remove(old)
        e = etree.SubElement(font, _w(tag))
        e.set("{%s}id" % R, rid)
        e.set(_w("fontKey"), "{%s}" % str(guid).upper())
    # schema order: embedRegular, embedBold, embedItalic, embedBoldItalic last
    embeds = sorted((c for c in font if etree.QName(c).localname in _STYLE_TAG.values()),
                    key=lambda c: list(_STYLE_TAG.values()).index(etree.QName(c).localname))
    for c in embeds:
        font.remove(c)
        font.append(c)
    if "r" not in (ft.nsmap or {}):
        etree.cleanup_namespaces(ft, top_nsmap={"r": R})

    parts[ft_name] = etree.tostring(ft, xml_declaration=True, encoding="UTF-8", standalone=True)
    parts[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    if "word/settings.xml" in parts:
        parts["word/settings.xml"] = _patch_settings(parts["word/settings.xml"])

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, parts[n])
    return out.getvalue()
