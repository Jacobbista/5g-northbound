import httpx
import pytest

ROLE = "camara-location-read"
ASSETS = "/assets"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_assets_requires_auth(client):
    resp = await client.get(ASSETS)
    assert resp.status_code == 401


async def test_get_assets_lists_seeded_map(client, auth_headers):
    resp = await client.get(ASSETS, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 4
    ids = {a["assetId"] for a in body["assets"]}
    assert ids == {"tool-880", "forklift-7", "pkg-4471"}
    by_id = {a["assetId"]: a for a in body["assets"]}
    assert by_id["pkg-4471"]["capabilities"][0]["positioningId"] == "wittra-tag-01"
    assert by_id["pkg-4471"]["org"] == "acme"
    assert "simulated" not in by_id["forklift-7"]


async def test_put_assets_replaces_map(client, auth_headers):
    new_map = {
        "version": 4,
        "assets": [
            {"assetId": "drill-1", "kind": "tool", "org": "atlas", "label": "Drill 1",
             "capabilities": [{"source": "wifi", "positioningId": "wifi-asset-01"}]},
        ],
    }
    put = await client.put(ASSETS, json=new_map, headers=auth_headers)
    assert put.status_code == 200

    got = await client.get(ASSETS, headers=auth_headers)
    ids = {a["assetId"] for a in got.json()["assets"]}
    assert ids == {"drill-1"}


async def test_details_joins_engine_telemetry(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wittra-tag-01").mock(
        return_value=httpx.Response(200, json={
            "positioningId": "wittra-tag-01",
            "latitude": 45.064,
            "longitude": 7.659,
            "accuracy": 0.85,
            "altitude": 1.2,
            "timestamp": "2026-06-03T12:00:00+00:00",
            "sources": ["wittra"],
            "strategy": "weighted_avg",
        })
    )
    resp = await client.get(f"{ASSETS}/pkg-4471/details", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["assetId"] == "pkg-4471"
    assert body["kind"] == "pallet"
    assert body["telemetry"]["sources"] == ["wittra"]
    assert body["telemetry"]["altitude"] == 1.2


async def test_details_fuses_multi_capability(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings
    get_settings.cache_clear()

    amap = {"version": 4, "assets": [
        {"assetId": "robot-9", "kind": "forklift", "org": "acme",
         "capabilities": [{"source": "wifi", "positioningId": "wifi-9"},
                          {"source": "wittra", "positioningId": "uwb-9"}]}]}
    assert (await client.put("/assets", json=amap, headers=auth_headers)).status_code == 200

    respx_mock.get("http://engine.test/position/wifi-9?source=wifi").mock(
        return_value=httpx.Response(200, json={
            "positioningId": "wifi-9", "latitude": 0.0, "longitude": 0.0, "accuracy": 3.0,
            "timestamp": "2026-01-01T00:00:00+00:00", "sources": ["wifi"]}))
    respx_mock.get("http://engine.test/position/uwb-9?source=wittra").mock(
        return_value=httpx.Response(200, json={
            "positioningId": "uwb-9", "latitude": 1.0, "longitude": 1.0, "accuracy": 0.5,
            "timestamp": "2026-01-01T00:00:05+00:00", "sources": ["wittra"]}))

    resp = await client.get(f"{ASSETS}/robot-9/details", headers=auth_headers)
    assert resp.status_code == 200
    tele = resp.json()["telemetry"]
    assert set(tele["sources"]) == {"wifi", "wittra"}  # fused side-panel shows both
    assert tele["latitude"] > 0.9  # pulled toward the sharp UWB fix


async def test_details_404_for_unknown_asset(client, auth_headers):
    resp = await client.get(f"{ASSETS}/nope-999/details", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "IDENTIFIER_NOT_FOUND"


async def test_details_telemetry_null_when_engine_unreachable(
    client, respx_mock, auth_headers, monkeypatch
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        side_effect=httpx.ConnectError("nope")
    )
    resp = await client.get(f"{ASSETS}/tool-880/details", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["telemetry"] is None


async def test_put_assets_rejects_a_positioning_id_claimed_by_two_assets(client, auth_headers):
    # Reproduces the KELT repro: wittra-tag-shared standalone AND as a
    # capability of puppypi-01. The gateway's stream enrich groups engine
    # broadcasts by positioningId -> asset; a collision means one asset never
    # gets an entry and location-app shows it OFFLINE despite a live source.
    dup_map = {
        "version": 4,
        "assets": [
            {"assetId": "tag-standalone", "kind": "tool", "org": "acme",
             "capabilities": [{"source": "wittra", "positioningId": "wittra-tag-shared"}]},
            {"assetId": "puppypi-01", "kind": "robot", "org": "acme",
             "capabilities": [
                 {"source": "wifi", "positioningId": "puppypi-01"},
                 {"source": "wittra", "positioningId": "wittra-tag-shared"},
             ]},
        ],
    }
    resp = await client.put(ASSETS, json=dup_map, headers=auth_headers)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "DUPLICATE_POSITIONING_ID"
    assert "wittra-tag-shared" in body["message"]
    assert "tag-standalone" in body["message"]
    assert "puppypi-01" in body["message"]

    # The rejected write must not have landed.
    got = await client.get(ASSETS, headers=auth_headers)
    ids = {a["assetId"] for a in got.json()["assets"]}
    assert "puppypi-01" not in ids


async def test_put_assets_allows_the_same_asset_with_distinct_positioning_ids(client, auth_headers):
    # The legitimate multi-capability case (docs/asset-registry.md): one asset,
    # several sources, each with its OWN positioningId. Must not be rejected.
    ok_map = {
        "version": 4,
        "assets": [
            {"assetId": "robot-2", "kind": "robot", "org": "acme",
             "capabilities": [
                 {"source": "wifi", "positioningId": "puppypi-02"},
                 {"source": "wittra", "positioningId": "wittra-tag-09"},
             ]},
        ],
    }
    resp = await client.put(ASSETS, json=ok_map, headers=auth_headers)
    assert resp.status_code == 200


def _adapters_response(*entries):
    return httpx.Response(200, json={"adapters": list(entries)})


def _adapter(name, source, kinds):
    return {"name": name, "state": "live",
            "capabilities": {"source": source, "kinds": kinds}}


@pytest.fixture
def engine(respx_mock, monkeypatch):
    """Point the gateway at a stub engine and return its /adapters route."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()
    return respx_mock.get("http://engine.test/adapters")


def _map_with(source, kind="tool"):
    return {
        "version": 4,
        "assets": [
            {"assetId": "drill-1", "kind": kind, "org": "atlas", "label": "Drill 1",
             "capabilities": [{"source": source, "positioningId": "p-1"}]},
        ],
    }


async def test_put_assets_rejects_a_source_no_adapter_serves(client, auth_headers, engine):
    # The typo case: accepted today and then silent, because nothing answers
    # for that source and no error ever says so.
    engine.mock(return_value=_adapters_response(_adapter("wifi", "wifi", ["tool"])))
    resp = await client.put(ASSETS, json=_map_with("wtira"), headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "UNKNOWN_SOURCE"
    assert "wtira" in resp.json()["message"]
    # The rejected write must not have landed.
    got = await client.get(ASSETS, headers=auth_headers)
    assert "drill-1" not in {a["assetId"] for a in got.json()["assets"]}


async def test_put_assets_rejects_a_kind_no_adapter_advertises(client, auth_headers, engine):
    engine.mock(return_value=_adapters_response(_adapter("wifi", "wifi", ["tool"])))
    resp = await client.put(ASSETS, json=_map_with("wifi", kind="submarine"), headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "UNKNOWN_KIND"


async def test_put_assets_accepts_what_the_live_fabric_advertises(client, auth_headers, engine):
    engine.mock(return_value=_adapters_response(_adapter("wifi", "wifi", ["tool"])))
    resp = await client.put(ASSETS, json=_map_with("wifi"), headers=auth_headers)
    assert resp.status_code == 200


async def test_put_assets_proceeds_when_the_engine_cannot_be_asked(client, auth_headers, engine):
    # A check that cannot run must not block an operator from writing. The
    # engine being down is not evidence that the source is wrong.
    engine.mock(side_effect=httpx.ConnectError("engine down"))
    resp = await client.put(ASSETS, json=_map_with("wittra"), headers=auth_headers)
    assert resp.status_code == 200


async def test_put_assets_keeps_a_source_the_stored_map_already_uses(client, auth_headers, engine):
    # A self-registered adapter that stays down long enough is evicted from the
    # registry. A source the map already carries is not a typo, so it remains
    # writable rather than becoming unwritable during an outage.
    engine.mock(return_value=_adapters_response(_adapter("wifi", "wifi", ["tool", "pallet"])))
    # `wittra` is in the seeded map and no adapter advertises it here.
    seeded = await client.get(ASSETS, headers=auth_headers)
    assert "wittra" in {c["source"] for a in seeded.json()["assets"] for c in a["capabilities"]}
    resp = await client.put(ASSETS, json=_map_with("wittra", kind="pallet"), headers=auth_headers)
    assert resp.status_code == 200
