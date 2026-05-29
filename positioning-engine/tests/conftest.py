import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.mock_fiveg import FiveGAdapter
from app.adapters.mock_uwb import UwbAdapter
from app.adapters.mock_wifi import WifiAdapter
from app.models import Floor, FloorPlan, GpsOrigin

MOCK_FLOOR = Floor(id=0, label="Test", width_m=20.0, depth_m=30.0, height_m=3.0)
MOCK_FLOOR_PLAN = FloorPlan(
    version=1,
    gps_origin=GpsOrigin(latitude=45.064312, longitude=7.659154),
    floors=[MOCK_FLOOR],
)


@pytest.fixture
def floor():
    return MOCK_FLOOR


@pytest.fixture
def floor_plan():
    return MOCK_FLOOR_PLAN


@pytest.fixture
def app(floor_plan):
    from app.main import app as _app
    # Populate state directly — ASGITransport does not trigger lifespan
    _app.state.floor_plan = floor_plan
    _app.state.adapters = [
        FiveGAdapter(floor_plan.floors[0]),
        WifiAdapter(floor_plan.floors[0]),
        UwbAdapter(floor_plan.floors[0]),
    ]
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
