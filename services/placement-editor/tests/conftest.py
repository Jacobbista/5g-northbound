import httpx
import pytest


@pytest.fixture
def engine_url(monkeypatch):
    """Point the editor at a fake engine and reset the settings cache."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine:8080")
    from app.config import get_settings

    get_settings.cache_clear()
    yield "http://engine:8080"
    get_settings.cache_clear()


@pytest.fixture
async def client(engine_url):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
