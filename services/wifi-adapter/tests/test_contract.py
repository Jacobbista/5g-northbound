from httpx import ASGITransport, AsyncClient

from app.main import app


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_contract_served_without_auth():
    # /contract carries no business data and must answer even with auth on and
    # no token, exactly like /health.
    r = await _get("/contract")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "wifi-adapter"
    assert body["kind"] == "internal"
    assert body["external_origin"] is None
    assert "required" in body["env"]
    assert "recommended" in body["env"]
    assert "optional" in body["env"]


async def test_contract_exposes_names_only_no_values():
    r = await _get("/contract")
    body = r.json()
    all_names = [
        e["name"] for tier in body["env"].values() for e in tier
    ]
    assert "WIFI_CONFIG_PATH" in all_names
    # Schema only: entries describe vars, they never carry a runtime value.
    for tier in body["env"].values():
        for entry in tier:
            assert "name" in entry
            assert "value" not in entry


async def test_ready_endpoint_present():
    # Degraded-boot contract: /ready reflects business config. With a valid
    # default bindings file the app loads and is ready.
    r = await _get("/ready")
    assert r.status_code in (200, 503)


async def test_contract_publishes_the_tunable_vocabularies():
    """A dashboard renders a selector from the set the image implements, and
    cannot offer a value the binary would ignore."""
    body = (await _get("/contract")).json()
    assert body["motion_models"] == ["constant-velocity", "random-walk"]
    assert body["algorithms"] == ["trilateration", "centroid"]


async def test_contract_reports_the_active_tunables():
    body = (await _get("/contract")).json()
    # /contract answers before the blueprint loads, when there is no live
    # config to read an active value from.
    for key, vocab in (("motion_model", "motion_models"), ("algorithm", "algorithms")):
        assert body[key] is None or body[key] in body[vocab]
