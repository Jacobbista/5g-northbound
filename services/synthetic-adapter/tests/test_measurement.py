async def test_measurement_shape(client):
    r = await client.get("/measurement/dev-1")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "synthetic"
    assert (body["frame"], body["room"]) == ("room", "room-01")
    assert 0.0 <= body["x"] <= 20.0
    assert 0.0 <= body["y"] <= 30.0
    assert 0.0 <= body["z"] <= 3.0
    assert body["accuracy"] > 0
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["timestamp"], float)


async def test_measurement_per_device_state(client):
    a1 = (await client.get("/measurement/dev-a")).json()
    b1 = (await client.get("/measurement/dev-b")).json()
    a2 = (await client.get("/measurement/dev-a")).json()
    # consecutive polls of the same device should move; different devices independent
    assert (a1["x"], a1["y"]) != (a2["x"], a2["y"]) or (a1["x"], a1["y"]) != (b1["x"], b1["y"])


async def test_no_fix_until_the_blueprint_names_a_room(app, client):
    app.state.walker.room_id = None
    app.state.walker._room_attempt = float("inf")
    r = await client.get("/measurement/dev-1")
    assert r.status_code == 404
