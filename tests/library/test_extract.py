import json
from pathlib import Path

from docx import Document

from src.common.doc_extractor import SINGLE_PASS_LIMIT
from src.library.ingest_core import extract as extract_mod
from src.library.ingest_core.extract import Extraction, extract_file, merge_chunks
from src.library.ingest_core.prompt import CITY_LISTS, COUNTRY_LISTS, EXTRACTION_PROMPT


class StubClient:
    """Exposes what call_and_parse uses (complete_json), plus usage and cost_usd."""

    def __init__(self, responses, prompt_tokens=100, completion_tokens=40, price=True):
        self._responses = list(responses)
        self.calls: list[str] = []
        self.usage = {"prompt_tokens": 7, "completion_tokens": 3}
        self._pt = prompt_tokens
        self._ct = completion_tokens
        self._price = price

    def complete_json(self, prompt, max_tokens=None, **kwargs):
        self.calls.append(prompt)
        self.usage["prompt_tokens"] += self._pt
        self.usage["completion_tokens"] += self._ct
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp if isinstance(resp, str) else json.dumps(resp)

    @property
    def cost_usd(self):
        if not self._price:
            return None
        return self.usage["prompt_tokens"] * 1e-6 + self.usage["completion_tokens"] * 5e-6


def _docx(path: Path, lines: list[str]) -> Path:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)
    return path


LONG_LINE = "Lunch at Trattoria Mario in Florence serves classic ribollita. " * 4


def test_prompt_names_every_list_and_field():
    assert len(CITY_LISTS) == 13
    for name in ("restaurants", "attractions", "hotels", "local_dishes", "phrases",
                 "safety_tips", "souvenirs", "emergency_contacts", "connectivity_tips",
                 "transport_options", "health_tips", "route_guides", "season_notes"):
        assert name in CITY_LISTS
    assert COUNTRY_LISTS == (
        "plugs", "tipping", "dos_donts", "scams", "insurance", "apps", "money",
        "embassies", "season_notes", "phrases", "safety_tips", "emergency_contacts",
        "connectivity_tips", "health_tips", "transport_options",
    )
    for name in CITY_LISTS + COUNTRY_LISTS:
        assert f'"{name}"' in EXTRACTION_PROMPT, name
    for field in ("covered_cities", "city_countries", "country_content", "currency",
                  "meal_slots", "notes", "entry_fee", "dress_code", "tips",
                  "how_to_use", "covers", "provider", "kind", "price_text",
                  "coverage_countries", "voltage", "purpose", "after_hours",
                  "stops", "suggested_stop", "total_km", "total_time", "minutes"):
        assert f'"{field}"' in EXTRACTION_PROMPT, field
    rendered = EXTRACTION_PROMPT.format(text="DOC BODY")
    assert "DOC BODY" in rendered
    for phrase in ("your hotel", " | "):
        assert phrase in rendered


def test_prompt_states_rules():
    rendered = EXTRACTION_PROMPT.format(text="DOC BODY")
    for marker in ("ADD RESTAURANT", "PRICE UNKNOWN", "WRITE PERSONAL LETTER",
                   "CHECK:", "VERIFY", "\u26a0"):
        assert marker in rendered, marker
    assert "only when a heading or table column the restaurant appears under states the meal" in rendered
    assert "short canonical wording" in rendered
    assert "repeated in each of those countries' country_content entries" in rendered
    assert "section heading the restaurant sits under" in rendered
    assert "Dinner Options in Chamonix Town Centre" in rendered
    assert "nearby_landmarks: landmarks the text places near the restaurant" in rendered
    assert "Type of souvenir | Category | Where to buy" in rendered
    assert '"What to Buy"' in rendered
    assert "city is the origin city" in rendered
    assert "Visa and entry requirements: put them in dos_donts only if phrased as advice" in rendered
    for placeholder in ('"<breakfast|lunch|dinner>"', '"<sim|esim|wifi>"',
                        '"<family|couples|friends|solo|...>"',
                        '"<true only if the text says so, else omit>"'):
        assert placeholder in rendered, placeholder


def test_single_pass_returns_data_and_token_deltas(tmp_path):
    data = {"covered_cities": ["Florence"],
            "restaurants": [{"name": "Trattoria Mario", "city": "Florence",
                             "meal_slots": ["lunch"]}]}
    client = StubClient([data])
    path = _docx(tmp_path / "a.docx", [LONG_LINE] * 3)

    result = extract_file(client, path)

    assert isinstance(result, Extraction)
    assert result.data == data
    assert result.chunks == 1
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 40
    assert abs(result.usd - (100 * 1e-6 + 40 * 5e-6)) < 1e-12
    assert len(client.calls) == 1
    assert "Trattoria Mario" in client.calls[0]


def test_usd_none_when_model_unpriced(tmp_path):
    client = StubClient([{"covered_cities": ["Florence"]}], price=False)
    path = _docx(tmp_path / "a.docx", [LONG_LINE] * 3)
    result = extract_file(client, path)
    assert result is not None and result.usd is None


