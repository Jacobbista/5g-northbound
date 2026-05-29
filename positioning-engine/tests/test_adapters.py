import math

import pytest

from app.adapters.mock_fiveg import FiveGAdapter
from app.adapters.mock_uwb import UwbAdapter
from app.adapters.mock_wifi import WifiAdapter
from app.models import Floor

FLOOR = Floor(id=0, label="T", width_m=20.0, depth_m=30.0, height_m=3.0)


@pytest.mark.asyncio
async def test_fiveg_adapter_source():
    m = await FiveGAdapter(FLOOR).get_measurement("dev-1")
    assert m is not None
    assert m.source == "fiveg"


@pytest.mark.asyncio
async def test_wifi_adapter_source():
    m = await WifiAdapter(FLOOR).get_measurement("dev-1")
    assert m is not None
    assert m.source == "wifi"


@pytest.mark.asyncio
async def test_uwb_adapter_source():
    m = await UwbAdapter(FLOOR).get_measurement("dev-1")
    assert m is not None
    assert m.source == "uwb"


@pytest.mark.asyncio
async def test_random_walk_bounded():
    adapter = UwbAdapter(FLOOR)
    m1 = await adapter.get_measurement("dev-1")
    m2 = await adapter.get_measurement("dev-1")
    dist = math.sqrt((m2.x - m1.x) ** 2 + (m2.y - m1.y) ** 2 + (m2.z - m1.z) ** 2)
    # max step per axis is 0.3, so 3D diagonal <= 0.3 * sqrt(3) ≈ 0.52
    assert dist <= 0.3 * math.sqrt(3) + 1e-9
