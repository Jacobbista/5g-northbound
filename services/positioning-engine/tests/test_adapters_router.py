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
    reg.upsert("wifi", "http://wifi-positioning:8080", "adapter", SEED)
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
    assert by["wifi"]["in_cooldown"] is False
    # heartbeat fresh (seed, never ages) but polls fail -> unreachable, not stale
    assert by["wittra"]["state"] == "unreachable"
    assert by["wittra"]["in_cooldown"] is True
    assert by["wittra"]["fail_count"] == 5


async def test_exposes_base_url_kind_provenance(registry):
    r = await _get("/adapters")
    by = {a["name"]: a for a in r.json()["adapters"]}
    assert by["wifi"]["base_url"] == "http://wifi-positioning:8080"
    assert by["wifi"]["registered_via"] == "seed"
    assert "last_seen_s_ago" in by["wifi"]


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
        post = await c.post("/adapters", json={"name": "edge-wifi", "base_url": "http://edge:8080", "kind": "adapter"})
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
