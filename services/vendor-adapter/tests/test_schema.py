import pytest
from pydantic import ValidationError

from app.schema import Schema


def test_example_wittra_schema_validates(wittra_schema):
    assert wittra_schema.vendor == "wittra"
    assert wittra_schema.auth.scheme == "basic"
    assert wittra_schema.mapping.frame.const == "wgs84"
    assert wittra_schema.mapping.latitude.path == "-1.location.value.latitude"
    # Discover block ships in the example so the editor's sync flow can be
    # exercised against the local mock-vendor. Real Wittra v4 returns the
    # device array directly (no envelope) so list_path is empty and
    # pagination is disabled.
    assert wittra_schema.discover is not None
    assert wittra_schema.discover.mapping.vendor_device_id.path == "deviceId"
    assert wittra_schema.discover.pagination.type == "none"
    assert wittra_schema.discover.list_path == ""


def test_schema_rejects_extra_top_level_field(wittra_schema_dict):
    wittra_schema_dict["unknown_field"] = "x"
    with pytest.raises(ValidationError):
        Schema.model_validate(wittra_schema_dict)


def test_field_spec_rejects_both_const_and_path():
    bad = {
        "vendor": "v",
        "default_base_url": "http://x",
        "path": "/{device_id}",
        "auth": {"scheme": "none"},
        "mapping": {
            "frame":      {"const": "wgs84"},
            "latitude":   {"const": 1.0, "path": "a"},
            "longitude":  {"const": 0.0},
            "accuracy_m": {"const": 1.0},
            "confidence": {"const": 0.5},
            "y":          {"const": 0.0},
            "timestamp":  {"const": 0.0},
        },
    }
    with pytest.raises(ValidationError):
        Schema.model_validate(bad)


def test_schema_accepts_bearer_auth():
    s = Schema.model_validate({
        "vendor": "v",
        "default_base_url": "http://x",
        "path": "/devices/{device_id}",
        "auth": {"scheme": "bearer", "token": {"env": "VENDOR_TOKEN"}},
        "mapping": {
            "frame":      {"const": "wgs84"},
            "latitude":   {"path": "lat"},
            "longitude":  {"path": "lon"},
            "accuracy_m": {"const": 1.0},
            "confidence": {"const": 0.5},
            "y":          {"const": 0.0},
            "timestamp":  {"path": "ts"},
        },
    })
    assert s.auth.scheme == "bearer"


def test_schema_accepts_header_auth():
    s = Schema.model_validate({
        "vendor": "v",
        "default_base_url": "http://x",
        "path": "/devices/{device_id}",
        "auth": {"scheme": "header", "header": "X-API-Key", "value": {"env": "VENDOR_KEY"}},
        "mapping": {
            "frame":      {"const": "local"},
            "latitude":   {"path": "x"},
            "longitude":  {"path": "z"},
            "accuracy_m": {"const": 1.0},
            "confidence": {"const": 0.5},
            "y":          {"const": 0.0},
            "timestamp":  {"path": "ts"},
        },
    })
    assert s.auth.scheme == "header"
    assert s.auth.header == "X-API-Key"
