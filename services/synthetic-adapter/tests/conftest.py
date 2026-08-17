import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.walker import RandomWalker


@pytest.fixture
def app():
    from app.main import app as _app
    # ASGITransport does not trigger lifespan; populate state manually.
    _app.state.walker = RandomWalker(settings)
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
