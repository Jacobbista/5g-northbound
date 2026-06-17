"""Adapter registry: the engine is the authority for which adapters exist.

Adapters self-register (`POST /adapters`) at boot and heartbeat periodically;
the engine evicts self-registered entries that stop beating (TTL). `ADAPTER_URLS`
is only a cold-start seed, applied once to an empty registry. Two provenance
classes, with different lifecycles:

  - ``self``        : maintained by heartbeat, TTL-evicted, NOT persisted
                      (repopulates on the next adapter boot within one interval)
  - ``seed``/``manual`` : declared intentionally, persisted, NEVER TTL-evicted;
                      liveness comes from polling (cooldown), not heartbeat

The registry OWNS the live adapter dict the PositionService polls. Mutations
are synchronous (mutate the dict, then ``await persist()`` after) so the
single-event-loop no-lock guarantee holds: no ``await`` mid read-modify-write.

State surfaced on GET /adapters (membership x reachability are orthogonal):
  - ``live``        : heartbeat fresh (or seed/manual) AND not in cooldown
  - ``unreachable`` : present but the engine's polls fail (in cooldown) -
                      e.g. a vendor adapter whose upstream cloud is down
  - ``stale``       : self entry that has not re-announced within one heartbeat
                      interval (still within TTL)
"""

import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from .adapters.http import HttpAdapter
from .config import adapter_options

log = logging.getLogger(__name__)

SELF = "self"
SEED = "seed"
MANUAL = "manual"
_PERSISTED_VIA = {SEED, MANUAL}


class _Entry:
    __slots__ = ("name", "base_url", "kind", "registered_via", "last_seen", "adapter", "capabilities")

    def __init__(self, name, base_url, kind, registered_via, last_seen, adapter, capabilities=None):
        self.name = name
        self.base_url = base_url
        self.kind = kind
        self.registered_via = registered_via
        self.last_seen = last_seen
        self.adapter = adapter
        # Self-advertised positioning traits (frame, streaming, z, accuracy
        # class, kinds). Drives the gateway's GET /capabilities so the profile
        # surface reflects what the live deployment can actually do.
        self.capabilities = capabilities or {}


class AdapterRegistry:
    def __init__(
        self,
        ttl_s: float,
        heartbeat_s: float,
        persist_path: str,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._ttl = ttl_s
        self._heartbeat = heartbeat_s
        self._persist_path = persist_path
        self._clock = clock or time.monotonic
        self._entries: dict[str, _Entry] = {}
        # The live dict the PositionService holds by reference. Mutated in
        # place (never reassigned) so the service always sees the current set.
        self.adapters: dict[str, HttpAdapter] = {}

    # --- mutations (synchronous dict update; the async caller awaits
    #     persist() and closes any returned orphan client afterwards, so no
    #     await ever lands mid read-modify-write) -----------------------------

    def upsert(self, name: str, base_url: str, kind: str, via: str,
               capabilities: Optional[dict] = None) -> Optional[HttpAdapter]:
        """Register or heartbeat. Returns an orphaned HttpAdapter to close when
        an existing entry's endpoint changed, else None."""
        now = self._clock()
        existing = self._entries.get(name)
        if existing is not None and existing.base_url == base_url:
            # Same endpoint: a heartbeat. Keep the HttpAdapter (and its cooldown
            # state); refresh last_seen + capabilities. Allow self -> seed/manual
            # promotion, never demote a declared entry back to self.
            existing.last_seen = now
            if capabilities:
                existing.capabilities = capabilities
            if existing.registered_via == SELF and via in _PERSISTED_VIA:
                existing.registered_via = via
            return None
        orphan = existing.adapter if existing is not None else None
        adapter = HttpAdapter(name=name, base_url=base_url, **adapter_options(name))
        self._entries[name] = _Entry(name, base_url, kind, via, now, adapter, capabilities)
        self.adapters[name] = adapter
        return orphan

    def remove(self, name: str) -> Optional[HttpAdapter]:
        """Deregister. Returns the orphaned HttpAdapter to close, or None."""
        entry = self._entries.pop(name, None)
        if entry is None:
            return None
        self.adapters.pop(name, None)
        return entry.adapter

    def evict_expired(self) -> list[HttpAdapter]:
        """Drop self-registered entries past TTL (seed/manual are immune).
        Returns the orphaned clients to close."""
        now = self._clock()
        orphans, names = [], []
        for name, e in list(self._entries.items()):
            if e.registered_via == SELF and (now - e.last_seen) > self._ttl:
                self._entries.pop(name, None)
                self.adapters.pop(name, None)
                orphans.append(e.adapter)
                names.append(name)
        if names:
            log.info("registry: evicted stale self-registered adapters: %s", ", ".join(names))
        return orphans

    # --- persistence (seed/manual only) ------------------------------------

    def persist(self) -> None:
        keep = [
            {"name": e.name, "base_url": e.base_url, "kind": e.kind,
             "registered_via": e.registered_via, "capabilities": e.capabilities}
            for e in self._entries.values()
            if e.registered_via in _PERSISTED_VIA
        ]
        try:
            p = Path(self._persist_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(keep, indent=2))
        except OSError as exc:
            log.warning("registry: could not persist (%s)", exc)

    def load_persisted(self) -> int:
        """Recreate seed/manual entries from the persisted file. Returns count."""
        p = Path(self._persist_path)
        if not p.is_file():
            return 0
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("registry: persisted file unreadable (%s); ignoring", exc)
            return 0
        for d in data:
            via = d.get("registered_via") or MANUAL
            if via not in _PERSISTED_VIA:
                continue
            self.upsert(d["name"], d["base_url"], d.get("kind") or "adapter", via, d.get("capabilities"))
        return len(self._entries)

    def is_empty(self) -> bool:
        return not self._entries

    # --- read --------------------------------------------------------------

    def _state(self, e: _Entry, now: float) -> str:
        in_cooldown = e.adapter.status().get("in_cooldown", False)
        if e.registered_via == SELF and (now - e.last_seen) > self._heartbeat:
            return "stale"
        if in_cooldown:
            return "unreachable"
        return "live"

    def status_list(self) -> list[dict]:
        now = self._clock()
        out = []
        for e in self._entries.values():
            st = e.adapter.status()
            st.update(
                kind=e.kind,
                registered_via=e.registered_via,
                last_seen_s_ago=round(now - e.last_seen, 1),
                state=self._state(e, now),
                capabilities=e.capabilities,
            )
            out.append(st)
        return out

    async def aclose(self) -> None:
        for e in self._entries.values():
            await _safe_aclose(e.adapter)


async def _safe_aclose(adapter: HttpAdapter) -> None:
    try:
        await adapter.aclose()
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        log.debug("adapter aclose failed: %s", exc)
