"""Asset Identity Map: the gateway's first-class registry of tracked assets.

An asset is a thing (UWB tag, tool, pallet, forklift), NOT a cellular
subscriber - it has no MSISDN/IMSI/NAI. The map resolves a CAMARA
`device.assetId` to a positioning id (engine routing) + tenant `org` +
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

log = logging.getLogger(__name__)

ASSET_SCHEMA_VERSION = 2


class Asset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    asset_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    positioning_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    kind: str
    source: str
    org: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    label: str = ""
    simulated: bool = False
    metadata: dict = Field(default_factory=dict)


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


def asset_by_id(asset_id: str) -> Asset | None:
    return next((a for a in list_assets() if a.asset_id == asset_id), None)
