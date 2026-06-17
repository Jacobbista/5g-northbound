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
    assert "matchRate" not in data  # MVP omits matchRate
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
