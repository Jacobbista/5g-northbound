"""GET /devices - device discovery for onboarding.

Standard adapter discovery endpoint (mirrors wifi's), so the management layer
gets one shape across sources. For the rest-adapter this is the vendor's own
inventory: it reuses the schema `discover` walker, so the id a candidate
carries is the vendor device id - exactly the value that becomes the asset's
`positioning_id` and is substituted back into the vendor URL at fix time.

`origin: inventory` - the vendor cloud maintains a stable, pre-named list, so
these are bulk-onboardable (unlike wifi's activity-observed candidates).
"""

from fastapi import APIRouter, Request

from ..discover import discover

router = APIRouter(tags=["devices"])


@router.get("/devices")
async def devices(request: Request) -> dict:
    schema = request.app.state.store.schema
    # No schema, or a vendor whose schema opted out of discovery: nothing to
    # enumerate. Return an empty inventory rather than erroring - the engine
    # aggregator treats it as "this source has no candidates".
    if schema is None or schema.discover is None:
        return {"origin": "inventory", "devices": []}
    found = await discover(schema)
    # Anchor classification is schema-declared (not hardcoded): a candidate is
    # an anchor when its native device_type is listed in the vendor schema's
    # `anchor_types`. When the schema declares none, role is left off and every
    # candidate is onboardable - the consumer decides.
    anchor_types = set(schema.discover.anchor_types or [])
    out = []
    for d in found or []:
        vid = d.get("vendor_device_id")
        if not vid:
            continue
        entry = {"id": vid}
        if d.get("label"):
            entry["label"] = d["label"]
        device_type = d.get("device_type")
        if device_type:
            entry["device_type"] = device_type
            if anchor_types:
                entry["role"] = "anchor" if device_type in anchor_types else "trackable"
        lat, lon = d.get("latitude"), d.get("longitude")
        if lat is not None and lon is not None:
            entry["position"] = {"latitude": lat, "longitude": lon}
        out.append(entry)
    return {"origin": "inventory", "devices": out}
