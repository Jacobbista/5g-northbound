import pytest

from app.models import Floor, FloorPlan


@pytest.mark.asyncio
async def test_position_contract_shape(client):
    resp = await client.get("/position/uwb-tag-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["device_id"] == "uwb-tag-001"
    assert isinstance(body["latitude"], float)
    assert isinstance(body["longitude"], float)
    assert isinstance(body["accuracy_m"], float)
    assert body["accuracy_m"] > 0
    assert isinstance(body["sources"], list)
    assert len(body["sources"]) > 0
    # no local x/y/z leaks across the northbound boundary
    assert "x" not in body and "z" not in body


@pytest.mark.asyncio
async def test_position_near_gps_origin(client):
    # device roams a 20x30 m floor anchored at the dev gps_origin
    body = (await client.get("/position/uwb-tag-001")).json()
    assert 45.064 < body["latitude"] < 45.065
    assert 7.659 < body["longitude"] < 7.660


@pytest.mark.asyncio
async def test_position_degrades_without_gps_origin(app, client):
    app.state.floor_plan = FloorPlan(
        version=1, floors=[Floor(id=0, label="x", width_m=20.0, depth_m=30.0, height_m=3.0)]
    )
    body = (await client.get("/position/uwb-tag-001")).json()
    assert body["latitude"] == 0.0
    assert body["longitude"] == 0.0
