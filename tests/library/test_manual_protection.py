import copy
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.library.ingest_core.merge import FileMeta, merge_extraction
from src.library.ui import create_app


@pytest.fixture
def client(memory_backend):
    return TestClient(create_app(storage_backend=memory_backend))


def _shard():
    return {
        "restaurants": [
            {"name": "Roscioli", "city": "Rome", "hours": "9-5",
             "_source_file": "italy/a.docx", "_source_date": "2025-01-01",
             "_source_format": "new"},
            {"name": "Armando", "city": "Rome", "hours": "10-10",
             "_source_file": "italy/a.docx"},
        ],
        "route_guides": [{"from": "Rome", "to": "Florence", "how": "train"}],
        "season_notes": [{"tip": "Summer is hot"}],
        "currency": {"code": "EUR"},
        "_conflicts": [{"list": "restaurants", "key": "x"}],
    }


def test_edit_flags_only_edited_item(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    body = client.get("/api/city/Rome").json()
    body["restaurants"][0]["hours"] = "8-6"
    body["changed_by"] = "marina"
    assert client.put("/api/city/Rome", json=body).status_code == 200
    r = memory_db.get_city_data("Rome")["restaurants"]
    assert r[0]["_manual"] is True and r[0]["_manual_by"] == "marina"
    assert r[0]["_manual_at"]
    assert r[0]["_source_file"] == "italy/a.docx"
    assert "_manual" not in r[1]


def test_default_changed_by_unknown(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    body = client.get("/api/city/Rome").json()
    body["restaurants"][1]["hours"] = "x"
    client.put("/api/city/Rome", json=body)
    assert memory_db.get_city_data("Rome")["restaurants"][1]["_manual_by"] == "unknown"


def test_added_item_flagged(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    body = client.get("/api/city/Rome").json()
    body["restaurants"].append({"name": "New Place", "city": "Rome"})
    client.put("/api/city/Rome", json=body)
    r = memory_db.get_city_data("Rome")["restaurants"]
    assert r[2]["_manual"] is True
    assert "_manual" not in r[0] and "_manual" not in r[1]


def test_untouched_roundtrip_preserves_everything(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    body = client.get("/api/city/Rome").json()
    client.put("/api/city/Rome", json=copy.deepcopy(body))
    assert memory_db.get_city_data("Rome") == _shard()


def test_put_without_conflicts_keeps_stored_conflicts(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    body = client.get("/api/city/Rome").json()
    del body["_conflicts"]
    client.put("/api/city/Rome", json=body)
    assert memory_db.get_city_data("Rome")["_conflicts"] == _shard()["_conflicts"]


def test_existing_manual_flags_kept_unless_edited(client, memory_db):
    s = _shard()
    s["restaurants"][0].update(_manual=True, _manual_by="old", _manual_at="2020-01-01")
    memory_db.save_city_data("Rome", s)
    body = client.get("/api/city/Rome").json()
    client.put("/api/city/Rome", json=copy.deepcopy(body))
    r = memory_db.get_city_data("Rome")["restaurants"][0]
    assert (r["_manual_by"], r["_manual_at"]) == ("old", "2020-01-01")
    body["restaurants"][0]["hours"] = "new"
    body["changed_by"] = "marina"
    client.put("/api/city/Rome", json=body)
    r = memory_db.get_city_data("Rome")["restaurants"][0]
    assert r["_manual_by"] == "marina" and r["_manual_at"] != "2020-01-01"


def test_sweep_edit_flags_item(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    resp = client.put("/api/sweep", json={"changed_by": "marina", "edits": [
        {"city": "Rome", "index": 1, "category": "restaurants",
         "field": "hours", "value": "11-11"}]})
    assert resp.status_code == 200
    r = memory_db.get_city_data("Rome")["restaurants"]
    assert r[1]["_manual"] is True and r[1]["_manual_by"] == "marina"
    assert "_manual" not in r[0]


def test_manual_item_survives_newer_disagreeing_ingest(client, memory_db):
    memory_db.save_city_data("Rome", _shard())
    body = client.get("/api/city/Rome").json()
    body["restaurants"][0]["hours"] = "hand"
    client.put("/api/city/Rome", json=body)
    before = memory_db.get_city_data("Rome")["restaurants"][0]
    data = {"covered_cities": ["Rome"], "city_countries": {"Rome": "Italy"},
            "restaurants": [{"name": "Roscioli", "city": "Rome", "hours": "ai"}]}
    merge_extraction(memory_db, data, FileMeta("italy/z.docx", date(2026, 1, 1), "new", "italy"))
    shard = memory_db.get_city_data("Rome")
    assert shard["restaurants"][0] == before
    assert shard["restaurants"][0]["hours"] == "hand"
    assert any(c.get("incoming", {}).get("hours") == "ai" for c in shard["_conflicts"])
