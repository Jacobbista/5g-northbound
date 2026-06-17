"""GET /capabilities - what this deployment can actually do, right now.

Derived live, not hardcoded: positioning traits come from the capabilities the
adapters advertise to the engine's registry (proxied via GET /adapters), and
the tenant/kind surface comes from the Asset Identity Map. A consumer discovers
the private-asset profile at runtime instead of reading a static doc - and the
answer shrinks when an adapter goes offline.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..assets import list_assets
from ..auth import consumer_org, require_location_role
from ..position import get_adapter_status

router = APIRouter(prefix="/capabilities", tags=["Capabilities"])


class AdapterCapability(BaseModel):
    name: str
    source: str | None = None
    state: str | None = None
    capabilities: dict = {}


class Capabilities(BaseModel):
    profile: str = "camara-private-asset"
    kinds: list[str]
    sources: list[str]
    orgs: list[str]
    streaming: bool
    altitude: bool
    accuracy_classes: list[str]
    adapters: list[AdapterCapability]


@router.get("", response_model=Capabilities)
async def capabilities(claims: dict = Depends(require_location_role)) -> Capabilities:
    assets = list_assets()
    org = consumer_org(claims)
    if org:  # tenant view: kinds/orgs reflect only the consumer's assets
        assets = [a for a in assets if a.org == org]
    adapters = await get_adapter_status() or []

    kinds: set[str] = {a.kind for a in assets}
    sources: set[str] = set()
    accuracy: set[str] = set()
    streaming = False
    altitude = False
    adapter_caps: list[AdapterCapability] = []

    for ad in adapters:
        caps = ad.get("capabilities") or {}
        if caps.get("source"):
            sources.add(caps["source"])
        for k in caps.get("kinds") or []:
            kinds.add(k)
        if caps.get("accuracy_class"):
            accuracy.add(caps["accuracy_class"])
        streaming = streaming or bool(caps.get("streaming"))
        altitude = altitude or bool(caps.get("z"))
        adapter_caps.append(
            AdapterCapability(
                name=ad.get("name", ""),
                source=caps.get("source"),
                state=ad.get("state"),
                capabilities=caps,
            )
        )

    return Capabilities(
        kinds=sorted(kinds),
        sources=sorted(sources),
        orgs=sorted({a.org for a in assets}),
        streaming=streaming,
        altitude=altitude,
        accuracy_classes=sorted(accuracy),
        adapters=adapter_caps,
    )
