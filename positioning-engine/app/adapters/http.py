import logging
from typing import Optional

import httpx

from .base import Adapter, Measurement

log = logging.getLogger(__name__)


class HttpAdapter(Adapter):
    """Generic HTTP adapter — pulls a Measurement from any service that speaks
    the contract: GET {base_url}/measurement/{device_id}.

    The same engine talks to wifi-positioning (open algo, in this repo) and to
    vendor pods (private images) without code changes. Switching backends is a
    deployment concern: change ADAPTER_URLS, not the engine image.
    """

    def __init__(self, base_url: str, source: Optional[str] = None, timeout: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.source = source or "http"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        try:
            r = await self._client.get(f"{self.base_url}/measurement/{device_id}")
        except httpx.HTTPError as exc:
            log.warning("adapter %s unreachable: %s", self.base_url, exc)
            return None
        if r.status_code == 404:
            return None  # no fix yet at the adapter
        if r.status_code != 200:
            log.warning("adapter %s -> %d", self.base_url, r.status_code)
            return None
        body = r.json()
        return Measurement(
            source=body.get("source", self.source),
            x=float(body["x"]),
            y=float(body.get("y", 0.0)),
            z=float(body["z"]),
            accuracy_m=float(body["accuracy_m"]),
            confidence=float(body["confidence"]),
            timestamp=body.get("timestamp"),
        )

    async def aclose(self):
        await self._client.aclose()