def test_long_text_chunks_and_merge_dedups(tmp_path, monkeypatch):
    text = ("x" * 1000 + "\n\n") * ((SINGLE_PASS_LIMIT // 1000) + 20)
    monkeypatch.setattr(extract_mod, "read_text", lambda p: text)
    chunk1 = {"covered_cities": ["Florence"], "city_countries": {"Florence": "Italy"},
              "restaurants": [{"name": "Trattoria Mario", "city": "Florence", "notes": "first"}],
              "country_content": [{"country": "Italy", "currency": "EUR",
                                   "tipping": [{"tip": "Tipping is not expected"}]}]}
    chunk2 = {"covered_cities": ["Florence", "Rome"], "city_countries": {"Rome": "Italy"},
              "restaurants": [{"name": "the trattoria mario", "city": "Florence", "notes": "second"},
                              {"name": "Roscioli", "city": "Rome"}],
              "country_content": [{"country": "Italy",
                                   "tipping": [{"tip": "Tipping is not expected"},
                                               {"tip": "Round up taxi fares"}],
                                   "plugs": [{"type": "F", "voltage": "230V"}]}]}
    client = StubClient([chunk1, chunk2])

    result = extract_file(client, tmp_path / "big.docx")

    assert len(client.calls) == 2
    assert result.chunks == 2
    assert result.prompt_tokens == 200 and result.completion_tokens == 80
    d = result.data
    assert d["covered_cities"] == ["Florence", "Rome"]
    assert d["city_countries"] == {"Florence": "Italy", "Rome": "Italy"}
    names = [r["name"] for r in d["restaurants"]]
    assert names == ["Trattoria Mario", "Roscioli"]
    assert d["restaurants"][0]["notes"] == "first"
    assert len(d["country_content"]) == 1
    italy = d["country_content"][0]
    assert italy["currency"] == "EUR"
    assert [t["tip"] for t in italy["tipping"]] == ["Tipping is not expected", "Round up taxi fares"]
    assert italy["plugs"] == [{"type": "F", "voltage": "230V"}]


def test_merge_chunks_keeps_same_name_in_different_cities():
    merged = merge_chunks([
        {"restaurants": [{"name": "Cafe Central", "city": "Vienna"}]},
        {"restaurants": [{"name": "Cafe Central", "city": "Prague"}]},
    ])
    assert len(merged["restaurants"]) == 2


def test_all_chunks_fail_returns_none(tmp_path, monkeypatch):
    text = ("y" * 1000 + "\n\n") * ((SINGLE_PASS_LIMIT // 1000) + 20)
    monkeypatch.setattr(extract_mod, "read_text", lambda p: text)
    client = StubClient([RuntimeError("boom"), "not json at all"])
    assert extract_file(client, tmp_path / "big.docx") is None
    assert len(client.calls) == 2


def test_single_pass_failure_returns_none(tmp_path):
    client = StubClient([RuntimeError("boom")])
    path = _docx(tmp_path / "a.docx", [LONG_LINE] * 3)
    assert extract_file(client, path) is None


def test_short_text_returns_none_without_calling(tmp_path):
    client = StubClient([])
    path = _docx(tmp_path / "short.docx", ["Too short."])
    assert extract_file(client, path) is None
    assert client.calls == []


def test_unreadable_returns_none_without_calling(tmp_path):
    client = StubClient([])
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a docx")
    assert extract_file(client, path) is None
    assert client.calls == []


def test_merge_chunks_ignores_malformed_fields():
    merged = merge_chunks([
        {"covered_cities": "Florence", "city_countries": [["Florence", "Italy"]],
         "country_content": {"country": "Italy"},
         "restaurants": [{"name": "Trattoria Mario", "city": "Florence"}]},
        "not a dict",
        ["also", "not"],
        {"covered_cities": ["Rome", 5], "city_countries": {"Rome": "Italy"},
         "country_content": ["bad", {"country": "Italy", "currency": "EUR"}]},
    ])
    assert merged["covered_cities"] == ["Rome"]
    assert merged["city_countries"] == {"Rome": "Italy"}
    assert merged["country_content"] == [{"country": "Italy", "currency": "EUR"}]
    assert merged["restaurants"] == [{"name": "Trattoria Mario", "city": "Florence"}]


def test_extract_file_survives_malformed_chunks(tmp_path, monkeypatch):
    text = ("z" * 1000 + "\n\n") * ((SINGLE_PASS_LIMIT // 1000) + 20)
    monkeypatch.setattr(extract_mod, "read_text", lambda p: text)
    client = StubClient([
        ["a", "list", "not", "a", "dict"],
        {"covered_cities": "Florence", "city_countries": ["Florence", "Italy"],
         "restaurants": [{"name": "Roscioli", "city": "Rome"}]},
    ])
    result = extract_file(client, tmp_path / "big.docx")
    assert result is not None
    assert result.chunks == 2
    assert result.data == {"restaurants": [{"name": "Roscioli", "city": "Rome"}]}


def test_extract_file_none_when_no_chunk_is_a_dict(tmp_path, monkeypatch):
    text = ("w" * 1000 + "\n\n") * ((SINGLE_PASS_LIMIT // 1000) + 20)
    monkeypatch.setattr(extract_mod, "read_text", lambda p: text)
    client = StubClient([["x"], "[1, 2]"])
    assert extract_file(client, tmp_path / "big.docx") is None
