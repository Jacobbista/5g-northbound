"""Adapter registry: the engine is the authority for which adapters exist.

Adapters self-register (`POST /adapters`) at boot and heartbeat periodically;
the engine evicts self-registered entries that stop beating (TTL). `ADAPTER_URLS`
is only a cold-start seed, applied once to an empty registry. Two provenance
classes, with different lifecycles:

  - ``self``        : maintained by heartbeat, TTL-evicted, NOT persisted
                      (repopulates on the next adapter boot within one interval)

A name can be served by several running instances of one adapter: replicas,
or the old and the new pod of a rolling update. Each announces its own
`instance` id. The entry lives while any instance does: a deregistration
removes only the instance that sends it, and the TTL counts from the most
recent announcement of any instance.
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
from .config import adapter_budget, adapter_options

log = logging.getLogger(__name__)

SELF = "self"
SEED = "seed"
MANUAL = "manual"
_PERSISTED_VIA = {SEED, MANUAL}


class _Entry:
    __slots__ = ("name", "base_url", "kind", "registered_via", "last_seen", "adapter", "capabilities",
                 "instances")

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
        # Running instances that announced this name: instance id -> when it
        # last announced. Empty for a seeded entry or an adapter that
        # announces no instance.
        self.instances: dict[str, float] = {}


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
               capabilities: Optional[dict] = None,
               instance: Optional[str] = None) -> Optional[HttpAdapter]:
        """Register or heartbeat. Returns an orphaned HttpAdapter to close when
        an existing entry's endpoint changed, else None."""
        now = self._clock()
        existing = self._entries.get(name)
        if existing is not None and existing.base_url == base_url:
            if instance:
                existing.instances[instance] = now
            # Same endpoint: a heartbeat. Keep the HttpAdapter (and its cooldown
            # state); refresh lastSeen + capabilities. Allow self -> seed/manual
            # promotion, never demote a declared entry back to self.
            existing.last_seen = now
            if capabilities:
                existing.capabilities = capabilities
                existing.adapter.timeout = adapter_budget(name, capabilities)
            if existing.registered_via == SELF and via in _PERSISTED_VIA:
                existing.registered_via = via
            return None
        orphan = existing.adapter if existing is not None else None
        options = adapter_options(name)
        options["timeout"] = adapter_budget(name, capabilities)
        adapter = HttpAdapter(name=name, base_url=base_url, **options)
        entry = _Entry(name, base_url, kind, via, now, adapter, capabilities)
        if existing is not None:
            # A new endpoint for the same adapter: the instances that announced
            # the old one are still instances of this adapter.
            entry.instances = {i: t for i, t in existing.instances.items() if now - t <= self._ttl}
        if instance:
            entry.instances[instance] = now
        self._entries[name] = entry
        self.adapters[name] = adapter
        return orphan

    def remove(self, name: str, instance: Optional[str] = None) -> tuple[bool, Optional[HttpAdapter]]:
        """Deregister. With `instance`, only that instance leaves, and the
        entry goes with it only when no other live instance remains. Without
        it, the entry goes, unless instances that identified themselves are
        still live: the sender is none of them, for example an older adapter
        stopping after its replacement registered. Returns whether anything
        was removed, and the orphaned HttpAdapter to close when the entry
        went."""
        entry = self._entries.get(name)
        if entry is None:
            return False, None
        now = self._clock()
        if not instance and any(now - t <= self._ttl for t in entry.instances.values()):
            return False, None
        if instance and entry.instances:
            if entry.instances.pop(instance, None) is None:
                return False, None
            live = {i: t for i, t in entry.instances.items() if now - t <= self._ttl}
            entry.instances = live
            if live:
                entry.last_seen = max(live.values())
                return True, None
        del self._entries[name]
        self.adapters.pop(name, None)
        return True, entry.adapter

    def evict_expired(self) -> list[HttpAdapter]:
        """Drop self-registered entries past TTL (seed/manual are immune).
        Returns the orphaned clients to close."""
        now = self._clock()
        orphans, names = [], []
        for name, e in list(self._entries.items()):
            # An instance that stopped without deregistering ages out alone.
            e.instances = {i: t for i, t in e.instances.items() if now - t <= self._ttl}
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
            {"name": e.name, "baseUrl": e.base_url, "kind": e.kind,
             "registeredVia": e.registered_via, "capabilities": e.capabilities}
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
            # A file written before 0.16.0 carries the superseded names. Read
            # both so an upgrade restores its declared adapters instead of
            # crashing the boot; the next persist() rewrites the file.
            via = d.get("registeredVia") or d.get("registered_via") or MANUAL
            if via not in _PERSISTED_VIA:
                continue
            base_url = d.get("baseUrl") or d.get("base_url")
            if not d.get("name") or not base_url:
                log.warning("registry: skipping unreadable persisted entry %r", d)
                continue
            self.upsert(d["name"], base_url, d.get("kind") or "adapter", via, d.get("capabilities"))
        return len(self._entries)

    def is_empty(self) -> bool:
        return not self._entries

    # --- read --------------------------------------------------------------

    def _state(self, e: _Entry, now: float) -> str:
        in_cooldown = e.adapter.status().get("inCooldown", False)
        if e.registered_via == SELF and (now - e.last_seen) > self._heartbeat:
            return "stale"
        if in_cooldown:
            return "unreachable"
        return "live"

    def device_adapters(self) -> list[tuple[str, HttpAdapter]]:
        """Live adapters that advertise the `devices` capability - the sources
        the engine polls for onboarding discovery. Unreachable/stale entries are
        skipped so a dead source does not stall the aggregate."""
        now = self._clock()
        return [
            (e.name, e.adapter)
            for e in self._entries.values()
            if e.capabilities.get("devices") and self._state(e, now) == "live"
        ]

    def capabilities_for(self, name: str) -> dict:
        """The capabilities the named adapter last advertised (empty if
        unknown). PositionService reads `accuracy_class` from this to fill a
        nominal accuracy when a measurement reports none - a live read, not a
        snapshot, since capabilities refresh on every heartbeat."""
        entry = self._entries.get(name)
        return entry.capabilities if entry is not None else {}

    def status_list(self) -> list[dict]:
        now = self._clock()
        out = []
        for e in self._entries.values():
            st = e.adapter.status()
            st.update(
                kind=e.kind,
                registeredVia=e.registered_via,
                instances=len(e.instances),
                lastSeenSAgo=round(now - e.last_seen, 1),
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
