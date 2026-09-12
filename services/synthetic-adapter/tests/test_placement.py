"""Placement: a device reports nothing until it is put somewhere.

Only this adapter can offer this. A real source reports where its hardware
actually is; there is nothing to place. This one synthesises the position, so
where it starts is a choice, and the demo hands that choice to the operator.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.walker import WaypointWalker


@pytest.fixture
def spawn_app(monkeypatch):
    """An app whose devices must be placed before they report."""
    from app import routers
    from app.main import app as _app

    cfg = Settings(width_m=13.0, depth_m=32.0, height_m=3.0, spawn_required=True,
                   device_ids="synthetic-demo-01", anchor_ids="synthetic-anchor-01")
    for mod in (routers.measurement, routers.devices, routers.placement):
        monkeypatch.setattr(mod, "settings", cfg)
    _app.state.walker = WaypointWalker(cfg)
    return _app


@pytest.fixture
async def spawn_client(spawn_app):
    async with AsyncClient(transport=ASGITransport(app=spawn_app), base_url="http://test") as c:
        yield c


async def test_an_unplaced_device_reports_no_fix(spawn_client):
    # Not an error: the same "no fix" an adapter reports for a device it cannot
    # currently locate. The engine skips the source for the cycle, and the
    # asset simply has no position.
    r = await spawn_client.get("/measurement/synthetic-demo-01")
    assert r.status_code == 404


async def test_placing_a_device_starts_it_reporting_from_that_point(spawn_client):
    put = await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": 4.0, "z": 9.0})
    assert put.status_code == 200
    assert put.json() == {"id": "synthetic-demo-01", "x": 4.0, "z": 9.0, "placed": True}

    r = await spawn_client.get("/measurement/synthetic-demo-01")
    assert r.status_code == 200
    # The first fix is the drop point, lifted into the engine's frame. Without
    # a blueprint the walker has no frame to mirror about and passes it
    # through, so the drop point is directly readable here.
    assert r.json()["x"] == pytest.approx(4.0, abs=0.5)


async def test_a_drop_outside_the_room_lands_just_inside(spawn_client):
    # A raycast can land slightly off the floor. Seeding the walk somewhere the
    # walk could never reach would strand the device, so the point is clamped
    # into the same inset the walk itself respects.
    put = await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": -50.0, "z": 999.0})
    assert put.status_code == 200
    body = put.json()
    assert 0.0 < body["x"] < 13.0
    assert 0.0 < body["z"] < 32.0


async def test_removing_a_device_stops_it_reporting(spawn_client):
    await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": 4.0, "z": 9.0})
    assert (await spawn_client.get("/measurement/synthetic-demo-01")).status_code == 200

    r = await spawn_client.delete("/devices/synthetic-demo-01/placement")
    assert r.status_code == 200
    assert r.json()["placed"] is False
    assert (await spawn_client.get("/measurement/synthetic-demo-01")).status_code == 404


async def test_removing_a_device_that_is_not_placed_is_not_an_error(spawn_client):
    # The caller wanted it gone and it is gone.
    r = await spawn_client.delete("/devices/synthetic-demo-01/placement")
    assert r.status_code == 200
    assert r.json()["placed"] is False


async def test_placing_twice_moves_the_device(spawn_client):
    await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": 2.0, "z": 2.0})
    second = await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": 9.0, "z": 20.0})
    assert second.json()["x"] == 9.0 and second.json()["z"] == 20.0


async def test_devices_reports_which_are_placed(spawn_client):
    # The listing is how the demo knows what is still draggable and what is
    # already on the floor.
    def _assets(body):
        return {d["id"]: d.get("placed") for d in body["devices"] if d["role"] == "asset"}

    before = _assets((await spawn_client.get("/devices")).json())
    assert before == {"synthetic-demo-01": False}

    await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": 4.0, "z": 9.0})
    after = _assets((await spawn_client.get("/devices")).json())
    assert after == {"synthetic-demo-01": True}


async def test_an_anchor_is_never_placed(spawn_client):
    # Anchors are fixed infrastructure. They are not walked and not placeable,
    # so the flag would be noise on them.
    infra = [d for d in (await spawn_client.get("/devices")).json()["devices"]
             if d["role"] == "infrastructure"]
    assert infra and all("placed" not in d for d in infra)


async def test_without_spawn_required_a_device_still_walks_from_boot(client):
    # The default is unchanged: a deployment that never places anything keeps
    # the behaviour it has today.
    assert (await client.get("/measurement/never-placed")).status_code == 200


async def test_a_freshly_placed_device_reports_the_drop_point_not_a_step_away(spawn_client):
    # The offset this guards: the walker used to start moving on the first poll
    # after placement, so by the time the fix reached a consumer the device was
    # most of a metre from where it was dropped, and the placement read as
    # imprecise.
    await spawn_client.put("/devices/synthetic-demo-01/placement", json={"x": 4.0, "z": 9.0})
    first = (await spawn_client.get("/measurement/synthetic-demo-01")).json()
    second = (await spawn_client.get("/measurement/synthetic-demo-01")).json()
    assert (first["x"], first["z"]) == (second["x"], second["z"])
