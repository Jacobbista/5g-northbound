import asyncio
import logging
from datetime import datetime, timezone

from fastapi import Request

from ..adapters.base import Adapter
from ..models import InternalPosition
from .fusion import fuse

log = logging.getLogger(__name__)


class PositionService:
    def __init__(self, adapters: list[Adapter]):
        self._adapters = adapters

    async def get_position(self, device_id: str) -> InternalPosition:
        results = await asyncio.gather(
            *[a.get_measurement(device_id) for a in self._adapters],
            return_exceptions=True,
        )
        measurements = [r for r in results if r is not None and not isinstance(r, Exception)]

        for exc in results:
            if isinstance(exc, Exception):
                log.warning("adapter error for %s: %s", device_id, exc)

        if not measurements:
            log.warning("no measurements for %s, returning zero position", device_id)
            return InternalPosition(
                device_id=device_id,
                x=0.0, y=0.0, z=0.0,
                floor=0,
                accuracy_m=99.9,
                timestamp=datetime.now(timezone.utc).isoformat(),
                sources=[],
            )

        x, y, z, accuracy, sources, ts = fuse(measurements)
        when = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)
        return InternalPosition(
            device_id=device_id,
            x=round(x, 4),
            y=round(y, 4),
            z=round(z, 4),
            floor=0,
            accuracy_m=round(accuracy, 4),
            timestamp=when.isoformat(),
            sources=sources,
        )


def get_position_service(request: Request) -> PositionService:
    return PositionService(request.app.state.adapters)
