import random
from typing import Optional

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.base import Adapter, Measurement
from app.fusion.registry import get_strategy
from app.models import Floor, FloorPlan, GpsOrigin
from app.services.position_service import PositionService

MOCK_FLOOR = Floor(id=0, label="Test", width_m=20.0, depth_m=30.0, height_m=3.0)
MOCK_FLOOR_PLAN = FloorPlan(
    version=1,
    gps_origin=GpsOrigin(latitude=45.064312, longitude=7.659154),
    floors=[MOCK_FLOOR],
)


class RandomWalkAdapter(Adapter):
    """Deterministic-ish test adapter that wanders inside the floor bounds."""

    def __init__(self, source: str, floor: Floor, accuracy_m: float, confidence: float, step: float = 0.3):
        self._source = source
        self._floor = floor
        self._accuracy_m = accuracy_m
        self._confidence = confidence
        self._step = step
        self._state: dict[str, tuple[float, float, float]] = {}
        self._rng = random.Random(hash(source) & 0xFFFFFFFF)

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        if device_id not in self._state:
            self._state[device_id] = (self._floor.width_m / 2, self._floor.height_m / 2, self._floor.depth_m / 2)
        x, y, z = self._state[device_id]
        x = self._clamp(x + self._rng.uniform(-self._step, self._step), 0, self._floor.width_m)
        y = self._clamp(y + self._rng.uniform(-self._step, self._step), 0, self._floor.height_m)
        z = self._clamp(z + self._rng.uniform(-self._step, self._step), 0, self._floor.depth_m)
        self._state[device_id] = (x, y, z)
        return Measurement(
            source=self._source, accuracy_m=self._accuracy_m, confidence=self._confidence,
            frame="local", x=x, y=y, z=z,
        )


@pytest.fixture
def floor():
    return MOCK_FLOOR


@pytest.fixture
def floor_plan():
    return MOCK_FLOOR_PLAN


@pytest.fixture
def adapters(floor):
    return {
        "fiveg": RandomWalkAdapter("fiveg", floor, accuracy_m=3.0, confidence=0.6),
        "wifi":  RandomWalkAdapter("wifi",  floor, accuracy_m=2.0, confidence=0.7),
        "uwb":   RandomWalkAdapter("uwb",   floor, accuracy_m=0.3, confidence=0.95),
    }


@pytest.fixture
def app(floor_plan, adapters):
    from app.main import app as _app
    # ASGITransport does not trigger lifespan; populate state manually.
    _app.state.floor_plan = floor_plan
    _app.state.adapters = adapters
    _app.state.primary_strategy_name = "weighted_avg"
    _app.state.position_service = PositionService(
        adapters=adapters,
        floor_plan=floor_plan,
        device_map={},
        primary_strategy=get_strategy("weighted_avg"),
        compare_strategies=[],
    )
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
