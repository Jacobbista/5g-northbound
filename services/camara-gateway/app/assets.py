"""Asset Identity Map: the gateway's first-class registry of tracked assets.

An asset is a thing (UWB tag, tool, pallet, forklift), NOT a cellular
subscriber - it has no MSISDN/IMSI/NAI. The map resolves a CAMARA
`device.assetId` to its capabilities (engine routing) + tenant `org` +
`kind`/`source` metadata. No subscriber lookup ever happens.

Network-authority, mirroring the engine's blueprint store: the map is
persisted on a writable store (PVC) and authored via GET/PUT /assets. On
first boot the store is empty, so it seeds once from a committed read-only
seed file. Conforms to schema/asset.schema.json.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings
from .errors import CamaraError

log = logging.getLogger(__name__)

ASSET_SCHEMA_VERSION = 4


class Capability(BaseModel):
    """One way an asset is positioned: a source and the id that source knows the
    asset by. The same physical thing is a different id to each source."""
    model_config = ConfigDict(extra="ignore")
    source: str
    positioningId: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class Asset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    assetId: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    kind: str
    org: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    capabilities: list[Capability] = Field(min_length=1)
    label: str = ""
    metadata: dict = Field(default_factory=dict)

    @property
    def primary(self) -> Capability:
        """The capability single-target paths (stream, diagnostics, details)
        route on. Multi-capability fusion combines all of them; a single-target
        consumer sees the first."""
        return self.capabilities[0]

    @property
    def source(self) -> str:
        return self.capabilities[0].source

    @property
    def positioning_id(self) -> str:
        return self.capabilities[0].positioningId


class AssetMap(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: int = ASSET_SCHEMA_VERSION
    assets: list[Asset] = Field(default_factory=list)


def _store_path() -> Path:
    return Path(get_settings().asset_store_file)


def _read(path: Path) -> AssetMap | None:
    try:
        return AssetMap.model_validate_json(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("asset map %s unreadable (%s)", path, exc)
        return None


def load_asset_map() -> AssetMap:
    """Return the current map from the store, seeding once on first boot.

    Store present -> use it. Store absent -> seed from the committed seed file
    and persist, so subsequent reads (and restarts) boot configured. Neither
    present -> empty map (the gateway still serves; PUT /assets populates it).
    """
    store = _store_path()
    current = _read(store) if store.exists() else None
    if current is not None:
        return current

    seed_path = Path(get_settings().asset_seed_file)
    seed = _read(seed_path) if seed_path.exists() else None
    if seed is not None:
        if (repeat := _repeated_asset_id(seed)) is not None:
            log.warning("asset map: seed %s lists assetId '%s' twice, requests resolve the first", seed_path, repeat[0])
        log.info("asset map: seeding store %s from %s (%d assets)", store, seed_path, len(seed.assets))
        save_asset_map(seed)
        return seed

    log.warning("asset map: no store and no seed; starting empty")
    return AssetMap()


def save_asset_map(amap: AssetMap) -> None:
    """Atomically persist the map to the store (temp file + rename)."""
    store = _store_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(store.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(amap.model_dump_json(indent=2))
        os.replace(tmp, store)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def list_assets() -> list[Asset]:
    return load_asset_map().assets


def _repeated_asset_id(amap: AssetMap) -> tuple[str, str, str] | None:
    """The first `assetId` the map lists twice, with the organisations of both
    entries. A request names an asset by `assetId` alone, so an id must
    resolve to one asset across every organisation."""
    seen: dict[str, str] = {}
    for asset in amap.assets:
        if asset.assetId in seen:
            return asset.assetId, seen[asset.assetId], asset.org
        seen[asset.assetId] = asset.org
    return None


def validate_for_write(amap: AssetMap) -> None:
    """The structural rules of a map written over PUT /assets. The store is not
    validated again on read, so this is the only gate."""
    repeat = _repeated_asset_id(amap)
    if repeat is not None:
        asset_id, first_org, second_org = repeat
        where = (
            f"in organisation '{first_org}'" if first_org == second_org
            else f"in organisations '{first_org}' and '{second_org}'"
        )
        raise CamaraError(422, "DUPLICATE_ASSET_ID", f"assetId '{asset_id}' appears twice, {where}.")
    _reject_duplicate_positioning_ids(amap)


def _reject_duplicate_positioning_ids(amap: AssetMap) -> None:
    """The engine routes a `positioningId` to exactly one adapter-learned
    source (docs/asset-registry.md); two assets claiming the same one starve
    one of them on the stream (an internal lookup keyed by positioningId can
    resolve to only one asset) and would blend one asset's telemetry into the
    other's fusion."""
    seen: dict[str, str] = {}
    for asset in amap.assets:
        for cap in asset.capabilities:
            prior = seen.get(cap.positioningId)
            if prior is not None:
                raise CamaraError(
                    422, "DUPLICATE_POSITIONING_ID",
                    f"positioningId '{cap.positioningId}' is claimed by both "
                    f"'{prior}' and '{asset.assetId}'.",
                )
            seen[cap.positioningId] = asset.assetId


def asset_by_id(asset_id: str) -> Asset | None:
    return next((a for a in list_assets() if a.assetId == asset_id), None)
