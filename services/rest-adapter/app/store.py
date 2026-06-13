"""Schema persistence + per-device TTL cache.

Schema persistence follows the placement-editor pattern: the schema is loaded
at startup from a mounted file path; operators replace it at runtime via
PUT /schema, which atomically rewrites the file. No restart required.

The cache holds the latest vendor response per device for `cache_ttl_s`. The
engine polls at ~1Hz; vendors can be slower or rate-limited, so caching keeps
us well-behaved without changing the engine.
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .schema import Schema

log = logging.getLogger(__name__)


def load_schema(path: str) -> Optional[Schema]:
    """Read and validate a schema from disk. Returns None if absent or invalid.

    Invalid files are logged but do not raise - the pod still boots into an
    'unconfigured' state, so the operator can PUT a corrected schema.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
        return Schema.model_validate(raw)
    except Exception as exc:
        log.warning("schema at %s is invalid (%s); starting unconfigured", path, exc)
        return None


def save_schema(path: str, schema: Schema) -> None:
    """Atomically write schema to disk.

    The two-phase write avoids leaving a half-written file if the pod is
    killed mid-save. fsync of the directory is omitted intentionally: the
    operator's PUT call can always be retried.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = schema.model_dump(mode="json")
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".schema.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


@dataclass
class State:
    """Mutable runtime state shared across requests.

    Lives on app.state. The schema may be None until the operator loads one.
    """

    schema: Optional[Schema] = None
    cache: dict[str, _CacheEntry] = field(default_factory=dict)

    def cache_get(self, device_id: str) -> Optional[Any]:
        e = self.cache.get(device_id)
        if e is None:
            return None
        if time.monotonic() >= e.expires_at:
            del self.cache[device_id]
            return None
        return e.value

    def cache_put(self, device_id: str, value: Any, ttl_s: float) -> None:
        self.cache[device_id] = _CacheEntry(value=value, expires_at=time.monotonic() + ttl_s)

    def cache_clear(self) -> None:
        self.cache.clear()
