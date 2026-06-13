async def test_measurement_shape(client):
    r = await client.get("/measurement/dev-1")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "mock"
    assert body["frame"] == "local"
    assert 0.0 <= body["x"] <= 20.0
    assert 0.0 <= body["z"] <= 30.0
    assert body["accuracy_m"] > 0
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["timestamp"], float)


async def test_measurement_per_device_state(client):
    a1 = (await client.get("/measurement/dev-a")).json()
    b1 = (await client.get("/measurement/dev-b")).json()
    a2 = (await client.get("/measurement/dev-a")).json()
    # consecutive polls of the same device should move; different devices independent
    assert (a1["x"], a1["z"]) != (a2["x"], a2["z"]) or (a1["x"], a1["z"]) != (b1["x"], b1["z"])
