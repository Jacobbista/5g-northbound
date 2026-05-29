ROLE = "camara-location-read"
RETRIEVE = "/location-retrieval/v0.5/retrieve"
BODY = {"device": {"phoneNumber": "+123456789"}}


async def test_missing_token_401(client):
    resp = await client.post(RETRIEVE, json=BODY)
    assert resp.status_code == 401
    body = resp.json()
    assert body["status"] == 401
    assert body["code"] == "UNAUTHENTICATED"
    assert "message" in body


async def test_invalid_token_401(client):
    resp = await client.post(RETRIEVE, json=BODY, headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


async def test_expired_token_401(client, make_token):
    token = make_token(roles=[ROLE], exp_offset=-10)
    resp = await client.post(RETRIEVE, json=BODY, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


async def test_valid_token_without_role_403(client, make_token):
    token = make_token(roles=["some-other-role"])
    resp = await client.post(RETRIEVE, json=BODY, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "PERMISSION_DENIED"


async def test_valid_token_with_role_200(client, make_token):
    token = make_token(roles=[ROLE])
    resp = await client.post(RETRIEVE, json=BODY, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
