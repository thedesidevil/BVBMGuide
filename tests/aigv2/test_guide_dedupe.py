import json
from pathlib import Path

from src.aigv2.guide.dedupe import split_top_level, souvenir_items

TEXTILES = ("Batik & Ikat Textiles, Batik fabrics, sarongs, handwoven scarves, cotton shirts, handmade bags, "
            "Batik, sarongs, handwoven scarves and cotton shirts, Batik fabrics, sarongs, handwoven scarves, "
            "cotton shirts and handmade bags, Batik & Ikat Fabrics, Batik and Ikat Fabric")
HANDI = ("Wooden Handicrafts & Ceramics, Handmade goods and artisan souvenirs, Handicrafts, fabrics, souvenirs, "
         "paintings, home décor, Handicrafts, fabrics, paintings, home décor, Rattan bags, handmade silver jewelry, "
         "batik scarves, wooden crafts, woven baskets, Rattan Bags, Handmade products (bags, wooden bowls, shell items)")


def test_split_ignores_parentheses():
    assert split_top_level("A (x, y); B, c") == ["A (x, y)", "B", "c"]


def test_textiles_collapse():
    out = souvenir_items(TEXTILES)
    low = " ".join(out).lower()
    assert len(out) <= 5 and "batik & ikat textiles" in low and "sarongs" in low
    assert not any(o.lower() in ("batik", "batik fabrics", "batik & ikat fabrics", "batik and ikat fabric") for o in out)


def test_handicrafts_no_exact_dupes_and_cap():
    out = souvenir_items(HANDI)
    assert len({o.lower() for o in out}) == len(out) and len(out) <= 8
    assert sum(o.lower() == "rattan bags" for o in out) == 1


def test_cap_eight():
    assert len(souvenir_items(", ".join(f"item{chr(97 + i)}x{i}" for i in range(12)))) == 8


def test_exact_duplicate_fragment_dropped_unique_kept():
    assert souvenir_items("Snacks and clothing, Snacks and clothing") == ["Snacks and clothing"]
