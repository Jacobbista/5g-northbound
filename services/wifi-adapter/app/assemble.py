"""Assemble a WifiConfig from blueprint + bindings.

The deployed adapter receives two files:

  1. Blueprint (placement-editor JSON) - owns positions, room geometry,
     anchor ids, georef. Portable across clusters.
  2. Bindings (this service's per-venue config) - owns tunables +
     per-anchor BSSIDs. Sensitive, never committed, lives next to the
     blueprint on the cluster's PVC / ConfigMap.

This module joins them on anchor `id` and emits the single WifiConfig
the trilateration code already consumes. If LAYOUT_PATH is not set, we
fall back to reading positions from the bindings file too (legacy mode
used by tests and the no-blueprint demo).
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .models import Router, WifiBindings, WifiConfig

log = logging.getLogger(__name__)


def _normalize_layout(raw: dict) -> dict:
    """Lift legacy v1 blueprint (room_w / room_h / aps) to the v2 shape
    we consume below. v2 blueprints (`rooms[]`, `floor_plans[]`) pass
    through unchanged."""
    if raw.get("version") == 2 and isinstance(raw.get("rooms"), list):
        return raw
    return {
        "version": 2,
        "floor_plans": raw.get("floor_plans") or [],
        "rooms": [
            {
                "id": "room-01",
                "width_m": float(raw.get("room_w") or 0),
                "height_m": float(raw.get("room_h") or 0),
                "anchors": raw.get("aps") or [],
            }
        ],
    }


def bindings_from_dict(data: dict) -> WifiBindings:
    """Normalise a raw bindings dict (as read from disk or PUT over HTTP) into
    a WifiBindings. Legacy `routers: [{id, x, y, bssids}]` is lifted to the
    `bindings` shape - we drop x/y (positions come from the blueprint) but keep
    id, bssids, and any per-AP tx_power / path_loss_n so an old config imports
    without losing its calibration."""
    if "bindings" not in data and isinstance(data.get("routers"), list):
        data = {
            **data,
            "bindings": [
                {
                    "id": r.get("id"),
                    "bssids": r.get("bssids") or [],
                    "tx_power": r.get("tx_power"),
                    "path_loss_n": r.get("path_loss_n"),
                }
                for r in data["routers"]
                if r.get("id")
            ],
        }
    return WifiBindings.model_validate(data)


def load_bindings(path: Path) -> WifiBindings:
    """Read the per-venue bindings + tunables file. Legacy wifi-config.json
    layouts (with positions inline) are also accepted: we ignore the x/y
    here because positions come from the blueprint.

    An absent, unreadable, or invalid bindings file (an unseeded PVC, or the
    k8s subPath-as-directory footgun where the path is a directory) is treated
    as EMPTY bindings rather than crashing the adapter. wifi then comes up
    ready with the blueprint's anchor positions and no BSSIDs, and picks the
    bindings up once they are written (bindings import / operator config)."""
    try:
        text = path.read_text()
    except OSError as exc:
        log.warning(
            "wifi-adapter: bindings not readable at %s (%s); starting with empty bindings",
            path, exc,
        )
        return WifiBindings.model_validate({"bindings": []})
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning(
            "wifi-adapter: bindings at %s is not valid JSON (%s); starting with empty bindings",
            path, exc,
        )
        return WifiBindings.model_validate({"bindings": []})
    return bindings_from_dict(data)


def assemble_from_blueprint(
    blueprint_path: Path, bindings_path: Path
) -> WifiConfig:
    """File-reading wrapper kept for legacy callers / tests."""
    return assemble_from_blueprint_dict(json.loads(blueprint_path.read_text()), bindings_path)


def assemble_from_blueprint_dict(
    raw_layout: dict, bindings_path: Path
) -> WifiConfig:
    """Build a WifiConfig by joining blueprint positions to BSSID bindings.

    The blueprint arrives as a dict (fetched over HTTP from the engine, the
    blueprint authority). Anchors with `technology != "wifi"` are skipped - UWB
    and 5G anchors live in their own adapters. Anchors with no matching binding
    are logged + dropped (no positioning without a BSSID). Bindings with no
    matching anchor are also logged + dropped (no positioning without a
    position).
    """
    layout = _normalize_layout(raw_layout)
    rooms = layout.get("rooms") or []
    if not rooms:
        raise ValueError("blueprint has no rooms")
    room = rooms[0]
    width = float(room.get("width_m") or 0)
    height = float(room.get("height_m") or 0)
    wifi_anchors = [
        a for a in (room.get("anchors") or [])
        if (a.get("technology") or "wifi") == "wifi"
    ]
    anchor_by_id = {a["id"]: a for a in wifi_anchors if a.get("id")}

    bindings = load_bindings(bindings_path)
    binding_by_id = {b.id: b for b in bindings.bindings}

    routers: list[Router] = []
    for anchor_id, anchor in anchor_by_id.items():
        binding = binding_by_id.get(anchor_id)
        if binding is None or not binding.bssids:
            log.warning(
                "wifi-adapter: anchor %s has no BSSID binding; skipped",
                anchor_id,
            )
            continue
        routers.append(
            Router(
                id=anchor_id,
                x=float(anchor.get("x") or 0),
                y=float(anchor.get("y") or 0),
                bssids=binding.bssids,
                tx_power=binding.tx_power,
                path_loss_n=binding.path_loss_n,
            )
        )
    for binding_id in binding_by_id:
        if binding_id not in anchor_by_id:
            log.warning(
                "wifi-adapter: binding for %s has no matching anchor in blueprint; skipped",
                binding_id,
            )

    # GPS origin from the blueprint's first floor plan, if any.
    gps_origin: Optional[dict] = None
    fp = (layout.get("floor_plans") or [{}])[0]
    georef = fp.get("georef") or {}
    if georef.get("latitude") is not None and georef.get("longitude") is not None:
        gps_origin = {
            "latitude": float(georef["latitude"]),
            "longitude": float(georef["longitude"]),
        }

    # Room origin + floor-plan height: lift the room-local fix into the
    # engine's `local` frame (floor-plan-local, north-up) at emit time.
    base_x = float(room.get("x_m") or 0)
    base_y = float(room.get("y_m") or 0)
    fp_height_m = float(georef.get("height_m") or 0)

    return WifiConfig(
        room_w=width,
        room_h=height,
        base_x=base_x,
        base_y=base_y,
        fp_height_m=fp_height_m,
        tx_power=bindings.tx_power,
        path_loss_n=bindings.path_loss_n,
        gps_origin=gps_origin,
        routers=routers,
        algorithm=bindings.algorithm,
        weight_power=bindings.weight_power,
        smoothing=bindings.smoothing,
        process_noise=bindings.process_noise,
    )


def persist_calibration(
    bindings_path: Path,
    overrides: dict[str, dict],
    samples: list,
) -> None:
    """Write per-AP `tx_power` and `path_loss_n` overrides plus the
    survey samples back to the bindings file on disk.

    Atomic-ish: writes to a temp file and renames over the target so a
    crash mid-write does not leave the operator with a half-empty config.
    """
    from .models import CalibrationSample

    # Tolerate an absent / unreadable / invalid bindings file (unseeded PVC):
    # start from an empty doc so an import is a valid recovery path that
    # CREATES the file rather than failing on read.
    try:
        raw = json.loads(bindings_path.read_text())
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    # Update or insert per-binding overrides keyed by id.
    bindings_list = raw.get("bindings")
    if not isinstance(bindings_list, list):
        # Legacy `routers` shape: lift to bindings first.
        legacy = raw.get("routers") or []
        bindings_list = [
            {"id": r.get("id"), "bssids": r.get("bssids") or []}
            for r in legacy
            if r.get("id")
        ]
        raw["bindings"] = bindings_list

    # Insert entries for imported anchor ids that have no binding yet, so
    # calibration imported into an empty config persists (BSSIDs stay empty
    # until the operator supplies them; the RF params are what we're writing).
    by_id = {e.get("id"): e for e in bindings_list if e.get("id")}
    for anchor_id, ov in overrides.items():
        entry = by_id.get(anchor_id)
        if entry is None:
            entry = {"id": anchor_id, "bssids": []}
            bindings_list.append(entry)
            by_id[anchor_id] = entry
        entry["tx_power"] = ov.get("tx_power")
        entry["path_loss_n"] = ov.get("path_loss_n")

    raw["calibration_samples"] = [
        s.model_dump() if isinstance(s, CalibrationSample) else dict(s)
        for s in samples
    ]

    _atomic_write(bindings_path, json.dumps(raw, indent=2, ensure_ascii=False))
    log.info(
        "wifi-adapter: calibration persisted (overrides=%d, samples=%d) -> %s",
        len(overrides), len(samples), bindings_path,
    )


def write_bindings(bindings_path: Path, bindings: WifiBindings) -> None:
    """Replace the whole per-venue bindings file with `bindings` (BSSIDs +
    tunables + calibration samples). This is the write half of the config
    transfer flow: an operator calibrates on one cluster, exports the file,
    and imports it here. Replace-semantics, like PUT /blueprint - the uploaded
    document is authoritative."""
    doc = bindings.model_dump()
    _atomic_write(bindings_path, json.dumps(doc, indent=2, ensure_ascii=False))
    log.info(
        "wifi-adapter: bindings replaced (bindings=%d, samples=%d) -> %s",
        len(bindings.bindings), len(bindings.calibration_samples), bindings_path,
    )


def _atomic_write(path: Path, blob: str) -> None:
    """Best-effort atomic write: tmp file in the same directory, then rename
    over the target. When the container user lacks write permission on the
    parent directory (common with single-file bind mounts), fall back to
    writing in place - we lose crash-safety there but keep the data flowing."""
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(blob)
        tmp.replace(path)
    except PermissionError as exc:
        log.warning(
            "wifi-adapter: atomic rename not available (%s); writing in place",
            exc,
        )
        path.write_text(blob)


def load_wifi_config(
    bindings_path: Path,
    blueprint_path: Optional[Path] = None,
    blueprint: Optional[dict] = None,
) -> WifiConfig:
    """Single entry point used by main.py. Blueprint mode when a blueprint is
    available (a dict fetched from the engine, or a readable file path), legacy
    mode otherwise. Bindings always come from the local file (PVC)."""
    if blueprint is not None:
        cfg = assemble_from_blueprint_dict(blueprint, bindings_path)
        log.info(
            "wifi-adapter: blueprint mode (from engine, bindings=%s) - %d routers",
            bindings_path, len(cfg.routers),
        )
        return cfg
    if blueprint_path is not None and blueprint_path.is_file():
        cfg = assemble_from_blueprint(blueprint_path, bindings_path)
        log.info(
            "wifi-adapter: blueprint mode (layout=%s, bindings=%s) - %d routers",
            blueprint_path,
            bindings_path,
            len(cfg.routers),
        )
        return cfg
    # Legacy mode - bindings file carries positions inline. Accepts both
    # the historical `routers: [{id, x, y, bssids}]` and the new
    # `bindings: [...]` plus tunables shape.
    raw = json.loads(bindings_path.read_text())
    if "routers" in raw and isinstance(raw["routers"], list):
        cfg = WifiConfig.model_validate(raw)
        log.info(
            "wifi-adapter: legacy mode (%s) - %d routers",
            bindings_path,
            len(cfg.routers),
        )
        return cfg
    raise ValueError(
        f"wifi-adapter: {bindings_path} has no positions and no blueprint is "
        "configured. Set LAYOUT_PATH to point at the placement-editor JSON, or "
        "add `routers: [{id, x, y, bssids}]` to the bindings file."
    )
