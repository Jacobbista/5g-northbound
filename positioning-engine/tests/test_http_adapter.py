import pytest
import respx
from httpx import Response

from app.adapters.http import HttpAdapter


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_decodes_measurement():
    respx.get("http://wifi-positioning:8080/measurement/dev1").mock(
        return_value=Response(200, json={
            "source": "wifi", "x": 5.0, "y": 0.0, "z": 12.3,
            "accuracy_m": 1.5, "confidence": 0.7, "timestamp": 1700000000.0,
        })
    )
    a = HttpAdapter("http://wifi-positioning:8080")
    m = await a.get_measurement("dev1")
    await a.aclose()
    assert m is not None
    assert m.source == "wifi"
    assert m.x == 5.0 and m.z == 12.3
    assert m.accuracy_m == 1.5
    assert m.timestamp == 1700000000.0


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_404_returns_none():
    respx.get("http://x/measurement/nope").mock(return_value=Response(404))
    a = HttpAdapter("http://x")
    assert await a.get_measurement("nope") is None
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_network_error_returns_none():
    import httpx as _httpx
    respx.get("http://down/measurement/dev").mock(side_effect=_httpx.ConnectError("down"))
    a = HttpAdapter("http://down")
    # exception path inside the adapter -> None, never raises
    assert await a.get_measurement("dev") is None
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_trailing_slash_normalised():
    respx.get("http://x/measurement/dev").mock(
        return_value=Response(200, json={"source": "wifi", "x": 1, "y": 0, "z": 2,
                                          "accuracy_m": 1, "confidence": 0.5})
    )
    a = HttpAdapter("http://x/")
    m = await a.get_measurement("dev")
    await a.aclose()
    assert m is not None and m.x == 1.0
