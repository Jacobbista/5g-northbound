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
    # UNFILTERED: onboarding wants the tags the editor's anchor-only filter
    # drops. role / source_class come from the schema's classify block (already
    # merged into each entry by discover()).
    found = await discover(schema, apply_filter=False)
    out = []
    for d in found or []:
        vid = d.get("vendor_device_id")
        if not vid:
            continue
        entry = {"id": vid}
        for src, dst in (("label", "label"), ("device_type", "device_type"),
                         ("role", "role"), ("source_class", "source_class")):
            if d.get(src) is not None:
                entry[dst] = d[src]
        lat, lon = d.get("latitude"), d.get("longitude")
        if lat is not None and lon is not None:
            entry["position"] = {"latitude": lat, "longitude": lon}
        out.append(entry)
    return {"origin": "inventory", "devices": out}
