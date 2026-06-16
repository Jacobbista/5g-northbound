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
def wittra_sample_payload() -> list:
    """Trimmed Wittra v4 get-data response: an array of location
    DeviceDataPoints, ascending by time. The adapter takes the last (most
    recent) element, so the expected fix is the second entry here."""
    def _pt(lat, lon, acc, ts):
        return {
            "dataType": "location",
            "deviceId": "D001",
            "location": {
                "value": {
                    "latitude": lat, "longitude": lon, "height": 1.2,
                    "level": 0, "accuracy": acc, "label": "Lab A",
                    "motion": "stationary",
                },
                "timestamp": ts,
            },
        }
    return [
        _pt(45.060000, 7.650000, 1.20, "2026-06-03 14:35:00.000000+00:00"),
        _pt(45.064547, 7.659272, 0.85, "2026-06-03 14:36:17.000000+00:00"),  # latest
    ]


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
