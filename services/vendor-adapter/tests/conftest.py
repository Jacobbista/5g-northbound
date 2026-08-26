import json
from pathlib import Path

import pytest

from app.schema import Schema

_EXAMPLE_SCHEMA = (
    Path(__file__).resolve().parents[1] / "examples" / "wittra-schema.json"
)


@pytest.fixture
def wittra_schema_dict() -> dict:
    return json.loads(_EXAMPLE_SCHEMA.read_text())


@pytest.fixture
def wittra_schema(wittra_schema_dict) -> Schema:
    return Schema.model_validate(wittra_schema_dict)


@pytest.fixture
def wittra_sample_payload() -> dict:
    """Trimmed Wittra v4 GET /devices/{id} snapshot: the current fix under
    latest.data.location, WGS84 at full precision."""
    return {
        "deviceId": "D001",
        "deviceType": "tag",
        "latest": {
            "data": {
                "location": {
                    "timestamp": "2026-06-03 14:36:17.000000+00:00",
                    "value": {
                        "latitude": 45.064547, "longitude": 7.659272, "height": 1.2,
                        "level": 0, "accuracy": 0.85, "label": "",
                        "motion": "STATIONARY",
                    },
                }
            }
        },
    }


@pytest.fixture
def wittra_sample_discover_page() -> list:
    """Trimmed Wittra v4 device-list response, mirroring the real shape: the
    array comes back directly with no envelope (the example schema uses
    `list_path: ""`, `pagination.type: "none"`), each record carries a clean
    `deviceType` string + a human `name`, and only anchors have `fixedLocation`.
    Three device classes so classification is exercised: a fixed beacon
    (infrastructure), a meshrouter with no fixedLocation (still infrastructure),
    and a mobile tag (the only onboardable asset)."""
    return [
        {
            "deviceId": "D001",
            "deviceType": "beacon",
            "name": "Position Beacon 01",
            "isPositioningActive": True,
            "fixedLocation": {
                "latitude": 45.064547,
                "longitude": 7.659272,
                "height": 2.0,
                "level": 0,
            },
            "lastSeen": None,
        },
        {
            "deviceId": "MR1",
            "deviceType": "meshrouter",
            "name": "Mesh Router 01",
            "isPositioningActive": True,
            "fixedLocation": None,
            "lastSeen": None,
        },
        {
            "deviceId": "TAG1",
            "deviceType": "tag",
            "name": "Asset Tag 01",
            "isPositioningActive": True,
            "fixedLocation": None,
            "lastSeen": None,
        },
    ]
