import pytest

ROLE = "camara-location-read"
RETRIEVE = "/location-retrieval/v0.5/retrieve"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_retrieve_returns_spec_shaped_circle(client, auth_headers, location_validator):
    resp = await client.post(RETRIEVE, json={"device": {"phoneNumber": "+123456789"}}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["area"]["areaType"] == "CIRCLE"
    assert body["area"]["radius"] >= 1
    assert "lastLocationTime" in body
    location_validator.validate(body)


async def test_retrieve_ipv4_device(client, auth_headers, location_validator):
    body = {"device": {"ipv4Address": {"publicAddress": "84.125.93.10", "publicPort": 59765}}}
    resp = await client.post(RETRIEVE, json=body, headers=auth_headers)
    assert resp.status_code == 200
    location_validator.validate(resp.json())


async def test_retrieve_missing_device_422(client, auth_headers):
    resp = await client.post(RETRIEVE, json={"maxAge": 120}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "MISSING_IDENTIFIER"


async def test_retrieve_invalid_phone_400(client, auth_headers):
    resp = await client.post(RETRIEVE, json={"device": {"phoneNumber": "123"}}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_ARGUMENT"
