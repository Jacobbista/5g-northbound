import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app as _app
from app.registry import SEED, AdapterRegistry


@pytest.fixture
def registry(tmp_path):
    fake_now = [100.0]

    def clock():
        return fake_now[0]

    reg = AdapterRegistry(
        ttl_s=45.0, heartbeat_s=15.0,
        persist_path=str(tmp_path / "adapters.json"), clock=clock,
    )
    # Two seed adapters; force one into cooldown without any HTTP.
    reg.upsert("wifi", "http://wifi-adapter:8080", "adapter", SEED)
    reg.upsert("wittra", "http://wittra:8080", "adapter", SEED)
    degraded = reg.adapters["wittra"]
    degraded._fail_count = 5
    # HttpAdapter uses its own (real monotonic) clock for cooldown; force it
    # relative to that clock so in_cooldown is True independent of the
    # registry's fake clock.
    degraded._cooldown_until = degraded._clock() + 10.0
    _app.state.registry = reg
    return reg, fake_now


async def _get(path):
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        return await c.get(path)


async def test_adapters_endpoint_lists_registered(registry):
    r = await _get("/adapters")
    assert r.status_code == 200
    names = sorted(a["name"] for a in r.json()["adapters"])
    assert names == ["wifi", "wittra"]


async def test_cooldown_surfaces_as_unreachable(registry):
    r = await _get("/adapters")
    by = {a["name"]: a for a in r.json()["adapters"]}
    assert by["wifi"]["state"] == "live"
    assert by["wifi"]["inCooldown"] is False
    # heartbeat fresh (seed, never ages) but polls fail -> unreachable, not stale
    assert by["wittra"]["state"] == "unreachable"
    assert by["wittra"]["inCooldown"] is True
    assert by["wittra"]["failCount"] == 5


async def test_exposes_base_url_kind_provenance(registry):
    r = await _get("/adapters")
    by = {a["name"]: a for a in r.json()["adapters"]}
    assert by["wifi"]["baseUrl"] == "http://wifi-adapter:8080"
    assert by["wifi"]["registeredVia"] == "seed"
    assert "lastSeenSAgo" in by["wifi"]


async def test_self_entry_goes_stale_then_evicts(tmp_path):
    fake_now = [0.0]
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0,
                          persist_path=str(tmp_path / "a.json"), clock=lambda: fake_now[0])
    reg.upsert("mock", "http://mock:8080", "adapter", "self")
    _app.state.registry = reg
    # fresh
    assert reg.status_list()[0]["state"] == "live"
    # past one heartbeat interval but within TTL -> stale
    fake_now[0] = 20.0
    assert reg.status_list()[0]["state"] == "stale"
    # past TTL -> evicted
    fake_now[0] = 50.0
    orphans = reg.evict_expired()
    assert len(orphans) == 1
    assert reg.is_empty()


async def test_seed_entry_never_evicted(tmp_path):
    fake_now = [0.0]
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0,
                          persist_path=str(tmp_path / "a.json"), clock=lambda: fake_now[0])
    reg.upsert("wifi", "http://wifi:8080", "adapter", SEED)
    fake_now[0] = 10_000.0  # long past TTL
    assert reg.evict_expired() == []
    assert not reg.is_empty()
    # seed with no cooldown stays live regardless of age (no heartbeat expected)
    assert reg.status_list()[0]["state"] == "live"


async def test_post_register_and_delete_roundtrip(tmp_path):
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    _app.state.registry = reg
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        post = await c.post("/adapters", json={"name": "edge-wifi", "baseUrl": "http://edge:8080", "kind": "adapter"})
        assert post.status_code == 200
        assert "edge-wifi" in reg.adapters
        # self entry not persisted
        import json as _json
        from pathlib import Path
        persisted = _json.loads(Path(tmp_path / "a.json").read_text())
        assert persisted == []
        dele = await c.delete("/adapters/edge-wifi")
        assert dele.status_code == 200
        assert "edge-wifi" not in reg.adapters


async def test_persist_restore_only_seed_manual(tmp_path):
    path = str(tmp_path / "a.json")
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=path)
    reg.upsert("wifi", "http://wifi:8080", "adapter", SEED)
    reg.upsert("edge", "http://edge:8080", "adapter", "self")
    reg.persist()
    reg2 = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=path)
    reg2.load_persisted()
    assert set(reg2.adapters) == {"wifi"}  # self not persisted


