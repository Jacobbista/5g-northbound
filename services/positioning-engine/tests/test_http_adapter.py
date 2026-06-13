import pytest
import respx
from httpx import Response

from app.adapters.http import HttpAdapter


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_decodes_local_measurement():
    respx.get("http://wifi-positioning:8080/measurement/dev1").mock(
        return_value=Response(200, json={
            "source": "wifi", "x": 5.0, "y": 0.0, "z": 12.3,
            "accuracy_m": 1.5, "confidence": 0.7, "timestamp": 1700000000.0,
        })
    )
    a = HttpAdapter("wifi", "http://wifi-positioning:8080")
    m = await a.get_measurement("dev1")
    await a.aclose()
    assert m is not None
    assert m.source == "wifi"
    assert m.frame == "local"
    assert m.x == 5.0 and m.z == 12.3
    assert m.accuracy_m == 1.5
    assert m.timestamp == 1700000000.0


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_decodes_wgs84_measurement():
    respx.get("http://wittra/measurement/dev1").mock(
        return_value=Response(200, json={
            "source": "wittra", "frame": "wgs84",
            "latitude": 45.064412, "longitude": 7.659254,
            "accuracy_m": 0.3, "confidence": 0.95,
        })
    )
    a = HttpAdapter("wittra", "http://wittra")
    m = await a.get_measurement("dev1")
    await a.aclose()
    assert m is not None
    assert m.frame == "wgs84"
    assert m.latitude == 45.064412
    assert m.longitude == 7.659254


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_uses_adapter_name_when_source_missing():
    respx.get("http://x/measurement/d").mock(
        return_value=Response(200, json={"x": 1, "y": 0, "z": 2, "accuracy_m": 1, "confidence": 0.5})
    )
    a = HttpAdapter("custom-name", "http://x")
    m = await a.get_measurement("d")
    await a.aclose()
    assert m is not None and m.source == "custom-name"


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_404_returns_none():
    respx.get("http://x/measurement/nope").mock(return_value=Response(404))
    a = HttpAdapter("x", "http://x")
    assert await a.get_measurement("nope") is None
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_network_error_returns_none():
    import httpx as _httpx
    respx.get("http://down/measurement/dev").mock(side_effect=_httpx.ConnectError("down"))
    a = HttpAdapter("down", "http://down")
    assert await a.get_measurement("dev") is None
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_sends_configured_headers():
    route = respx.get("http://wittra/measurement/dev1").mock(
        return_value=Response(200, json={
            "source": "wittra", "x": 1.0, "y": 0, "z": 2.0,
            "accuracy_m": 0.3, "confidence": 0.95,
        })
    )
    a = HttpAdapter("wittra", "http://wittra", headers={"X-API-Key": "secret-token"})
    m = await a.get_measurement("dev1")
    await a.aclose()
    assert m is not None
    assert route.called
    assert route.calls.last.request.headers["X-API-Key"] == "secret-token"


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_cooldown_after_consecutive_failures():
    """Three consecutive network errors -> cooldown skips further HTTP calls."""
    import httpx as _httpx

    fake_now = [0.0]

    def clock():
        return fake_now[0]

    route = respx.get("http://flaky/measurement/dev").mock(
        side_effect=_httpx.ConnectError("down")
    )
    a = HttpAdapter("flaky", "http://flaky", clock=clock)

    # 3 failures trip the cooldown.
    for _ in range(3):
        assert await a.get_measurement("dev") is None
    assert a.fail_count == 3
    calls_after_trip = route.call_count

    # Next call within the cooldown window must not hit the network.
    fake_now[0] += 0.5
    assert await a.get_measurement("dev") is None
    assert route.call_count == calls_after_trip

    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_cooldown_expires_then_retries():
    import httpx as _httpx

    fake_now = [0.0]

    def clock():
        return fake_now[0]

    route = respx.get("http://flaky/measurement/dev").mock(
        side_effect=_httpx.ConnectError("down")
    )
    a = HttpAdapter("flaky", "http://flaky", clock=clock)

    for _ in range(3):
        await a.get_measurement("dev")
    calls = route.call_count

    # Jump past the cooldown window (>2s).
    fake_now[0] += 5.0
    await a.get_measurement("dev")
    assert route.call_count == calls + 1
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_success_resets_failure_counter():
    import httpx as _httpx

    respx.get("http://x/measurement/dev").mock(
        side_effect=[
            _httpx.ConnectError("down"),
            _httpx.ConnectError("down"),
            Response(200, json={
                "source": "x", "x": 1, "y": 0, "z": 2,
                "accuracy_m": 1, "confidence": 0.5,
            }),
        ]
    )
    a = HttpAdapter("x", "http://x")
    await a.get_measurement("dev")
    await a.get_measurement("dev")
    assert a.fail_count == 2
    m = await a.get_measurement("dev")
    assert m is not None
    assert a.fail_count == 0
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_404_does_not_trip_cooldown():
    respx.get("http://x/measurement/dev").mock(return_value=Response(404))
    a = HttpAdapter("x", "http://x")
    for _ in range(5):
        await a.get_measurement("dev")
    assert a.fail_count == 0
    await a.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_5xx_counts_as_failure():
    respx.get("http://x/measurement/dev").mock(return_value=Response(503))
    a = HttpAdapter("x", "http://x")
    for _ in range(3):
        await a.get_measurement("dev")
    assert a.fail_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_4xx_other_than_404_does_not_trip_cooldown():
    # 401/403 from a misconfigured API key would otherwise spam retries; the
    # adapter should not enter cooldown but also should not increment the
    # failure counter (the operator needs to fix credentials, not back off).
    respx.get("http://x/measurement/dev").mock(return_value=Response(401))
    a = HttpAdapter("x", "http://x")
    for _ in range(5):
        await a.get_measurement("dev")
    assert a.fail_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_malformed_body_counts_as_failure():
    respx.get("http://x/measurement/dev").mock(
        return_value=Response(200, json={"source": "x"})  # missing accuracy_m, confidence
    )
    a = HttpAdapter("x", "http://x")
    m = await a.get_measurement("dev")
    assert m is None
    assert a.fail_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_http_adapter_trailing_slash_normalised():
    respx.get("http://x/measurement/dev").mock(
        return_value=Response(200, json={"source": "wifi", "x": 1, "y": 0, "z": 2,
                                          "accuracy_m": 1, "confidence": 0.5})
    )
    a = HttpAdapter("wifi", "http://x/")
    m = await a.get_measurement("dev")
    await a.aclose()
    assert m is not None and m.x == 1.0
