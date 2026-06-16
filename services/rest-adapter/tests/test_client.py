import base64

import httpx
import pytest
import respx

from app.client import base_url, build_auth_headers, fetch


def test_base_url_default(wittra_schema, monkeypatch):
    monkeypatch.delenv("WITTRA_BASE_URL", raising=False)
    assert base_url(wittra_schema) == "https://api.wittra.se"


def test_base_url_env_override(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra:8080/")
    assert base_url(wittra_schema) == "http://mock-wittra:8080"


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
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")

    expected_url = "http://mock-wittra/v4/organizations/orgA/projects/prj1/data?deviceId=D001&dataType=location"
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
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")

    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/data?deviceId=D001&dataType=location"
    ).mock(return_value=httpx.Response(404))
    assert await fetch(wittra_schema, "D001") is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_non_200_returns_none(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")

    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/data?deviceId=D001&dataType=location"
    ).mock(return_value=httpx.Response(500, text="boom"))
    assert await fetch(wittra_schema, "D001") is None


@pytest.mark.asyncio
async def test_fetch_missing_env_returns_none_without_request(wittra_schema, monkeypatch):
    monkeypatch.delenv("WITTRA_ORG_ID", raising=False)
    monkeypatch.delenv("WITTRA_API_KEY", raising=False)
    monkeypatch.delenv("WITTRA_PROJECT_ID", raising=False)
    # No respx mock - if any HTTP call is attempted httpx will raise.
    assert await fetch(wittra_schema, "D001") is None
