import base64

import httpx
import pytest
import respx

from app.client import base_url, build_auth_headers, fetch


def test_base_url_comes_from_the_environment(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor:8080/")
    assert base_url(wittra_schema) == "http://mock-vendor:8080"


def test_base_url_is_none_when_the_operator_has_not_set_it(wittra_schema, monkeypatch):
    # No fallback: the document names the variable, the operator supplies the
    # value, and an unset variable is a misconfiguration the callers map to 503.
    monkeypatch.delenv("WITTRA_BASE_URL", raising=False)
    assert base_url(wittra_schema) is None


def test_basic_auth_header(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k3y")
    headers = build_auth_headers(wittra_schema)
    expected = base64.b64encode(b"orgA:k3y").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


def test_basic_auth_missing_env_returns_none(wittra_schema, monkeypatch):
    monkeypatch.delenv("WITTRA_ORG_ID", raising=False)
    monkeypatch.delenv("WITTRA_API_KEY", raising=False)
    assert build_auth_headers(wittra_schema) is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_substitutes_path_vars_and_returns_json(wittra_schema, monkeypatch, wittra_sample_payload):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")

    expected_url = "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    route = respx.get(expected_url).mock(return_value=httpx.Response(200, json=wittra_sample_payload))

    result = await fetch(wittra_schema, "D001")
    assert route.called
    assert result == wittra_sample_payload


@pytest.mark.asyncio
@respx.mock
async def test_fetch_404_returns_none(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")

    respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(404))
    assert await fetch(wittra_schema, "D001") is None


@pytest.mark.asyncio
@respx.mock
async def test_a_vendor_error_is_not_a_missing_fix(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")

    respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(500, text="boom"))
    from app.client import VendorError

    with pytest.raises(VendorError):
        await fetch(wittra_schema, "D001")


@pytest.mark.asyncio
async def test_fetch_missing_env_is_unavailable_without_request(wittra_schema, monkeypatch):
    monkeypatch.delenv("WITTRA_ORG_ID", raising=False)
    monkeypatch.delenv("WITTRA_API_KEY", raising=False)
    monkeypatch.delenv("WITTRA_PROJECT_ID", raising=False)
    # No respx mock - if any HTTP call is attempted httpx will raise.
    from app.client import VendorUnavailable

    with pytest.raises(VendorUnavailable):
        await fetch(wittra_schema, "D001")


async def test_the_trace_records_a_new_connection_and_the_vendors_time():
    from app.client import _tracer

    record: dict = {}
    trace = _tracer(record)
    for name in ("connection.connect_tcp.started", "connection.connect_tcp.complete",
                 "http11.send_request_headers.started", "http11.receive_response_headers.complete"):
        await trace(name, {})
    assert record["connection"] == "new" and record["upstream_ms"] >= 0


async def test_the_trace_records_a_reused_connection():
    from app.client import _tracer

    record: dict = {}
    trace = _tracer(record)
    await trace("http11.send_request_headers.started", {})
    await trace("http11.receive_response_headers.complete", {})
    assert record["connection"] == "reused"



@pytest.mark.asyncio
@respx.mock
async def test_a_vendor_slower_than_its_budget_is_a_timeout(wittra_schema, monkeypatch):
    """The whole call is bounded, so the adapter answers before the engine's
    budget, which is the requestTimeout plus the adapter's own time."""
    import asyncio

    from app.client import VendorTimeout

    for var, val in (("WITTRA_ORG_ID", "orgA"), ("WITTRA_API_KEY", "k"),
                     ("WITTRA_PROJECT_ID", "prj1"), ("WITTRA_BASE_URL", "http://mock-vendor")):
        monkeypatch.setenv(var, val)

    async def slow(request):
        await asyncio.sleep(1.0)
        return httpx.Response(200, json={})

    respx.get("http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001").mock(side_effect=slow)
    quick = wittra_schema.model_copy(update={"requestTimeout": 0.1})
    with pytest.raises(VendorTimeout):
        await fetch(quick, "D001")
