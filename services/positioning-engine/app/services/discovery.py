"""Capability-driven broadcast discovery.

The live-positions broadcast does not read a static device list or the
gateway's asset map - it learns which positioning ids to broadcast, and which
source positions each, from the adapters themselves. Every adapter that
advertises the `devices` capability enumerates the ids it serves; the adapter
that reports an id IS its source. This keeps the engine asset-agnostic (it
holds no id->source map of its own) and routes each broadcast fix to a single
adapter instead of fanning out and fusing.
"""

import asyncio
import logging

log = logging.getLogger(__name__)

# A real observation outranks a declared inventory: if a device is actually
# being seen (a live scan/measurement arrived), route it to that source rather
# than to a mock that merely lists it. Unknown origins rank lowest.
_ORIGIN_RANK = {"observed": 2, "inventory": 1}


async def resolve_broadcast_targets(registry) -> dict[str, str]:
    """Map each discoverable positioning_id to the one source that should
    position it, from adapters advertising the `devices` capability.

    When two adapters report the same id (a misconfiguration - in steady state
    each id is served by exactly one source), precedence is DETERMINISTIC, never
    first-responder: higher origin rank (observed > inventory), then adapter
    name alphabetically. This stops the broadcast flip-flopping between sources.
    """
    pairs = registry.device_adapters()
    if not pairs:
        return {}
    results = await asyncio.gather(
        *[adapter.get_devices() for _, adapter in pairs],
        return_exceptions=True,
    )
    # id -> (origin_rank, source_name) of the current best claimant
    chosen: dict[str, tuple[int, str]] = {}
    for (name, _), res in zip(pairs, results):
        if isinstance(res, Exception) or not isinstance(res, dict):
            continue
        rank = _ORIGIN_RANK.get(res.get("origin") or "", 0)
        for d in res.get("devices") or []:
            did = d.get("id")
            if not did:
                continue
            cur = chosen.get(did)
            if cur is None or rank > cur[0] or (rank == cur[0] and name < cur[1]):
                chosen[did] = (rank, name)
    return {did: src for did, (_, src) in chosen.items()}
