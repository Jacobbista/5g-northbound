"""x-correlator: minted/echoed on the response, and propagated to the engine
so the per-hop latency trace joins across services. See
docs/latency-instrumentation.md."""

import json
import logging
from pathlib import Path

import httpx
import jsonschema
import pytest

_HOP_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "schema/hop-log.schema.json").read_text()
)

ROLE = "camara-location-read"
RETRIEVE = "/location-retrieval/v0.5/retrieve"
ASSET = {"assetId": "tool-880"}


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


def _engine_ok():
    return httpx.Response(200, json={
        "device_id": "wifi-asset-01",
        "latitude": 45.064312,
        "longitude": 7.659154,
        "accuracy_m": 1.5,
        "timestamp": "2026-06-03T14:36:17+00:00",
        "sources": ["wifi"],
        "strategy": "weighted_avg",
    })


async def test_correlator_echoed_when_supplied(client, auth_headers):
    resp = await client.post(
        RETRIEVE, json={"device": ASSET}, headers={**auth_headers, "x-correlator": "corr-abc"}
    )
    assert resp.status_code == 200
    assert resp.headers["x-correlator"] == "corr-abc"


async def test_correlator_minted_when_absent(client, auth_headers):
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers.get("x-correlator")  # non-empty minted value


async def test_correlator_propagated_to_engine(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()
    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=_engine_ok()
    )
    resp = await client.post(
        RETRIEVE, json={"device": ASSET}, headers={**auth_headers, "x-correlator": "corr-xyz"}
    )
    assert resp.status_code == 200
    # The gateway must forward the same correlator on its downstream engine call.
    assert route.calls.last.request.headers.get("x-correlator") == "corr-xyz"


async def test_hop_line_matches_schema(client, auth_headers, caplog):
    with caplog.at_level(logging.INFO, logger="hop"):
        await client.post(
            RETRIEVE, json={"device": ASSET}, headers={**auth_headers, "x-correlator": "corr-schema"}
        )
    hops = [json.loads(r.getMessage()) for r in caplog.records if r.name == "hop"]
    assert hops, "no hop line logged"
    for line in hops:
        jsonschema.validate(line, _HOP_SCHEMA)  # emitted line honours the published contract
    assert any(h["correlator"] == "corr-schema" for h in hops)
