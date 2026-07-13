import json
from pathlib import Path

import pytest

from app.assemble import (
    assemble_from_blueprint,
    bindings_from_dict,
    load_bindings,
    load_wifi_config,
    write_bindings,
)


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def _blueprint(rooms_anchors):
    return {
        "version": 2,
        "floor_plans": [
            {
                "id": "fp-01",
                "georef": {"latitude": 59.4, "longitude": 17.9, "width_m": 30, "height_m": 20},
            }
        ],
        "rooms": [
            {
                "id": "room-01",
                "width_m": 30,
                "height_m": 20,
                "anchors": rooms_anchors,
            }
        ],
    }


def test_assemble_joins_blueprint_positions_to_bindings(tmp_path):
    blueprint = _write(
        tmp_path,
        "layout.json",
        _blueprint([
            {"id": "AP07", "technology": "wifi", "x": 5.0, "y": 3.0},
            {"id": "AP08", "technology": "wifi", "x": 12.0, "y": 4.0},
        ]),
    )
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {
            "tx_power": -45,
            "bindings": [
                {"id": "AP07", "bssids": ["AA:BB:CC:01:01:01"]},
                {"id": "AP08", "bssids": ["AA:BB:CC:01:01:02"]},
            ],
        },
    )

    cfg = assemble_from_blueprint(blueprint, bindings)

    assert cfg.room_w == 30
    assert cfg.room_h == 20
    assert cfg.tx_power == -45
    assert {r.id for r in cfg.routers} == {"AP07", "AP08"}
    ap07 = next(r for r in cfg.routers if r.id == "AP07")
    assert (ap07.x, ap07.y) == (5.0, 3.0)
    assert ap07.bssids == ["AA:BB:CC:01:01:01"]
    assert cfg.gps_origin is not None
    assert cfg.gps_origin.latitude == 59.4


def test_assemble_skips_non_wifi_anchors(tmp_path):
    blueprint = _write(
        tmp_path,
        "layout.json",
        _blueprint([
            {"id": "AP01", "technology": "wifi", "x": 1.0, "y": 1.0},
            {"id": "UWB01", "technology": "wittra", "x": 2.0, "y": 2.0},
        ]),
    )
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {
            "bindings": [
                {"id": "AP01", "bssids": ["AA:BB:CC:01:01:01"]},
                {"id": "UWB01", "bssids": ["AA:BB:CC:01:01:02"]},
            ]
        },
    )

    cfg = assemble_from_blueprint(blueprint, bindings)
    assert [r.id for r in cfg.routers] == ["AP01"]


def test_assemble_drops_anchors_without_binding(tmp_path):
    blueprint = _write(
        tmp_path,
        "layout.json",
        _blueprint([
            {"id": "AP01", "technology": "wifi", "x": 1.0, "y": 1.0},
            {"id": "AP02", "technology": "wifi", "x": 2.0, "y": 2.0},
        ]),
    )
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {"bindings": [{"id": "AP01", "bssids": ["AA:BB:CC:01:01:01"]}]},
    )

    cfg = assemble_from_blueprint(blueprint, bindings)
    assert [r.id for r in cfg.routers] == ["AP01"]


def test_load_bindings_accepts_legacy_routers_shape(tmp_path):
    bindings_path = _write(
        tmp_path,
        "wifi-config.json",
        {
            "tx_power": -42,
            "routers": [
                {"id": "AP01", "x": 1.0, "y": 1.0, "bssids": ["AA:BB:CC:01:01:01"]},
            ],
        },
    )
    bindings = load_bindings(bindings_path)
    assert [b.id for b in bindings.bindings] == ["AP01"]
    assert bindings.bindings[0].bssids == ["AA:BB:CC:01:01:01"]


def test_bindings_from_dict_keeps_legacy_per_router_params():
    bindings = bindings_from_dict(
        {
            "routers": [
                {
                    "id": "AP01",
                    "x": 1.0,
                    "y": 1.0,
                    "bssids": ["AA:BB:CC:01:01:01"],
                    "tx_power": -39.0,
                    "path_loss_n": 2.4,
                }
            ]
        }
    )
    # x/y dropped (they come from the blueprint), but the per-AP calibration
    # survives the lift so an old config imports without losing its fit.
    assert bindings.bindings[0].tx_power == -39.0
    assert bindings.bindings[0].path_loss_n == 2.4


def test_write_bindings_roundtrips_full_fidelity(tmp_path):
    path = tmp_path / "wifi-config.json"
    original = bindings_from_dict(
        {
            "tx_power": -40,
            "path_loss_n": 3.0,
            "bindings": [
                {
                    "id": "AP07",
                    "bssids": ["C8:B5:AD:CA:98:18"],
                    "tx_power": -39.29,
                    "path_loss_n": 2.5,
                }
            ],
            "calibration_samples": [
                {
                    "id": "s1",
                    "x_m": 1.0,
                    "y_m": 2.0,
                    "rssi_by_anchor": {"C8:B5:AD:CA:98:18": -55.0},
                    "n_scans": 10,
                    "ts": 1.0,
                }
            ],
        }
    )
    write_bindings(path, original)
    back = load_bindings(path)
    assert [b.id for b in back.bindings] == ["AP07"]
    assert back.bindings[0].bssids == ["C8:B5:AD:CA:98:18"]
    assert back.bindings[0].tx_power == -39.29
    assert len(back.calibration_samples) == 1


def test_load_wifi_config_blueprint_mode(tmp_path):
    blueprint = _write(
        tmp_path,
        "layout.json",
        _blueprint([{"id": "AP01", "technology": "wifi", "x": 1.0, "y": 2.0}]),
    )
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {"bindings": [{"id": "AP01", "bssids": ["AA:BB:CC:01:01:01"]}]},
    )

    cfg = load_wifi_config(bindings, blueprint)
    assert cfg.routers[0].id == "AP01"
    assert (cfg.routers[0].x, cfg.routers[0].y) == (1.0, 2.0)


def test_load_wifi_config_legacy_mode_when_no_blueprint(tmp_path):
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {
            "room_w": 10,
            "room_h": 20,
            "routers": [
                {"id": "AP01", "x": 5.0, "y": 5.0, "bssids": ["AA:BB:CC:01:01:01"]},
            ],
        },
    )
    cfg = load_wifi_config(bindings, blueprint_path=None)
    assert cfg.room_w == 10
    assert cfg.routers[0].id == "AP01"


def test_load_wifi_config_errors_without_positions_and_no_blueprint(tmp_path):
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {"bindings": [{"id": "AP01", "bssids": ["AA:BB:CC:01:01:01"]}]},
    )
    with pytest.raises(ValueError):
        load_wifi_config(bindings, blueprint_path=None)


def test_assemble_handles_v1_legacy_blueprint(tmp_path):
    blueprint = _write(
        tmp_path,
        "layout.json",
        {
            "room_w": 13,
            "room_h": 32,
            "aps": [
                {"id": "AP01", "technology": "wifi", "x": 5.0, "y": 5.0},
            ],
        },
    )
    bindings = _write(
        tmp_path,
        "wifi-config.json",
        {"bindings": [{"id": "AP01", "bssids": ["AA:BB:CC:01:01:01"]}]},
    )

    cfg = assemble_from_blueprint(blueprint, bindings)
    assert cfg.room_w == 13
    assert cfg.room_h == 32
    assert cfg.routers[0].id == "AP01"
