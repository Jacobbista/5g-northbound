import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.walker import RandomWalker


@pytest.fixture
def app(monkeypatch):
    from app.main import app as _app
    # The devices the tests ask for are declared, as a deployment declares them.
    monkeypatch.setattr(settings, "device_ids", "dev-1,dev-a,dev-b,never-placed")
    # ASGITransport does not trigger lifespan; populate state manually.
    walker = RandomWalker(settings)
    # The room the blueprint would name; no engine runs in the tests.
    walker.room_id = "room-01"
    _app.state.walker = walker
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
