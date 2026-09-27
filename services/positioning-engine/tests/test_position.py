import pytest

from app.models import FloorPlan


@pytest.mark.asyncio
async def test_position_contract_shape(client):
    resp = await client.get("/position/uwb-tag-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["positioningId"] == "uwb-tag-001"
    assert isinstance(body["latitude"], float)
    assert isinstance(body["longitude"], float)
    assert isinstance(body["accuracy"], float)
    assert body["accuracy"] > 0
    assert isinstance(body["sources"], list)
    assert len(body["sources"]) > 0
    # no local x/y/z leaks across the northbound boundary
    assert "x" not in body and "z" not in body


@pytest.mark.asyncio
async def test_position_near_gps_origin(client):
    # device roams a 20x30 m floor anchored at the dev gps_origin
    body = (await client.get("/position/uwb-tag-001")).json()
    assert 59.40 <= body["latitude"] < 59.401
    assert 17.95 <= body["longitude"] < 17.951


@pytest.mark.asyncio
async def test_position_degrades_without_gps_origin(app, client):
    app.state.floor_plan = FloorPlan(
        width_m=20.0, depth_m=30.0
    )
    body = (await client.get("/position/uwb-tag-001")).json()
    assert body["latitude"] == 0.0
    assert body["longitude"] == 0.0
