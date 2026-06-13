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
    """Trimmed Wittra v4 telemetry response (single device)."""
    return {
        "deviceId": "D001",
        "dataType": "telemetry",
        "telemetryId": "t-001",
        "source": "p",
        "location": {
            "telemetryId": "loc-001",
            "value": {
                "latitude": 45.064547,
                "longitude": 7.659272,
                "height": 1.2,
                "level": 0,
                "accuracy": 0.85,
                "label": "Lab A",
                "motion": "stationary",
            },
            "timestamp": "2026-06-03T14:36:17.000000+00:00",
        },
    }


@pytest.fixture
def wittra_sample_discover_page() -> list:
    """Trimmed Wittra v4 device-list response. Real v4 returns the array
    directly with no envelope, so the example schema uses
    `list_path: ""` and `pagination.type: "none"`."""
    return [
        {
            "deviceId": "D001",
            "deviceType": "beacon",
            "isPositioningActive": True,
            "fixedLocation": {
                "latitude": 45.064547,
                "longitude": 7.659272,
                "level": 0,
            },
            "lastSeen": None,
        },
        {
            "deviceId": "D002",
            "deviceType": "beacon",
            "isPositioningActive": True,
            "fixedLocation": {
                "latitude": 45.064600,
                "longitude": 7.659300,
                "level": 0,
            },
            "lastSeen": None,
        },
    ]
