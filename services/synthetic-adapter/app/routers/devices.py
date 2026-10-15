"""GET /devices - device discovery for onboarding (standard adapter shape).

The source's discovery is an `inventory`: the tags it declares
(`role: asset`, from DEVICE_IDS) and the devices placed beyond them, plus fixed
anchors/relays (`role: infrastructure`, from ANCHOR_IDS), each tagged with the
`source_class` (the positioning technology). Onboarding keeps the assets and
never onboards infrastructure. Positions are omitted here - the walker
synthesises them on /measurement, and listing should not advance the walk.
"""

from fastapi import APIRouter, Request

from ..config import settings

router = APIRouter(tags=["devices"])


def _csv(raw: str) -> list[str]:
    return sorted({d.strip() for d in raw.split(",") if d.strip()})


def _entry(device_id: str, role: str, walker=None) -> dict:
    out = {"id": device_id, "role": role}
    if settings.source_class:
        out["sourceClass"] = settings.source_class
    # Only meaningful when placement gates reporting. Without it every device
    # walks from boot and `placed` would say nothing, so it is left off.
    if settings.spawn_required and walker is not None:
        out["placed"] = walker.is_active(device_id)
    return out


@router.get("/devices")
async def devices(request: Request) -> dict:
    walker = getattr(request.app.state, "walker", None)
    assets = [_entry(d, "asset", walker) for d in _csv(settings.device_ids)]
    # Devices that exist because they were placed, listed while they are.
    if walker is not None:
        assets += [{**_entry(d, "asset"), "placed": True} for d in walker.placed_undeclared()]
    # Anchors are fixed infrastructure, never walked and never placed.
    infra = [_entry(d, "infrastructure") for d in _csv(settings.anchor_ids)]
    return {"origin": "inventory", "devices": assets + infra}
