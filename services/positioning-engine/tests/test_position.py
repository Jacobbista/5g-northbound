import pytest

from app.adapters.base import Adapter, Measurement
from app.fusion.registry import get_strategy
from app.models import FloorPlan, GpsOrigin
from app.services.position_service import PositionService


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
    # The test adapters declare no reporting model: the position holds as of
    # its fix time and is never current.
    assert body["establishedAt"] == body["timestamp"]
    assert body["current"] is False


@pytest.mark.asyncio
async def test_position_near_gps_origin(client):
    # device roams a 20x30 m floor anchored at the dev gps_origin
    body = (await client.get("/position/uwb-tag-001")).json()
    assert 59.40 <= body["latitude"] < 59.401
    assert 17.95 <= body["longitude"] < 17.951


@pytest.mark.asyncio
async def test_position_without_georeference_is_unavailable(app, client):
    saved = app.state.floor_plan
    app.state.floor_plan = FloorPlan(width_m=20.0, depth_m=30.0)
    try:
        resp = await client.get("/position/uwb-tag-001")
    finally:
        app.state.floor_plan = saved
    assert resp.status_code == 503


class _Static(Adapter):
    def __init__(self, m: Measurement):
        self._m = m

    async def get_measurement(self, device_id: str):
        return self._m


def _service_for(m: Measurement, floor_plan: FloorPlan) -> PositionService:
    return PositionService(
        adapters={m.source: _Static(m)}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: {"z": True},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("altitude_m, expected", [(31.0, 0.2), (None, None)])
async def test_vertical_accuracy_is_published_only_with_altitude(app, client, altitude_m, expected):
    fp = FloorPlan(gps_origin=GpsOrigin(latitude=59.40, longitude=17.95, altitude_m=altitude_m),
                   width_m=20.0, depth_m=30.0)
    m = Measurement(source="uwb", frame="venue", x=5.0, y=5.0, z=1.5, verticalAccuracy=0.2,
                    accuracy=0.3, confidence=1.0, timestamp=1700000000.0)
    saved = (app.state.floor_plan, app.state.position_service)
    app.state.floor_plan, app.state.position_service = fp, _service_for(m, fp)
    try:
        body = (await client.get("/position/tag")).json()
    finally:
        app.state.floor_plan, app.state.position_service = saved
    assert body.get("verticalAccuracy") == expected


@pytest.mark.asyncio
async def test_wgs84_measurement_without_georeference_is_dropped():
    fp = FloorPlan(width_m=20.0, depth_m=30.0)
    m = Measurement(source="uwb", frame="wgs84", latitude=59.40, longitude=17.95,
                    accuracy=0.3, confidence=1.0, timestamp=1700000000.0)
    assert await _service_for(m, fp).get_position("tag") is None
