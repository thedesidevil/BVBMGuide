import json
from pathlib import Path

import pytest

from src.library.ui.services.db_service import LibraryDBService
from src.library.ui.storage import LocalStorageBackend


@pytest.fixture
def db_service(local_db):
    backend = LocalStorageBackend(local_db)
    return LibraryDBService(backend)


class TestLibraryDBService:
    def test_get_folder_coverage(self, db_service):
        coverage = db_service.get_folder_coverage()
        assert "italy" in coverage
        assert "Rome" in coverage["italy"]

    def test_get_city_data(self, db_service):
        data = db_service.get_city_data("Rome")
        assert data is not None
        assert data["restaurants"][0]["name"] == "Trattoria Roma"

    def test_get_city_data_missing(self, db_service):
        assert db_service.get_city_data("Atlantis") is None

    def test_save_city_data(self, db_service):
        db_service.save_city_data("Rome", {"restaurants": [], "attractions": []})
        data = db_service.get_city_data("Rome")
        assert data["restaurants"] == []

    def test_get_country_data(self, db_service):
        data = db_service.get_country_data("Italy")
        assert data is not None
        assert data["safety_tips"][0]["tip"] == "Watch for pickpockets"

    def test_save_country_data(self, db_service):
        db_service.save_country_data("Italy", {"safety_tips": []})
        data = db_service.get_country_data("Italy")
        assert data["safety_tips"] == []

    def test_get_all_city_names(self, db_service):
        names = db_service.get_all_city_names()
        assert "Rome" in names
        assert "Florence" in names
        assert "_index" not in names

    def test_set_review_status(self, db_service):
        db_service.set_review_status("Rome", "reviewed", "marina")
        status = db_service.get_review_status()
        assert status["Rome"]["status"] == "reviewed"
        assert status["Rome"]["reviewed_by"] == "marina"

    def test_get_tree(self, db_service):
        tree = db_service.get_tree()
        assert "italy" in tree
        city_names = [c["name"] for c in tree["italy"]["cities"]]
        assert "Rome" in city_names
