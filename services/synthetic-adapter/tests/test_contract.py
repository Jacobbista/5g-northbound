async def test_contract_served_without_auth(client):
    r = await client.get("/contract")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "synthetic-adapter"
    assert body["kind"] == "internal"
    assert body["external_origin"] is None
    names = [e["name"] for tier in body["env"].values() for e in tier]
    assert "DEVICE_IDS" in names
    for tier in body["env"].values():
        for entry in tier:
            assert "value" not in entry
