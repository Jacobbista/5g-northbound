import httpx
import respx
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def _get(path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(path)


@respx.mock
async def test_blueprint_proxied_from_engine(monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine:8080")
    monkeypatch.setenv("SKIP_AUTH", "true")
    get_settings.cache_clear()
    body = {"floor_plans": [{"georef": {"latitude": 59.4, "longitude": 17.9}}], "rooms": []}
    respx.get("http://engine:8080/blueprint").mock(return_value=httpx.Response(200, json=body))
    r = await _get("/blueprint")
    assert r.status_code == 200
    assert r.json()["floor_plans"][0]["georef"]["latitude"] == 59.4
    get_settings.cache_clear()


@respx.mock
async def test_blueprint_404_when_engine_has_none(monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine:8080")
    monkeypatch.setenv("SKIP_AUTH", "true")
    get_settings.cache_clear()
    respx.get("http://engine:8080/blueprint").mock(return_value=httpx.Response(404))
    r = await _get("/blueprint")
    assert r.status_code == 404
    get_settings.cache_clear()
