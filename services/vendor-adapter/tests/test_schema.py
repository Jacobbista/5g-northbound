import pytest
from pydantic import ValidationError

from app.schema import Schema


def test_example_wittra_schema_validates(wittra_schema):
    assert wittra_schema.vendor == "wittra"
    assert wittra_schema.auth.scheme == "basic"
    assert wittra_schema.mapping.frame.const == "wgs84"
    assert wittra_schema.mapping.latitude.path == "latest.data.location.value.latitude"
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


def test_mapping_omits_optional_y_and_confidence():
    # A wgs84 vendor with no height/confidence source omits both instead of
    # const-stuffing; they default to None (the mapper emits 0.0).
    s = Schema.model_validate({
        "vendor": "v",
        "default_base_url": "http://x",
        "path": "/devices/{device_id}",
        "auth": {"scheme": "none"},
        "mapping": {
            "frame":      {"const": "wgs84"},
            "latitude":   {"path": "lat"},
            "longitude":  {"path": "lon"},
            "accuracy_m": {"path": "acc"},
            "timestamp":  {"path": "ts"},
        },
    })
    assert s.mapping.y is None
    assert s.mapping.confidence is None


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


def test_diagnostics_block_parses(wittra_schema_dict):
    d = dict(wittra_schema_dict)
    d["diagnostics"] = {
        "stream": {"motion": {"path": "latest.data.location.value.motion"}},
        "on_demand": [
            {
                "path": "/v4/organizations/{org_id}/projects/{project_id}/devices/{device_id}",
                "mapping": {
                    "accuracy_value": {"path": "latest.data.location.value.accuracy"},
                    "accuracy_kind": {"const": "vendor-radius"},
                },
            }
        ],
    }
    sc = Schema.model_validate(d)
    assert "motion" in sc.diagnostics.stream
    assert sc.diagnostics.on_demand[0].mapping["accuracy_kind"].const == "vendor-radius"


def test_diagnostics_absent_is_none(wittra_schema_dict):
    d = dict(wittra_schema_dict)
    d.pop("diagnostics", None)
    assert Schema.model_validate(d).diagnostics is None


def test_example_schema_declares_diagnostics(wittra_schema):
    assert "motion" in wittra_schema.diagnostics.stream
    assert wittra_schema.diagnostics.on_demand[0].mapping["accuracy_kind"].const == "vendor-radius"
