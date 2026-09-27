"""Blueprint migration to version 3. The example pair under schema/examples is
the same venue in version 2 and version 3."""

import json
import math
from pathlib import Path

import pytest

from app.blueprint import floor_plan_from_blueprint
from app.blueprint_migration import blueprint_version, migrate_blueprint
from app.services.geo import room_to_venue

EXAMPLES = Path(__file__).resolve().parents[3] / "schema" / "examples"


def _load(name):
    return json.loads((EXAMPLES / name).read_text())


def test_v2_example_migrates_to_the_v3_example():
    assert migrate_blueprint(_load("layout.v2.example.json")) == _load("layout.example.json")


def test_v3_is_returned_unchanged():
    v3 = _load("layout.example.json")
    assert migrate_blueprint(v3) is v3


def test_migration_mirrors_each_level_on_its_parent_depth():
    v3 = migrate_blueprint(_load("layout.v2.example.json"))
    lab = v3["rooms"][0]
    # Plan depth 30, room top-left at y 6 with depth 8: lower-left at 30 - 14.
    assert (lab["x_m"], lab["y_m"], lab["depth_m"]) == (4.0, 16.0, 8)
    # An anchor 1 m below the room's top edge is 7 m above its bottom edge.
    ap01 = lab["anchors"][0]
    assert (ap01["x"], ap01["y"], ap01["z"]) == (1.0, 7.0, 2.7)
    assert v3["floor_plans"][0]["georef"]["depth_m"] == 30
    assert "height_m" not in v3["floor_plans"][0]["georef"]


def test_migration_drops_the_legacy_mirror():
    v3 = migrate_blueprint(_load("layout.v2.example.json"))
    for key in ("room_w", "room_h", "aps", "gps_origin", "walls", "floor_plan_image"):
        assert key not in v3


def test_rotated_room_places_anchors_where_the_v2_editor_did():
    # The v2 editor rotated a room about its centre in canvas coordinates
    # (y down) and mirrored on the floor-plan depth to reach the georef frame.
    v2 = _load("layout.v2.example.json")
    room = v2["rooms"][1]
    anchor = room["anchors"][0]
    plan_depth = v2["floor_plans"][0]["georef"]["height_m"]
    rot = math.radians(room["rotation_deg"])
    cx = room["x_m"] + room["width_m"] / 2
    cy = room["y_m"] + room["height_m"] / 2
    dx = room["x_m"] + anchor["x"] - cx
    dy = room["y_m"] + anchor["y"] - cy
    expected = (
        cx + dx * math.cos(rot) - dy * math.sin(rot),
        plan_depth - (cy + dx * math.sin(rot) + dy * math.cos(rot)),
    )
    v3 = migrate_blueprint(v2)
    placement = floor_plan_from_blueprint(v3).rooms["room-02"]
    migrated_anchor = v3["rooms"][1]["anchors"][0]
    got = room_to_venue(migrated_anchor["x"], migrated_anchor["y"], placement)
    assert got == pytest.approx(expected)


def test_plan_depth_falls_back_to_the_rooms_extent():
    v2 = {"version": 2, "floor_plans": [{"id": "fp", "georef": {"width_m": 0, "height_m": 0}}],
          "rooms": [{"id": "r", "floor_plan_id": "fp", "x_m": 0, "y_m": 2, "width_m": 5, "height_m": 3}]}
    room = migrate_blueprint(v2)["rooms"][0]
    # Extent 5 (2 + 3): the room touches the top edge, so its bottom is at 0.
    assert room["y_m"] == 0.0


def test_v1_floor_plan_seed_becomes_a_georeferenced_floor_plan():
    v1 = {"version": 1,
          "gps_origin": {"latitude": 59.4, "longitude": 17.9, "azimuth_deg": 0.0, "altitude_m": 30.0},
          "floors": [{"id": 0, "label": "Ground", "width_m": 20.0, "depth_m": 30.0}]}
    v3 = migrate_blueprint(v1)
    assert v3["version"] == 3 and v3["rooms"] == []
    georef = v3["floor_plans"][0]["georef"]
    assert (georef["latitude"], georef["depth_m"], georef["altitude_m"]) == (59.4, 30.0, 30.0)


@pytest.mark.parametrize("raw, version", [
    ({"version": 3}, 3), ({"version": "2.1", "rooms": []}, 2),
    ({"rooms": []}, 2), ({"gps_origin": {}}, 1),
])
def test_blueprint_version_reads_every_stored_form(raw, version):
    assert blueprint_version(raw) == version
