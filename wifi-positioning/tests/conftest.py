import pytest

from app.models import WifiConfig
from app.wifi import WifiAdapter


@pytest.fixture
def cfg():
    return WifiConfig(
        room_w=13,
        room_h=32,
        routers=[
            {"id": "A", "x": 3.5, "y": 13, "bssids": ["AA:AA:AA:AA:AA:01"]},
            {"id": "B", "x": 11.5, "y": 31, "bssids": ["BB:BB:BB:BB:BB:01"]},
        ],
    )


@pytest.fixture
def cfg3():
    return WifiConfig(
        room_w=20,
        room_h=20,
        algorithm="trilateration",
        routers=[
            {"id": "A", "x": 0, "y": 0, "bssids": ["AA:AA:AA:AA:AA:01"]},
            {"id": "B", "x": 20, "y": 0, "bssids": ["BB:BB:BB:BB:BB:01"]},
            {"id": "C", "x": 0, "y": 20, "bssids": ["CC:CC:CC:CC:CC:01"]},
        ],
    )


@pytest.fixture
def app_with_adapter(cfg):
    from app.main import app as _app

    _app.state.adapter = WifiAdapter(cfg)
    _app.state.wifi_config = cfg
    return _app
