"""GET /devices - device discovery for onboarding (standard adapter shape).

The mock serves a fixed, configured set of ids, so its discovery is an
`inventory`: a stable, known list, bulk-onboardable. It mirrors what a real
on-premise RTLS exposes - tracked tags (`role: asset`, from DEVICE_IDS) plus
fixed anchors/relays (`role: infrastructure`, from ANCHOR_IDS), each tagged with
the `source_class` (the positioning technology). Onboarding keeps the assets and
never onboards infrastructure. Positions are omitted here - the walker
synthesises them on /measurement, and listing should not advance the walk.
"""

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["devices"])


def _csv(raw: str) -> list[str]:
    return sorted({d.strip() for d in raw.split(",") if d.strip()})


def _entry(device_id: str, role: str) -> dict:
    out = {"id": device_id, "role": role}
    if settings.source_class:
        out["source_class"] = settings.source_class
    return out


@router.get("/devices")
async def devices() -> dict:
    assets = [_entry(d, "asset") for d in _csv(settings.device_ids)]
    infra = [_entry(d, "infrastructure") for d in _csv(settings.anchor_ids)]
    return {"origin": "inventory", "devices": assets + infra}
