import json

import pytest

from app.store import State, load_schema, save_schema


def test_load_schema_missing_file_returns_none(tmp_path):
    assert load_schema(str(tmp_path / "absent.json")) is None


def test_load_schema_invalid_json_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json")
    assert load_schema(str(p)) is None


def test_load_schema_invalid_shape_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"vendor": "x"}))  # missing required fields
    assert load_schema(str(p)) is None


def test_save_and_load_roundtrip(tmp_path, wittra_schema):
    path = tmp_path / "schema.json"
    assert save_schema(str(path), wittra_schema) is True
    loaded = load_schema(str(path))
    assert loaded is not None
    assert loaded.vendor == "wittra"


def test_save_schema_falls_back_to_in_place_when_rename_fails(tmp_path, wittra_schema, monkeypatch):
    # A bind-mounted single file cannot be replaced via rename (EBUSY); the
    # in-place write must still land the schema.
    path = tmp_path / "schema.json"
    path.write_text("{}")

    def boom(src, dst):
        raise OSError(16, "Device or resource busy")

    monkeypatch.setattr("app.store.os.replace", boom)
    assert save_schema(str(path), wittra_schema) is True
    assert load_schema(str(path)).vendor == "wittra"


def test_save_schema_returns_false_on_read_only_mount(tmp_path, wittra_schema, monkeypatch):
    # ConfigMap / subPath: rename AND in-place write both fail (read-only) ->
    # save_schema returns False rather than raising, so PUT can report it.
    path = tmp_path / "schema.json"

    def boom(*a, **k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr("app.store.os.replace", boom)
    monkeypatch.setattr("app.store.tempfile.mkstemp", boom)
    monkeypatch.setattr("app.store.Path.write_text", lambda self, data: (_ for _ in ()).throw(OSError(30, "ro")))
    assert save_schema(str(path), wittra_schema) is False


def test_cache_returns_none_when_empty():
    s = State()
    assert s.cache_get("d1") is None


def test_cache_put_then_get():
    s = State()
    s.cache_put("d1", {"x": 1}, ttl_s=10.0)
    assert s.cache_get("d1") == {"x": 1}


def test_cache_expires(monkeypatch):
    s = State()
    fake = [100.0]
    monkeypatch.setattr("app.store.time.monotonic", lambda: fake[0])
    s.cache_put("d1", {"x": 1}, ttl_s=5.0)
    fake[0] += 6.0
    assert s.cache_get("d1") is None


def test_cache_clear_removes_entries():
    s = State()
    s.cache_put("d1", 1, ttl_s=10.0)
    s.cache_put("d2", 2, ttl_s=10.0)
    s.cache_clear()
    assert s.cache_get("d1") is None
    assert s.cache_get("d2") is None
