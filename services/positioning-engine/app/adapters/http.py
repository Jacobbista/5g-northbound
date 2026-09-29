import logging
import time
from typing import Callable, Optional

import httpx

from pydantic import ValidationError

from .base import Adapter, Measurement
from ..wire import DevicesBody, MeasurementBody
from ..obs import corr_headers

log = logging.getLogger(__name__)


COOLDOWN_FAIL_THRESHOLD = 3       # consecutive failures before cooldown kicks in
COOLDOWN_BASE_S = 2.0             # first cooldown window
COOLDOWN_MAX_S = 60.0             # cap on the exponential backoff

class HttpAdapter(Adapter):
    """Generic HTTP adapter - pulls a Measurement from any service that speaks
    the contract: GET {base_url}/measurement/{device_id}.

    The same engine talks to wifi-adapter (open algo, in this repo) and to
    vendor pods (private images) without code changes. Switching backends is a
    deployment concern: change ADAPTER_URLS, not the engine image.

    Resilience: consecutive network or 5xx failures trigger a short cooldown
    during which the adapter returns None without issuing a request. The
    cooldown doubles each time the adapter fails again after a probe attempt,
    capped at COOLDOWN_MAX_S. A 404 is not a failure - it means "no fix" and
    leaves the counter untouched.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        timeout: float = 1.0,
        headers: Optional[dict[str, str]] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers or {})
        self._clock = clock or time.monotonic
        self._fail_count = 0
        self._cooldown_until = 0.0

    @property
    def fail_count(self) -> int:
        return self._fail_count

    def _in_cooldown(self) -> bool:
        return self._clock() < self._cooldown_until

    def status(self) -> dict:
        """Snapshot of current adapter health, surfaced on GET /adapters."""
        now = self._clock()
        remaining = max(0.0, self._cooldown_until - now)
        return {
            "name": self.name,
            "baseUrl": self.base_url,
            "failCount": self._fail_count,
            "inCooldown": now < self._cooldown_until,
            "cooldownSecondsRemaining": round(remaining, 2),
        }

    def _record_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= COOLDOWN_FAIL_THRESHOLD:
            # Exponential backoff once the threshold is crossed: 2s, 4s, 8s, …
            exponent = self._fail_count - COOLDOWN_FAIL_THRESHOLD
            window = min(COOLDOWN_BASE_S * (2 ** exponent), COOLDOWN_MAX_S)
            self._cooldown_until = self._clock() + window
            log.warning(
                "adapter %s entering cooldown for %.1fs after %d failures",
                self.name, window, self._fail_count,
            )

    def _record_success(self) -> None:
        if self._fail_count or self._cooldown_until:
            log.info("adapter %s recovered after %d failures", self.name, self._fail_count)
        self._fail_count = 0
        self._cooldown_until = 0.0

    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        if self._in_cooldown():
            return None
        try:
            r = await self._client.get(f"{self.base_url}/measurement/{device_id}", headers=corr_headers())
        except httpx.HTTPError as exc:
            log.warning("adapter %s unreachable: %s", self.base_url, exc)
            self._record_failure()
            return None
        if r.status_code == 404:
            # 404 = adapter is healthy but has no fix yet; do not penalise.
            return None
        if r.status_code != 200:
            log.warning("adapter %s -> %d", self.base_url, r.status_code)
            if r.status_code >= 500:
                self._record_failure()
            return None
        try:
            body = MeasurementBody.model_validate(r.json())
        except (ValueError, ValidationError) as exc:
            log.warning("adapter %s returned malformed body: %s", self.name, exc)
            self._record_failure()
            return None
        measurement = Measurement(
            source=body.source or self.name,
            accuracy=body.accuracy,
            confidence=body.confidence,
            frame=body.frame,
            room=body.room,
            x=body.x if body.x is not None else 0.0,
            y=body.y if body.y is not None else 0.0,
            z=body.z,
            verticalAccuracy=body.verticalAccuracy if body.z is not None else None,
            latitude=body.latitude if body.latitude is not None else 0.0,
            longitude=body.longitude if body.longitude is not None else 0.0,
            timestamp=body.timestamp,
            lastSeen=body.lastSeen,
            diagnostics=body.diagnostics,
        )
        self._record_success()
        return measurement

    async def get_devices(self) -> Optional[dict]:
        """Fetch this adapter's discoverable device list (GET /devices).

        Returns the parsed `{origin, devices}` body, or None when the adapter
        has no such endpoint (404), is in cooldown, or errors. Discovery is a
        best-effort side channel for onboarding, so it never records a failure
        against the measurement cooldown - a source that can position but not
        enumerate should keep positioning."""
        if self._in_cooldown():
            return None
        try:
            r = await self._client.get(f"{self.base_url}/devices", headers=corr_headers())
        except httpx.HTTPError as exc:
            log.warning("adapter %s /devices unreachable: %s", self.base_url, exc)
            return None
        if r.status_code != 200:
            return None
        try:
            body = DevicesBody.model_validate(r.json())
        except (ValueError, ValidationError) as exc:
            log.warning("adapter %s /devices malformed: %s", self.name, exc)
            return None
        return body.model_dump(exclude_none=True)

    async def aclose(self):
        await self._client.aclose()
