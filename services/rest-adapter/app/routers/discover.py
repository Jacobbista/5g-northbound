"""Vendor device discovery endpoint.

GET /discover walks the vendor's list endpoint (as declared in the active
schema's optional `discover` block) and returns a normalised array of
entries. The placement editor calls this through the editor backend
proxy when the operator opens the "sync vendor" panel.

Shape:
    {
      "vendor": "<schema.vendor>",
      "devices": [
        {
          "vendor_device_id": "f8f8052000ea96f8",
          "label":            "Tag 01",
          "latitude":         59.4047,
          "longitude":        17.9492,
          "height_m":         3.0
        },
        ...
      ]
    }

`label`, `latitude`, `longitude`, `height_m` are optional and may be
absent when the vendor does not expose them. The editor falls back to
manual placement for entries without coordinates.

Status codes:
    200  always when the active schema declares a `discover` block and
         the vendor responded (an empty `devices` array is a valid 200)
    404  when the active schema has no `discover` block (the vendor's
         schema author opted out of sync)
    503  when no schema is loaded, or the vendor is unreachable / misconfigured
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from ..discover import discover

log = logging.getLogger(__name__)
router = APIRouter(tags=["discover"])


@router.get("/discover")
async def list_devices(request: Request) -> dict:
    schema = request.app.state.store.schema
    if schema is None:
        raise HTTPException(503, "no schema loaded; PUT /schema first")
    if schema.discover is None:
        raise HTTPException(
            404,
            f"vendor {schema.vendor} has no discover block in its schema",
        )
    devices = await discover(schema)
    if devices is None:
        raise HTTPException(503, f"vendor {schema.vendor} discover failed")
    return {"vendor": schema.vendor, "devices": devices}
