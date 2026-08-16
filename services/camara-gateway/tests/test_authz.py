"""2-legged org-scoped authorisation (gap 3).

A token's `org` claim is joined against the asset's `org`. A consumer sees
only its tenant; a cross-tenant asset reads as 404 (no existence leak). A
token with no `org` (untenanted / dev) sees everything.
"""
import pytest

ROLE = "camara-location-read"
RETRIEVE = "/location-retrieval/v0.5/retrieve"
ASSETS = "/assets"


def _hdr(make_token, org=None):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE], org=org)}"}


async def test_retrieve_same_tenant_ok(client, make_token):
    # pkg-4471 is org=acme (conftest _TEST_ASSETS).
    resp = await client.post(RETRIEVE, json={"device": {"assetId": "pkg-4471"}},
                             headers=_hdr(make_token, org="acme"))
    assert resp.status_code == 200
    assert resp.json()["source"] == "wittra"


async def test_retrieve_cross_tenant_404(client, make_token):
    resp = await client.post(RETRIEVE, json={"device": {"assetId": "pkg-4471"}},
                             headers=_hdr(make_token, org="atlas"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "IDENTIFIER_NOT_FOUND"


async def test_retrieve_no_org_sees_all(client, make_token):
    resp = await client.post(RETRIEVE, json={"device": {"assetId": "pkg-4471"}},
                             headers=_hdr(make_token, org=None))
    assert resp.status_code == 200


async def test_assets_list_filtered_by_org(client, make_token):
    # all seeded assets are acme -> a acme token sees all 3.
    same = await client.get(ASSETS, headers=_hdr(make_token, org="acme"))
    assert {a["asset_id"] for a in same.json()["assets"]} == {"tool-880", "forklift-7", "pkg-4471"}
    # a different tenant sees none.
    other = await client.get(ASSETS, headers=_hdr(make_token, org="atlas"))
    assert other.json()["assets"] == []


async def test_details_cross_tenant_404(client, make_token):
    resp = await client.get(f"{ASSETS}/pkg-4471/details", headers=_hdr(make_token, org="atlas"))
    assert resp.status_code == 404
