from datetime import datetime, timezone

import httpx
import pytest

ROLE = "camara-location-read"
VERIFY = "/location-verification/v3/verify"

# Mock position is centred near here; a huge radius must match, a tiny one must not.
NEAR = {"latitude": 45.064312, "longitude": 7.659154}


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_verify_true_large_radius(client, auth_headers, verify_validator):
    body = {
        "device": {"assetId": "tool-880"},
        "area": {"areaType": "CIRCLE", "center": NEAR, "radius": 100000},
    }
    resp = await client.post(VERIFY, json=body, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["verificationResult"] == "TRUE"
    assert "matchRate" not in data  # matchRate is only set for PARTIAL
    verify_validator.validate(data)


async def test_verify_false_far_area(client, auth_headers, verify_validator):
    body = {
        "device": {"assetId": "tool-880"},
        "area": {"areaType": "CIRCLE", "center": {"latitude": 0.0, "longitude": 0.0}, "radius": 1000},
    }
    resp = await client.post(VERIFY, json=body, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["verificationResult"] == "FALSE"
    verify_validator.validate(data)


async def test_verify_missing_area_400(client, auth_headers):
    resp = await client.post(VERIFY, json={"device": {"assetId": "tool-880"}}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_ARGUMENT"


async def test_verify_missing_device_422(client, auth_headers):
    body = {"area": {"areaType": "CIRCLE", "center": NEAR, "radius": 1000}}
    resp = await client.post(VERIFY, json=body, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "MISSING_IDENTIFIER"


async def test_verify_maxage_unfulfillable_422(
    client, respx_mock, auth_headers, monkeypatch
):
    """A fix older than maxAge fails with UNABLE_TO_FULFILL_MAX_AGE regardless
    of the verification result."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=httpx.Response(200, json={
            "device_id": "wifi-asset-01", "latitude": 45.064312, "longitude": 7.659154,
            "accuracy_m": 1.5, "timestamp": "2026-06-03T14:36:17+00:00",
            "sources": ["wifi"], "strategy": "weighted_avg",
        })
    )
    body = {
        "device": {"assetId": "tool-880"},
        "area": {"areaType": "CIRCLE", "center": NEAR, "radius": 1000},
        "maxAge": 120,
    }
    resp = await client.post(VERIFY, json=body, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "LOCATION_VERIFICATION.UNABLE_TO_FULFILL_MAX_AGE"


# --- classification with the fix's uncertainty circle (unit) ---


def _pos(lat, lon, r):
    from app.position import Position

    return Position(
        latitude=lat, longitude=lon, radius_m=r,
        last_location_time=datetime.now(timezone.utc),
    )


def _area(lat, lon, r):
    from app.models import Circle, Point

    return Circle(center=Point(latitude=lat, longitude=lon), radius=r)


def test_classify_true_when_fix_circle_fully_inside():
    from app.routers.verification import _classify

    result, match_rate = _classify(_pos(45.0, 7.0, 5), _area(45.0, 7.0, 1000))
    assert result == "TRUE"
    assert match_rate is None


def test_classify_false_when_fix_circle_fully_outside():
    from app.routers.verification import _classify

    result, match_rate = _classify(_pos(45.0, 7.0, 5), _area(0.0, 0.0, 1000))
    assert result == "FALSE"
    assert match_rate is None


def test_classify_partial_when_fix_circle_straddles_boundary():
    from app.routers.verification import _classify

    # Fix centre ~100 m from the area centre (0.0009 deg lat), r_fix 50 m, area
    # radius 100 m -> the uncertainty circle crosses the boundary.
    result, match_rate = _classify(_pos(45.0009, 7.0, 50), _area(45.0, 7.0, 100))
    assert result == "PARTIAL"
    assert 1 <= match_rate <= 99
