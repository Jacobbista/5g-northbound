import httpx
import pytest


@pytest.fixture
def layout_file(tmp_path, monkeypatch):
    p = tmp_path / "layout.json"
    monkeypatch.setenv("LAYOUT_FILE", str(p))
    from app.config import get_settings

    get_settings.cache_clear()
    yield p
    get_settings.cache_clear()


@pytest.fixture
async def client(layout_file):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
