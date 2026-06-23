from src.hotel_options.codes import CodeStore
from src.library.ui.storage import LocalStorageBackend


def test_load_returns_seeds_when_file_missing(tmp_path):
    store = CodeStore(LocalStorageBackend(tmp_path))
    codes = store.load()
    assert codes["nr"] == "Non-refundable"
    assert codes["br"] == "Breakfast included"


def test_save_and_reload(tmp_path):
    store = CodeStore(LocalStorageBackend(tmp_path))
    codes = store.load()
    codes["hb"] = "Half board included"
    store.save(codes)

    store2 = CodeStore(LocalStorageBackend(tmp_path))
    reloaded = store2.load()
    assert reloaded["hb"] == "Half board included"
    assert reloaded["nr"] == "Non-refundable"  # seed preserved


def test_save_does_not_lose_seeds(tmp_path):
    store = CodeStore(LocalStorageBackend(tmp_path))
    store.save({"hb": "Half board"})
    reloaded = store.load()
    assert reloaded["nr"] == "Non-refundable"
