import json
import re
from pathlib import Path

from app.mapper import map_fetch_diagnostics, map_stream_diagnostics
from app.schema import DiagnosticsBlock, DiagnosticsFetch, PathSpec


def test_unknown_key_goes_to_the_extension_bag():
    block = DiagnosticsBlock(
        stream={"battery": PathSpec(path="b"), "temperature": PathSpec(path="t")}
    )
    out = map_stream_diagnostics(block, {"b": 84, "t": 22.5})
    assert out["battery"] == 84
    assert out["vendorSpecific"] == {"temperature": 22.5}


def test_moving_derived_from_speed_over_threshold():
    block = DiagnosticsBlock(stream={"speed": PathSpec(path="v")})
    assert map_stream_diagnostics(block, {"v": 0.9})["moving"] is True
    assert map_stream_diagnostics(block, {"v": 0.0})["moving"] is False


def test_speed_is_consumed_not_emitted():
    block = DiagnosticsBlock(stream={"speed": PathSpec(path="v")})
    out = map_stream_diagnostics(block, {"v": 0.9})
    assert "speed" not in out
    assert out.get("vendorSpecific", {}).get("speed") is None


def test_explicit_moving_wins_over_derivation():
    block = DiagnosticsBlock(
        stream={"speed": PathSpec(path="v"), "moving": PathSpec(path="m")}
    )
    out = map_stream_diagnostics(block, {"v": 0.9, "m": False})
    assert out["moving"] is False


def test_no_vendorSpecific_key_when_all_core():
    block = DiagnosticsBlock(stream={"battery": PathSpec(path="b")})
    assert "vendorSpecific" not in map_stream_diagnostics(block, {"b": 50})


def test_fetch_mapping_routes_the_same():
    fetch = DiagnosticsFetch(
        path="/d", mapping={"lastSeen": PathSpec(path="ts"), "rssi": PathSpec(path="r")}
    )
    out = map_fetch_diagnostics(fetch, {"ts": 1700000000, "r": -60})
    assert out["lastSeen"] == 1700000000
    assert out["vendorSpecific"] == {"rssi": -60}


_ARTIFACT = (
    Path(__file__).resolve().parents[3]
    / "spec" / "private-profile" / "diagnostics-vocabulary.json"
)


def test_core_names_follow_the_profile_convention():
    # Core names are this project's, anchored to an external DEFINITION rather
    # than an inherited spelling: LwM2M identifies battery level by the numeric
    # resource 3/0/9 and defines no JSON field name at all.
    vocab = json.loads(_ARTIFACT.read_text())
    for name in vocab["core"]:
        assert re.fullmatch(r"[a-z]+([A-Z][a-z0-9]*)*", name), name
    assert vocab["extensionBag"] == "vendorSpecific"
    assert "lastSeen" in vocab["core"]


def test_every_core_entry_still_records_its_source_definition():
    # Renaming the field must not lose the anchoring; that is what `standard` is for.
    vocab = json.loads(_ARTIFACT.read_text())
    for name, spec in vocab["core"].items():
        assert spec.get("standard"), name
