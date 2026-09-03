from app.mapper import map_fetch_diagnostics, map_stream_diagnostics
from app.schema import DiagnosticsBlock, DiagnosticsFetch, PathSpec


def test_unknown_key_goes_to_x_vendor():
    block = DiagnosticsBlock(
        stream={"battery": PathSpec(path="b"), "temperature": PathSpec(path="t")}
    )
    out = map_stream_diagnostics(block, {"b": 84, "t": 22.5})
    assert out["battery"] == 84
    assert out["x_vendor"] == {"temperature": 22.5}


def test_moving_derived_from_speed_over_threshold():
    block = DiagnosticsBlock(stream={"speed": PathSpec(path="v")})
    assert map_stream_diagnostics(block, {"v": 0.9})["moving"] is True
    assert map_stream_diagnostics(block, {"v": 0.0})["moving"] is False


def test_speed_is_consumed_not_emitted():
    block = DiagnosticsBlock(stream={"speed": PathSpec(path="v")})
    out = map_stream_diagnostics(block, {"v": 0.9})
    assert "speed" not in out
    assert out.get("x_vendor", {}).get("speed") is None


def test_explicit_moving_wins_over_derivation():
    block = DiagnosticsBlock(
        stream={"speed": PathSpec(path="v"), "moving": PathSpec(path="m")}
    )
    out = map_stream_diagnostics(block, {"v": 0.9, "m": False})
    assert out["moving"] is False


def test_no_x_vendor_key_when_all_core():
    block = DiagnosticsBlock(stream={"battery": PathSpec(path="b")})
    assert "x_vendor" not in map_stream_diagnostics(block, {"b": 50})


def test_fetch_mapping_routes_the_same():
    fetch = DiagnosticsFetch(
        path="/d", mapping={"last_seen": PathSpec(path="ts"), "rssi": PathSpec(path="r")}
    )
    out = map_fetch_diagnostics(fetch, {"ts": 1700000000, "r": -60})
    assert out["last_seen"] == 1700000000
    assert out["x_vendor"] == {"rssi": -60}