@pytest.mark.parametrize("capabilities, status", [
    ({"z": True, "nominalVerticalAccuracy": 0.8}, 200),
    ({"z": False, "nominalVerticalAccuracy": 0.8}, 422),   # an error of a height it does not measure
    ({"z": True, "nominalVerticalAccuracy": 0}, 422),
])
async def test_nominal_vertical_accuracy_is_declared_only_with_height(tmp_path, capabilities, status):
    _app.state.registry = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        r = await c.post("/adapters", json={"name": "uwb", "baseUrl": "http://uwb:8080",
                                            "capabilities": capabilities})
    assert r.status_code == status


async def test_a_stopping_instance_does_not_deregister_its_replacement(tmp_path):
    """Rolling update: the new pod registers, then the old one stops and
    deregisters. The adapter stays registered."""
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    _app.state.registry = reg
    announce = {"name": "wittra", "baseUrl": "http://wittra:8080", "kind": "vendor"}
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        await c.post("/adapters", json={**announce, "instance": "old"})
        await c.post("/adapters", json={**announce, "instance": "new"})
        gone = await c.delete("/adapters/wittra", params={"instance": "old"})
        assert gone.json() == {"status": "ok", "name": "wittra", "registered": True}
        assert "wittra" in reg.adapters
        last = await c.delete("/adapters/wittra", params={"instance": "new"})
        assert last.json() == {"status": "ok", "name": "wittra", "registered": False}
    assert "wittra" not in reg.adapters


async def test_an_unknown_instance_removes_nothing(tmp_path):
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("synthetic", "http://synthetic:8080", "synthetic", "self", instance="a")
    assert reg.remove("synthetic", "b") == (False, None)
    assert "synthetic" in reg.adapters


async def test_an_instance_that_stopped_silently_ages_out_alone(tmp_path):
    """A replica that crashed without deregistering does not keep the entry
    alive, and the live replica's deregistration is final."""
    fake_now = [0.0]
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0,
                          persist_path=str(tmp_path / "a.json"), clock=lambda: fake_now[0])
    reg.upsert("wifi", "http://wifi:8080", "wifi", "self", instance="crashed")
    fake_now[0] = 30.0
    reg.upsert("wifi", "http://wifi:8080", "wifi", "self", instance="live")
    fake_now[0] = 60.0
    assert reg.evict_expired() == []
    assert reg.status_list()[0]["instances"] == 1
    removed, orphan = reg.remove("wifi", "live")
    assert removed and orphan is not None
    assert reg.is_empty()


async def test_an_older_adapter_without_an_instance_does_not_deregister_its_replacement(tmp_path):
    """The first rollout onto adapters that announce an instance: the old pod
    deregisters without one, after the new pod registered with one."""
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("wittra", "http://wittra:8080", "vendor", "self")
    reg.upsert("wittra", "http://wittra:8080", "vendor", "self", instance="new")
    assert reg.remove("wittra") == (False, None)
    assert "wittra" in reg.adapters


async def test_a_new_endpoint_keeps_the_instances_of_the_adapter(tmp_path):
    """Instances announcing different addresses for one adapter: the entry
    follows the latest address, and an instance leaving keeps the others."""
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("wifi", "http://10.0.0.1:8080", "wifi", "self", instance="old")
    reg.upsert("wifi", "http://10.0.0.2:8080", "wifi", "self", instance="new")
    reg.upsert("wifi", "http://10.0.0.1:8080", "wifi", "self", instance="old")
    removed, orphan = reg.remove("wifi", "old")
    assert removed and orphan is None
    assert "wifi" in reg.adapters


async def test_an_anonymous_deregistration_of_a_live_adapter_reports_it_kept(tmp_path):
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("wifi", "http://wifi:8080", "wifi", "self", instance="live")
    _app.state.registry = reg
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        r = await c.delete("/adapters/wifi")
    assert r.json() == {"status": "kept", "name": "wifi", "registered": True}


async def test_the_engine_waits_as_long_as_the_adapter_declares(tmp_path, monkeypatch):
    monkeypatch.delenv("ADAPTER_WITTRA_TIMEOUT", raising=False)
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("wittra", "http://wittra:8080", "vendor", "self", {"responseTimeout": 3.0}, instance="a")
    assert reg.adapters["wittra"].timeout == 3.0
    reg.upsert("wittra", "http://wittra:8080", "vendor", "self", {"responseTimeout": 2.0}, instance="a")
    assert reg.adapters["wittra"].timeout == 2.0
