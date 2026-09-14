"""The tuning surface KELT drives from the dashboard.

A motion model is a choice from the set the image implements. The image
publishes that set on GET /contract and refuses anything outside it on
PUT /bindings, so a value can be tuned live and rolled back without the
operator discovering afterwards that the adapter ignored it.
"""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.kalman import MOTION_MODELS, RandomWalkTracker2D, Tracker2D
from app.models import WifiConfig
from app.wifi import WifiAdapter


@pytest.fixture
def app_with_bindings(cfg, tmp_path, monkeypatch):
    from app.main import app as _app

    path = tmp_path / "wifi-config.json"
    path.write_text(json.dumps({"bindings": []}))
    _app.state.adapter = WifiAdapter(cfg)
    _app.state.wifi_config = cfg
    _app.state.bindings_path = path
    _app.state.calibration = None
    _app.state.reload_wifi_config = None
    return _app


async def _put(app, body: dict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.put("/bindings", content=json.dumps(body))


@pytest.mark.asyncio
async def test_put_bindings_accepts_every_published_motion_model(app_with_bindings):
    for name in MOTION_MODELS:
        r = await _put(app_with_bindings, {"bindings": [], "motion_model": name})
        assert r.status_code == 200, f"{name} refused: {r.text}"
        stored = json.loads(Path(app_with_bindings.state.bindings_path).read_text())
        assert stored["motion_model"] == name


@pytest.mark.asyncio
async def test_put_bindings_refuses_a_motion_model_the_image_does_not_implement(app_with_bindings):
    before = Path(app_with_bindings.state.bindings_path).read_text()
    r = await _put(app_with_bindings, {"bindings": [], "motion_model": "kalman-ish"})
    assert r.status_code == 422
    assert "kalman-ish" in r.json()["detail"]
    # Refused means not written: the operator's previous value still stands.
    assert Path(app_with_bindings.state.bindings_path).read_text() == before


@pytest.mark.asyncio
async def test_put_bindings_refuses_an_unimplemented_algorithm(app_with_bindings):
    r = await _put(app_with_bindings, {"bindings": [], "algorithm": "fingerprinting"})
    assert r.status_code == 422
    assert "fingerprinting" in r.json()["detail"]


def test_reload_rebuilds_the_trackers_when_the_model_changes(cfg):
    """Without this the swap would apply only to devices first seen after it,
    and an operator tuning live would see no change on the device in front
    of them."""
    adapter = WifiAdapter(cfg.model_copy(update={"motion_model": "constant-velocity"}))
    adapter.ingest("dev1", {"AA:AA:AA:AA:AA:01": -50, "BB:BB:BB:BB:BB:01": -65})
    assert isinstance(adapter._trackers["dev1"], Tracker2D)

    adapter.reload(cfg.model_copy(update={"motion_model": "random-walk"}))
    adapter.ingest("dev1", {"AA:AA:AA:AA:AA:01": -50, "BB:BB:BB:BB:BB:01": -65})
    assert isinstance(adapter._trackers["dev1"], RandomWalkTracker2D)


def test_reload_keeps_the_trackers_when_the_filter_is_unchanged(cfg):
    """A calibration apply changes the propagation model, not the filter. It
    must not throw away the smoothing state of every tracked device."""
    adapter = WifiAdapter(cfg)
    adapter.ingest("dev1", {"AA:AA:AA:AA:AA:01": -50, "BB:BB:BB:BB:BB:01": -65})
    tracker = adapter._trackers["dev1"]
    adapter.reload(cfg.model_copy(update={"tx_power": -45.0}))
    assert adapter._trackers["dev1"] is tracker


def test_default_motion_model_does_not_extrapolate():
    """The default is the one that cannot turn measurement noise into motion."""
    assert WifiConfig(room_w=1, room_h=1, routers=[]).motion_model == "random-walk"
