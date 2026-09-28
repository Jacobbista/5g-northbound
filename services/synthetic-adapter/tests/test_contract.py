from pathlib import Path

import yaml

from app.config import Settings


async def test_contract_served_without_auth(client):
    r = await client.get("/contract")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "synthetic-adapter"
    assert body["kind"] == "internal"
    assert body["external_origin"] is None
    names = [e["name"] for tier in body["env"].values() for e in tier]
    assert "DEVICE_IDS" in names
    for tier in body["env"].values():
        for entry in tier:
            assert "value" not in entry


def test_contract_declares_every_setting_the_service_reads():
    # The contract lists what the binary reads. STEP_M is parsed for old
    # configurations and has no effect, so it is not offered.
    contract = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "env.contract.yaml").read_text()
    )
    declared = {e["name"] for tier in ("required", "optional") for e in contract.get(tier) or []}
    settings = {name.upper() for name in Settings.model_fields} - {"STEP_M"}
    assert settings <= declared
