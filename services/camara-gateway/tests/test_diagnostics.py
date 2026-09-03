import httpx
import pytest

ROLE = "camara-location-read"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


def _mock_engine_and_source(respx_mock):
    respx_mock.get("http://engine.test/adapters").mock(
        return_value=httpx.Response(200, json={"adapters": [
            {"name": "wittra", "base_url": "http://wittra-adapter:8080",
             "fail_count": 0, "in_cooldown": False, "cooldown_seconds_remaining": 0.0},
        ]})
    )
    respx_mock.get("http://wittra-adapter:8080/diagnostics/wittra-tag-01").mock(
        return_value=httpx.Response(200, json={
            "device_id": "wittra-tag-01",
            "diagnostics": {"accuracy_value": 0.9, "accuracy_kind": "vendor-radius", "motion": "MOVING"},
        })
    )


@pytest.mark.asyncio
async def test_device_diagnostics_resolves_and_proxies(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings
    get_settings.cache_clear()
    _mock_engine_and_source(respx_mock)

    r = await client.get("/device-diagnostics/v0/pkg-4471", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["assetId"] == "pkg-4471"
    assert body["source"] == "wittra"
    assert body["diagnostics"]["accuracy_kind"] == "vendor-radius"


@pytest.mark.asyncio
async def test_device_diagnostics_404_when_asset_unknown(client, auth_headers):
    r = await client.get("/device-diagnostics/v0/nope-999", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_device_diagnostics_requires_auth(client):
    r = await client.get("/device-diagnostics/v0/pkg-4471")
    assert r.status_code == 401


def test_diagnostics_payload_matches_contract(respx_mock):
    import json, pathlib, jsonschema
    schema = json.loads(pathlib.Path(__file__).resolve().parents[3]
                        .joinpath("schema/device-diagnostics.schema.json").read_text())
    body = {"assetId": "pkg-4471", "source": "wittra",
            "diagnostics": {"accuracy_value": 0.9, "accuracy_kind": "vendor-radius", "motion": "MOVING"}}
    jsonschema.validate(body, schema)


def test_core_vocabulary_and_x_vendor_validate():
    import json, pathlib, jsonschema
    schema = json.loads(pathlib.Path(__file__).resolve().parents[3]
                        .joinpath("schema/device-diagnostics.schema.json").read_text())
    body = {"assetId": "a", "source": "wittra",
            "diagnostics": {"battery": 84, "last_seen": 1700000000, "moving": True,
                            "x_vendor": {"temperature": 22.5}}}
    jsonschema.validate(body, schema)


def test_battery_out_of_range_rejected():
    import json, pathlib, jsonschema, pytest
    schema = json.loads(pathlib.Path(__file__).resolve().parents[3]
                        .joinpath("schema/device-diagnostics.schema.json").read_text())
    body = {"assetId": "a", "source": "wittra", "diagnostics": {"battery": 140}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(body, schema)
