"""Schema persistence + per-device TTL cache.

Schema persistence follows the placement-editor pattern: the schema is loaded
at startup from a mounted file path; operators replace it at runtime via
PUT /schema, which applies it live and best-effort persists it (atomic rename,
falling back to in-place write). A read-only mount - a ConfigMap / subPath -
takes the schema live but cannot persist it; the PUT reports persisted:false
rather than failing. Persistence wants a writable volume (PVC).

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


def save_schema(path: str, schema: Schema) -> bool:
    """Persist the schema to disk. Returns True when it landed, False when the
    target volume cannot be written.

    Three tiers, degrading gracefully:
      1. atomic: tmp file in the same dir + rename over the target (crash-safe).
      2. in-place write: when the target is a bind-mounted single file, the
         rename fails with EBUSY (you cannot rename over a mount) - fall back to
         truncating it in place. Loses crash-safety, keeps the data flowing.
      3. give up: a ConfigMap / subPath mount is READ-ONLY, so even the in-place
         write fails (EROFS/EBUSY). Return False so the caller can report that
         the schema is live but not persisted, instead of a 500. Edit the
         ConfigMap + restart, or mount the schema on a writable volume.
    """
    p = Path(path)
    blob = json.dumps(schema.model_dump(mode="json"), indent=2)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".schema.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(blob)
            os.replace(tmp, p)
            return True
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError as exc:
        log.warning("schema atomic write failed (%s); trying in-place", exc)
    try:
        p.write_text(blob)
        return True
    except OSError as exc:
        log.warning(
            "schema NOT persisted (%s): the schema volume is read-only "
            "(ConfigMap/subPath?). Applied live; edit the source + restart to persist.",
            exc,
        )
        return False


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
