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


def load_bindings(path: Path) -> WifiBindings:
    """Read the per-venue bindings + tunables file. Legacy wifi-config.json
    layouts (with positions inline) are also accepted: we ignore the x/y
    here because positions come from the blueprint."""
    data = json.loads(path.read_text())
    # Legacy `routers: [{id, x, y, bssids}]` is treated as bindings - we
    # drop x/y and keep just id + bssids. Operators with old configs
    # still work; new configs should use the cleaner `bindings` field.
    if "bindings" not in data and isinstance(data.get("routers"), list):
        data = {
            **data,
            "bindings": [
                {"id": r.get("id"), "bssids": r.get("bssids") or []}
                for r in data["routers"]
                if r.get("id")
            ],
        }
    return WifiBindings.model_validate(data)


def assemble_from_blueprint(
    blueprint_path: Path, bindings_path: Path
) -> WifiConfig:
    """Build a WifiConfig by joining blueprint positions to BSSID bindings.

    Anchors with `technology != "wifi"` in the blueprint are skipped - UWB
    and 5G anchors live in their own adapters. Anchors with no matching
    binding are logged + dropped (no positioning without a BSSID).
    Bindings with no matching anchor are also logged + dropped (no
    positioning without a position).
    """
    raw_layout = json.loads(blueprint_path.read_text())
    layout = _normalize_layout(raw_layout)
    rooms = layout.get("rooms") or []
    if not rooms:
        raise ValueError(f"blueprint {blueprint_path} has no rooms")
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
                "wifi-positioning: anchor %s has no BSSID binding; skipped",
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
                "wifi-positioning: binding for %s has no matching anchor in blueprint; skipped",
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

    return WifiConfig(
        room_w=width,
        room_h=height,
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

    raw = json.loads(bindings_path.read_text())
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

    for entry in bindings_list:
        anchor_id = entry.get("id")
        ov = overrides.get(anchor_id)
        if not ov:
            continue
        entry["tx_power"] = ov.get("tx_power")
        entry["path_loss_n"] = ov.get("path_loss_n")

    raw["calibration_samples"] = [
        s.model_dump() if isinstance(s, CalibrationSample) else dict(s)
        for s in samples
    ]

    blob = json.dumps(raw, indent=2, ensure_ascii=False)
    # Best-effort atomic write: tmp file in the same directory, then
    # rename over the target. When the container user lacks write
    # permission on the parent directory (common with single-file bind
    # mounts), fall back to writing the bindings file in place. We lose
    # crash-safety in that path but keep the calibration data flowing.
    try:
        tmp = bindings_path.with_suffix(bindings_path.suffix + ".tmp")
        tmp.write_text(blob)
        tmp.replace(bindings_path)
    except PermissionError as exc:
        log.warning(
            "wifi-positioning: atomic rename not available (%s); writing in place",
            exc,
        )
        bindings_path.write_text(blob)
    log.info(
        "wifi-positioning: calibration persisted (overrides=%d, samples=%d) -> %s",
        len(overrides), len(samples), bindings_path,
    )


def load_wifi_config(
    bindings_path: Path, blueprint_path: Optional[Path]
) -> WifiConfig:
    """Single entry point used by main.py. Picks blueprint mode if a
    blueprint path is configured + readable, legacy mode otherwise."""
    if blueprint_path is not None and blueprint_path.is_file():
        cfg = assemble_from_blueprint(blueprint_path, bindings_path)
        log.info(
            "wifi-positioning: blueprint mode (layout=%s, bindings=%s) - %d routers",
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
            "wifi-positioning: legacy mode (%s) - %d routers",
            bindings_path,
            len(cfg.routers),
        )
        return cfg
    raise ValueError(
        f"wifi-positioning: {bindings_path} has no positions and no blueprint is "
        "configured. Set LAYOUT_PATH to point at the placement-editor JSON, or "
        "add `routers: [{id, x, y, bssids}]` to the bindings file."
    )
