import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.http import HttpAdapter
from app.main import app as _app


@pytest.fixture
def client_with_http_adapters():
    fake_now = [100.0]

    def clock():
        return fake_now[0]

    healthy = HttpAdapter("wifi", "http://wifi-positioning:8080", clock=clock)
    degraded = HttpAdapter("wittra", "http://wittra:8080", clock=clock)
    # Force degraded into a cooldown state without making any HTTP calls.
    degraded._fail_count = 5
    degraded._cooldown_until = fake_now[0] + 10.0

    _app.state.adapters = {"wifi": healthy, "wittra": degraded}
    return healthy, degraded, fake_now


@pytest.mark.asyncio
async def test_adapters_endpoint_lists_configured_adapters(client_with_http_adapters):
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        r = await c.get("/adapters")
    assert r.status_code == 200
    names = sorted(a["name"] for a in r.json()["adapters"])
    assert names == ["wifi", "wittra"]


@pytest.mark.asyncio
async def test_adapters_endpoint_reports_cooldown_state(client_with_http_adapters):
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        r = await c.get("/adapters")
    by_name = {a["name"]: a for a in r.json()["adapters"]}
    assert by_name["wifi"]["in_cooldown"] is False
    assert by_name["wifi"]["fail_count"] == 0
    assert by_name["wittra"]["in_cooldown"] is True
    assert by_name["wittra"]["fail_count"] == 5
    assert by_name["wittra"]["cooldown_seconds_remaining"] == pytest.approx(10.0, abs=0.05)


@pytest.mark.asyncio
async def test_adapters_endpoint_exposes_base_url(client_with_http_adapters):
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        r = await c.get("/adapters")
    urls = {a["name"]: a["base_url"] for a in r.json()["adapters"]}
    assert urls["wifi"] == "http://wifi-positioning:8080"
    assert urls["wittra"] == "http://wittra:8080"
