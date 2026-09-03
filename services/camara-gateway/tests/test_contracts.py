import pytest


@pytest.mark.asyncio
async def test_contracts_index_lists_the_manifest(client):
    r = await client.get("/contracts")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["contracts"]}
    assert "device-diagnostics.schema.json" in names
    assert "location-retrieval.profiled.yaml" in names
    for c in r.json()["contracts"]:
        assert set(c) == {"name", "path", "media_type", "description"}


@pytest.mark.asyncio
async def test_fetch_vocabulary_registry_from_the_gateway(client):
    r = await client.get("/contracts/device-diagnostics.schema.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert "battery" in body["properties"]["diagnostics"]["properties"]


@pytest.mark.asyncio
async def test_fetch_profiled_spec_is_yaml(client):
    r = await client.get("/contracts/location-retrieval.profiled.yaml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/yaml")


@pytest.mark.asyncio
async def test_unknown_contract_404(client):
    r = await client.get("/contracts/not-a-contract.json")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_contracts_need_no_auth(client):
    # Same posture as GET /contract: no Authorization header required.
    r = await client.get("/contracts")
    assert r.status_code == 200
