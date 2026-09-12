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


@pytest.mark.asyncio
async def test_every_manifest_entry_resolves_to_a_served_file(client):
    # The manifest is hand-maintained: a wrong `path` would only surface as a
    # 404 in the cluster. Fetch every entry the index advertises.
    index = (await client.get("/contracts")).json()["contracts"]
    for entry in index:
        r = await client.get(f"/contracts/{entry['name']}")
        assert r.status_code == 200, f"{entry['name']} advertised but not served"


@pytest.mark.asyncio
async def test_accuracy_class_vocabulary_defines_the_declared_bands(client):
    r = await client.get("/contracts/accuracy-class-vocabulary.json")
    assert r.status_code == 200
    body = r.json()
    assert body["unit"] == "m"
    classes = body["classes"]
    assert set(classes) == {"sub-metre", "metre", "coarse"}
    # The bands tile the range without a gap or an overlap.
    assert classes["sub-metre"]["upperBound"] == classes["metre"]["lowerBound"]
    assert classes["metre"]["upperBound"] == classes["coarse"]["lowerBound"]
    # `coarse` is open-ended, so it resolves to no value on its own. An adapter
    # declaring it has to supply its own nominalAccuracy.
    assert "upperBound" not in classes["coarse"]
